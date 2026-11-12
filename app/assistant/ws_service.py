"""The workspace tab service: create a tab from a governed SQL answer, keep its versions, undo, rename, close.

A tab keeps checked SQL, never rows. Every change to the SQL is a new version; the oldest versions are dropped past
MAX_VERSIONS. Access to the SQL itself is decided by catalogue_for(user) and check_sql at the moment a tab is made.

Callers fetch a tab with owner=user (WorkspaceTab.objects.get(pk=..., owner=user)); these functions do not check ownership.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.db import transaction
from hr_sql.catalogue import catalogue_for
from hr_sql.host import HrHost
from sqlcore.check import CheckError, check_sql
from sqlcore.limits import Limits
from sqlcore.runner import Host, Refused, run_question
from sqlcore.tools import describe_text

from assistant import sqlanswer
from assistant.models import HelpQuestion, Outcome, WorkspaceMessage, WorkspaceTab, WorkspaceVersion
from assistant.providers import Provider
from assistant.sqlanswer import (
    MAX_ATTEMPTS,
    NO_VIEWS_REASON,
    NOT_ANSWERABLE_REASON,
    OFF_REASON,
    PROVIDER_REASON,
    UNAVAILABLE_REASON,
)
from assistant.sqlask import SqlReply, ask_refine_sql_reply, ask_sql_reply
from assistant.verified import examples_for
from assistant.ws_limits import MAX_TABS, MAX_VERSIONS
from assistant.ws_run import base_columns, run_count
from assistant.ws_sql import Spec, spec_from_json

logger = logging.getLogger(__name__)

TITLE_MAX = 80  # the tab title column is 80 characters
DEFAULT_TITLE = "Шинэ хүснэгт"  # the title of a tab made without a question


class WorkspaceLimit(Exception):
    """The viewer may not open another tab. The message is for the user."""


def _tab_limit_message() -> str:
    return f"Нээлттэй хүснэгт {MAX_TABS} байна. Нэгийг хаагаад дахин оролдоно уу."


def _lock_owner(user: User) -> None:
    """Serialise tab creation for one viewer. Call once, first, inside transaction.atomic()."""
    User.objects.select_for_update().filter(pk=user.pk).first()


def _ensure_room(user: User) -> None:
    """Refuse when the viewer already keeps MAX_TABS tabs. The caller must hold _lock_owner(user)."""
    if WorkspaceTab.objects.filter(owner=user).count() >= MAX_TABS:
        raise WorkspaceLimit(_tab_limit_message())


def _lock_tab(tab: WorkspaceTab) -> bool:
    """Lock the tab's row until the transaction ends. False when the tab no longer exists. Call inside atomic()."""
    return WorkspaceTab.objects.select_for_update().filter(pk=tab.pk).first() is not None


def tabs_of(user: User) -> list[WorkspaceTab]:
    """The viewer's tabs, oldest first."""
    return list(WorkspaceTab.objects.filter(owner=user).order_by("created_at", "id"))


def open_from_question(user: User, question: HelpQuestion) -> WorkspaceTab:
    """The tab for a governed SQL answer the viewer asked. Reuses the tab already made from that answer.

    Raises PermissionError when the answer is not the viewer's, is not an SQL answer, has no SQL, or its SQL no
    longer passes the checker for the viewer's catalogue (nothing is created then). Raises WorkspaceLimit past
    MAX_TABS; the reuse check comes first, so an existing tab can always be opened.
    """
    if question.user_id != user.pk or question.outcome != Outcome.SQL or not question.sql:
        raise PermissionError("Энэ асуултыг нээх эрхгүй.")
    with transaction.atomic():
        # Lock the owner before the reuse lookup: otherwise two requests for the same answer can both miss the lookup
        # and each create a tab. The lock is taken once here; _ensure_room only counts.
        _lock_owner(user)
        existing = WorkspaceTab.objects.filter(owner=user, source=question).first()
        if existing is not None:
            return existing
        try:
            checked = check_sql(question.sql, catalogue_for(user))
        except CheckError as exc:
            raise PermissionError("Энэ асуултын SQL одоо ашиглах эрхгүй байна.") from exc
        _ensure_room(user)
        tab = WorkspaceTab.objects.create(
            owner=user,
            title=question.question[:TITLE_MAX],
            source=question,
        )
        WorkspaceVersion.objects.create(
            tab=tab, question=question.question, sql=checked.sql, settings="", labels=question.sql_labels
        )
    return tab


def new_tab(user: User, title: str = DEFAULT_TITLE) -> WorkspaceTab:
    """A tab with no version yet. Raises WorkspaceLimit past MAX_TABS."""
    with transaction.atomic():
        _lock_owner(user)
        _ensure_room(user)
        return WorkspaceTab.objects.create(owner=user, title=title[:TITLE_MAX])


def add_version(
    tab: WorkspaceTab, question: str, sql: str, settings: str = "", labels: str = ""
) -> WorkspaceVersion:
    """Save a new current version of the tab. Drops the oldest versions beyond MAX_VERSIONS.

    `sql` must be a CheckedQuery.sql, that is, the output of check_sql for the viewer's catalogue. Callers must never
    pass raw model or user text here. Running the saved SQL re-checks it anyway.
    """
    with transaction.atomic():
        _lock_tab(tab)
        version = WorkspaceVersion.objects.create(
            tab=tab, question=question, sql=sql, settings=settings, labels=labels
        )
        stale = list(
            tab.versions.order_by("-id").values_list("id", flat=True)[MAX_VERSIONS:]
        )
        if stale:
            WorkspaceVersion.objects.filter(pk__in=stale).delete()
        tab.save(update_fields=["updated_at"])
    return version


def undo(tab: WorkspaceTab) -> WorkspaceVersion | None:
    """Go back one version: delete the current version when the tab has more than one. A tab keeps its first version.

    Returns the version that is current afterwards, or None when the tab has no version.
    """
    with transaction.atomic():
        _lock_tab(tab)
        current = tab.current()
        if current is None:
            return None
        if tab.versions.count() > 1:
            current.delete()
            tab.save(update_fields=["updated_at"])
            return tab.current()
        return current


def rename(tab: WorkspaceTab, title: str) -> None:
    """Change the tab's title (cut to TITLE_MAX characters)."""
    with transaction.atomic():
        _lock_tab(tab)
        tab.title = title[:TITLE_MAX]
        tab.save(update_fields=["title", "updated_at"])


def close(tab: WorkspaceTab) -> None:
    """Delete the tab and its versions and messages. A tab that is already gone is left alone (no error)."""
    with transaction.atomic():
        if not _lock_tab(tab):
            return
        tab.delete()


REFINED_TEXT = "Хүснэгтийг шинэчиллээ."  # the assistant's line after a refinement that worked, when no count is known
UNDONE_TEXT = "Өмнөх хувилбар руу буцлаа."  # the assistant's line after an undo, when no count is known
ROW_UNIT = "мөр"
GROUP_UNIT = "бүлэг"
# Reasons are English (log and result). Each one that the viewer can be told about has a Mongolian stored line.
CHANGED_REASON = "The table changed while you were asking."
TAB_GONE_REASON = "The table was closed while you were asking."
BASE_REASON = "The saved query cannot be run for you any more."
ERROR_REASON = "The refinement failed unexpectedly."
CHANGED_LINE = "Хүснэгт хооронд өөрчлөгдсөн байна. Дахин илгээнэ үү."
PROVIDER_LINE = "Асуултад одоогоор хариулах боломжгүй байна. Дахин оролдоно уу."
NOT_ANSWERABLE_LINE = "Харах боломжтой өгөгдлөөр энэ асуултад хариулах боломжгүй байна."
REFUSED_LINE = "Хүснэгтийг шинэчлэх боломжгүй байна. Асуултаа өөрөөр томъёолж үзнэ үү."
BASE_LINE = "Хадгалсан хүснэгтийн асуулга танд одоо ажиллахгүй байна. Шинэ хүснэгт нээнэ үү."
OFF_LINE = "Өгөгдлөөс хариулт авах боломж одоо унтраалттай байна."
UNAVAILABLE_LINE = "Өгөгдөлд одоо хандах боломжгүй байна."
NO_VIEWS_LINE = "Таны харах өгөгдлийн хүснэгт алга байна."
ERROR_LINE = "Алдаа гарлаа. Дахин оролдоно уу."


@dataclass(frozen=True)
class RefineResult:
    status: str  # "ok", "refused", "off" or "unavailable"
    reason: str  # "" when ok; an English reason otherwise
    version: WorkspaceVersion | None  # the new current version when ok; None otherwise
    total: int | None = None  # how many rows the new version has, when ok and the count could be run


def refined_line(before: int | None, after: int | None) -> str:
    """The assistant's line after a refinement that worked: it names the row counts when they are known, so a result
    that went to zero rows is not reported in the same words as one that did not."""
    if after is None:
        return REFINED_TEXT
    if before is None:
        return f"{REFINED_TEXT[:-1]}: {after} {ROW_UNIT}."
    return f"{REFINED_TEXT[:-1]}: {before} → {after} {ROW_UNIT}."


def undone_line(total: int | None, unit: str = ROW_UNIT) -> str:
    """The assistant's line after an undo, with the row (or group) count of the version that is current again."""
    return UNDONE_TEXT if total is None else f"{UNDONE_TEXT[:-1]}: {total} {unit}."


def _total(user: object, sql: str, governed: Host, settings: str = "") -> tuple[int | None, str]:
    """How many rows (or groups, when the saved settings group) the saved SQL gives the viewer, and the unit word.
    The count is None when it cannot be run; a line is then written without a number. Never raises."""
    try:
        base = base_columns(user, sql, host=governed)
        if base.status != "ok":
            return None, ROW_UNIT
        spec = spec_from_json(settings, base.columns)
        unit = GROUP_UNIT if spec.group_by else ROW_UNIT
        return run_count(user, sql, base.columns, spec, host=governed), unit
    except Exception as error:
        logger.warning("workspace count failed (%s)", type(error).__name__)
        return None, ROW_UNIT


def note_undo(user: User, tab: WorkspaceTab, version: WorkspaceVersion, host: Host | None = None) -> None:
    """Store the assistant's line that says an undo happened, so the chat log does not end on the undone exchange.
    A tab closed meanwhile stores nothing."""
    total, unit = _total(user, version.sql, host if host is not None else HrHost(), version.settings)
    with transaction.atomic():
        if not _lock_tab(tab):
            return
        WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.ASSISTANT, text=undone_line(total, unit))


def _stored_line(status: str, reason: str) -> str:
    """The Mongolian assistant line stored for an outcome. The English reason is never stored."""
    if status == "ok":
        return REFINED_TEXT
    lines = {
        PROVIDER_REASON: PROVIDER_LINE,
        NOT_ANSWERABLE_REASON: NOT_ANSWERABLE_LINE,
        OFF_REASON: OFF_LINE,
        UNAVAILABLE_REASON: UNAVAILABLE_LINE,
        NO_VIEWS_REASON: NO_VIEWS_LINE,
        CHANGED_REASON: CHANGED_LINE,
        BASE_REASON: BASE_LINE,
        ERROR_REASON: ERROR_LINE,
    }
    return lines.get(reason, REFUSED_LINE)


def _store_line(tab: WorkspaceTab, text: str) -> bool:
    """Store the viewer's line in its own transaction, before any model call. False when the tab no longer exists."""
    with transaction.atomic():
        if not _lock_tab(tab):
            return False
        WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text=text)
    return True


def _finish(
    tab: WorkspaceTab,
    text: str,
    status: str,
    reason: str,
    sql: str,
    base_pk: int | None,
    first_build: bool,
    ok_line: str = REFINED_TEXT,
    total: int | None = None,
    labels: str = "",
) -> RefineResult:
    """Store the new version when ok, then the assistant's line: one transaction under the tab's row lock.

    base_pk is the current version the refinement was made from (None for an empty tab). When the tab's current
    version changed while the model was asked, the refinement is refused and no version is added (lost-update guard).
    When the tab was closed meanwhile, nothing is stored. A failed refinement adds no version. The first build takes
    the question as the title when the title, re-read under the lock, is still the default.
    """
    version = None
    with transaction.atomic():
        if not _lock_tab(tab):
            return RefineResult(status="refused", reason=TAB_GONE_REASON, version=None)
        if status == "ok":
            latest = tab.versions.order_by("-id").values_list("id", flat=True).first()
            if latest != base_pk:
                status, reason = "refused", CHANGED_REASON
            else:
                version = add_version(tab, text, sql, labels=labels)
                title = WorkspaceTab.objects.values_list("title", flat=True).get(pk=tab.pk)
                if first_build and title == DEFAULT_TITLE:
                    rename(tab, text)
        WorkspaceMessage.objects.create(
            tab=tab,
            role=WorkspaceMessage.Role.ASSISTANT,
            text=ok_line if status == "ok" else _stored_line(status, reason),
        )
    ok = status == "ok"
    return RefineResult(status=status, reason="" if ok else reason, version=version, total=total if ok else None)


def _give_up(tab: WorkspaceTab, text: str, base_pk: int | None) -> RefineResult:
    """The refinement failed after the viewer's line was stored: one generic assistant line, no version."""
    try:
        return _finish(tab, text, "refused", ERROR_REASON, "", base_pk, first_build=False)
    except Exception as error:
        logger.warning("refine_tab: could not store the failure (%s)", type(error).__name__)
        return RefineResult(status="refused", reason=ERROR_REASON, version=None)


def _attempts(user: object, governed: Host, ask: Callable[[str], SqlReply]) -> tuple[str, str, str, str]:
    """Ask the model for SQL and validate it with run_question (one row allowed), at most MAX_ATTEMPTS times.

    `ask` takes the refusal text of the previous attempt ("" the first time). Returns (status, reason, checked sql,
    labels): the labels are the model's column headings as JSON text, kept only for the attempt that worked ("" else).
    A provider failure or an empty reply stops at once; only a checker or run refusal is fed back.
    """
    refusal = ""
    for _attempt in range(MAX_ATTEMPTS):
        try:
            reply = ask(refusal)
        except Exception as error:
            # Only the exception type is logged: its message can carry keys or payloads. Never shown to the viewer.
            logger.warning("refine_tab: provider call failed (%s)", type(error).__name__)
            return "refused", PROVIDER_REASON, "", ""
        if not reply.sql.strip():
            return "refused", NOT_ANSWERABLE_REASON, "", ""
        outcome = run_question(governed, user, reply.sql, Limits(max_rows=1))
        if isinstance(outcome, Refused):
            refusal = outcome.reason
            continue
        return "ok", "", outcome.query.sql, json.dumps(reply.labels, ensure_ascii=False)
    return "refused", refusal or NOT_ANSWERABLE_REASON, "", ""


def _carried_labels(old: str, new: str) -> str:
    """The previous version's labels with the new ones on top, as JSON text. A refinement often leaves out labels it
    did not change; a stale key is harmless, as only the result's own columns are looked up. Bad JSON counts as {}."""

    def parsed(text: str) -> dict[str, str]:
        try:
            value = json.loads(text) if text else {}
        except ValueError:
            return {}
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    return json.dumps({**parsed(old), **parsed(new)}, ensure_ascii=False)


def refine_tab(
    user: User,
    tab: WorkspaceTab,
    text: str,
    day: date,
    provider: Provider,
    host: Host | None = None,
) -> RefineResult:
    """Change the tab's SQL to satisfy the viewer's line, or say why it cannot. Never raises.

    A tab with no version yet is built from the line (ask_sql). A tab with a version is refined: the model gets the
    current SQL, its base columns (one row run) and the tab's stored messages from before this line. Either way the
    model's SQL is checked and run as the viewer before it is kept. The viewer's line is stored before the model is
    asked; one Mongolian assistant line and, on success, the new version are stored at the end.

    Intended: when the saved SQL no longer passes for the viewer (base query refused), it returns a refusal with no
    model call, so the tab shows the refusal and no old rows. Any failure after the viewer's line is stored ends with
    one generic assistant line and no version. A tab closed meanwhile stores nothing and returns a refusal.
    """
    try:
        history = [(message.role, message.text) for message in tab.messages.order_by("id")]  # before this turn's line
        current = tab.current()
        base_pk = current.pk if current is not None else None
        if not _store_line(tab, text):
            return RefineResult(status="refused", reason=TAB_GONE_REASON, version=None)
    except Exception as error:
        logger.warning("refine_tab: could not start (%s)", type(error).__name__)
        return RefineResult(status="refused", reason=ERROR_REASON, version=None)

    try:
        return _turn(user, tab, text, day, provider, host, current, base_pk, history)
    except Exception as error:
        logger.warning("refine_tab: failed after the line was stored (%s)", type(error).__name__)
        return _give_up(tab, text, base_pk)


def _turn(
    user: User,
    tab: WorkspaceTab,
    text: str,
    day: date,
    provider: Provider,
    host: Host | None,
    current: WorkspaceVersion | None,
    base_pk: int | None,
    history: list[tuple[str, str]],
) -> RefineResult:
    """The model work of refine_tab, after the viewer's line is stored. Its outcome is stored by _finish."""
    if not sqlanswer._setting_enabled():
        return _finish(tab, text, "off", OFF_REASON, "", base_pk, first_build=False)
    if not sqlanswer._database_ready():
        return _finish(tab, text, "unavailable", UNAVAILABLE_REASON, "", base_pk, first_build=False)

    governed: Host = host if host is not None else HrHost()
    catalogue = governed.catalogue_for(user)
    if not catalogue.views:
        return _finish(tab, text, "unavailable", NO_VIEWS_REASON, "", base_pk, first_build=False)
    catalogue_text = describe_text(catalogue)

    if current is None:
        examples = examples_for(catalogue, text)
        status, reason, sql, labels = _attempts(
            user,
            governed,
            lambda refusal: ask_sql_reply(provider, catalogue_text, text, day, refusal=refusal, examples=examples),
        )
        after = _total(user, sql, governed)[0] if status == "ok" else None
        return _finish(
            tab,
            text,
            status,
            reason,
            sql,
            base_pk,
            first_build=True,
            ok_line=refined_line(None, after),
            total=after,
            labels=labels,
        )

    base = base_columns(user, current.sql, host=governed)
    if base.status == "refused":
        return _finish(tab, text, "refused", BASE_REASON, "", base_pk, first_build=False)
    if base.status != "ok":
        return _finish(tab, text, base.status, base.reason, "", base_pk, first_build=False)
    columns = base.columns
    status, reason, sql, labels = _attempts(
        user,
        governed,
        lambda refusal: ask_refine_sql_reply(
            provider, catalogue_text, current.sql, columns, history, text, day, refusal=refusal
        ),
    )
    before = after = None
    if status == "ok":  # counted only for a refinement that worked: a refused one costs no extra run
        try:
            before = run_count(user, current.sql, columns, Spec(), host=governed)
        except Exception as error:
            logger.warning("workspace count failed (%s)", type(error).__name__)
        after = _total(user, sql, governed)[0]
        labels = _carried_labels(current.labels, labels)
    return _finish(
        tab,
        text,
        status,
        reason,
        sql,
        base_pk,
        first_build=False,
        ok_line=refined_line(before, after),
        total=after,
        labels=labels,
    )

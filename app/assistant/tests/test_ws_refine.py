"""Tests for refine_tab (Task 7): the chat that changes an open tab's SQL.

The provider is a fake that returns the replies it is given, in order, and can run a hook during a call. The host is a
fake that returns fixed columns. The gate is patched on assistant.sqlanswer, the same seams sqlanswer uses. The DB is
used for tabs and messages.
"""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, check_sql
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_service
from assistant.models import WorkspaceMessage, WorkspaceTab
from assistant.sqlanswer import NOT_ANSWERABLE_REASON, OFF_REASON, PROVIDER_REASON
from assistant.ws_service import (
    BASE_LINE,
    BASE_REASON,
    CHANGED_LINE,
    CHANGED_REASON,
    DEFAULT_TITLE,
    ERROR_LINE,
    ERROR_REASON,
    NOT_ANSWERABLE_LINE,
    OFF_LINE,
    PROVIDER_LINE,
    REFUSED_LINE,
    TAB_GONE_REASON,
)

DAY = date(2026, 11, 12)
EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name"), Column("DEPT", "department")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
BAD_SQL = "SELECT NAME FROM NO_SUCH_VIEW"
NEW_SQL = "SELECT ID, NAME, DEPT FROM GOV_EMPLOYEES"
# Lower-case keywords, odd spacing and a lower-case view name: check_sql must rewrite it, so the stored SQL differs.
RAW_SQL = "select  ID,NAME,DEPT from gov_employees"
OTHER_SQL = "SELECT ID FROM GOV_EMPLOYEES"
COLUMNS = ("ID", "NAME")


class FakeProvider:
    """Returns the queued replies in order. An exception in the queue is raised instead. Records every call.

    `on_call`, when given, runs before each reply is taken: it lets a test change the tab while the model is asked.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, *replies: Any, on_call: Callable[[], None] | None = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls.append((system, user))
        if self.on_call is not None:
            self.on_call()
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeHost:
    """A host with one catalogue. execute returns the fixed columns and one row, as the Protocol says."""

    def __init__(self, catalogue: Catalogue = CATALOGUE) -> None:
        self.catalogue = catalogue
        self.execute_calls: list[CheckedQuery] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogue

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append(query)
        return Result(columns=COLUMNS, rows=(("1", "Aigerim"),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)


def _tab_with_version(user: Any, sql: str = SQL) -> WorkspaceTab:
    tab = ws_service.new_tab(user, title="Ажилтнууд")
    ws_service.add_version(tab, "Ажилтнууд", sql)
    return tab


def _history_block(user_text: str) -> str:
    """The text between the <history> tags of a refinement prompt."""
    start = user_text.index("<history>\n") + len("<history>\n")
    return user_text[start : user_text.index("\n</history>", start)]


def test_refine_adds_version_with_default_settings(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": NEW_SQL})

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "ok"
    assert result.reason == ""
    assert result.version is not None
    assert result.version.sql == check_sql(NEW_SQL, CATALOGUE).sql
    assert result.version.settings == ""
    assert tab.current().pk == result.version.pk
    assert tab.versions.count() == 2
    # The refinement prompt carries the current SQL and its columns as data.
    assert "<current>" in provider.calls[0][1] and "<columns>" in provider.calls[0][1]


def test_stored_sql_is_the_checked_form(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    checked = check_sql(RAW_SQL, CATALOGUE).sql
    assert checked != RAW_SQL  # the input really is normalised by the checker

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider({"sql": RAW_SQL}), host=FakeHost())

    assert result.status == "ok"
    assert result.version.sql == checked
    assert tab.current().sql == checked


def test_failed_refine_keeps_versions_and_logs_messages(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": BAD_SQL}, {"sql": BAD_SQL})

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason != ""
    assert result.version is None
    assert tab.versions.count() == 1
    assert tab.current().sql == SQL
    messages = list(WorkspaceMessage.objects.filter(tab=tab).order_by("id"))
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].text == "Хэлтсийг нэм"
    # The stored line is Mongolian and generic: the English checker reason is not shown.
    assert messages[1].text == REFUSED_LINE
    assert messages[1].text != result.reason


def test_first_question_in_empty_tab_creates_version_one(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    provider = FakeProvider({"sql": SQL})

    result = ws_service.refine_tab(user, tab, "Нийт ажилтан", DAY, provider, host=FakeHost())

    assert result.status == "ok"
    assert tab.versions.count() == 1
    assert result.version.sql == check_sql(SQL, CATALOGUE).sql
    assert result.version.question == "Нийт ажилтан"
    # The default title is replaced by the question; the first build uses ask_sql, not the refine prompt.
    tab.refresh_from_db()
    assert tab.title == "Нийт ажилтан"
    assert "<current>" not in provider.calls[0][1]
    assert [m.text for m in WorkspaceMessage.objects.filter(tab=tab).order_by("id")] == [
        "Нийт ажилтан",
        "Хүснэгтийг шинэчиллээ.",
    ]


def test_custom_title_is_not_replaced(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user, title="Өөрийн нэр")
    result = ws_service.refine_tab(user, tab, "Нийт ажилтан", DAY, FakeProvider({"sql": SQL}), host=FakeHost())

    assert result.status == "ok"
    tab.refresh_from_db()
    assert tab.title == "Өөрийн нэр"
    assert DEFAULT_TITLE != "Өөрийн нэр"


def test_refine_retries_once_on_refusal(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": BAD_SQL}, {"sql": NEW_SQL})

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "ok"
    assert len(provider.calls) == 2
    # The second call carries the refusal of the first, as data.
    assert "<refusal>" in provider.calls[1][1]
    assert tab.versions.count() == 2


def test_refuses_after_max_attempts_without_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": BAD_SQL}, {"sql": BAD_SQL}, {"sql": NEW_SQL})

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert len(provider.calls) == 2  # MAX_ATTEMPTS, the third reply is never asked for
    assert tab.versions.count() == 1


def test_empty_sql_reply_is_not_answerable(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": ""}, {"sql": NEW_SQL})

    result = ws_service.refine_tab(user, tab, "Хүйсээр ангил", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason == NOT_ANSWERABLE_REASON
    assert len(provider.calls) == 1
    assert tab.versions.count() == 1
    assert WorkspaceMessage.objects.filter(tab=tab).order_by("id").last().text == NOT_ANSWERABLE_LINE


def test_provider_exception_is_generic_and_adds_no_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider(RuntimeError("secret-key-123"))

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason == PROVIDER_REASON
    assert "secret-key-123" not in result.reason
    assert tab.versions.count() == 1
    stored = WorkspaceMessage.objects.filter(tab=tab).order_by("id").last().text
    assert stored == PROVIDER_LINE
    assert "secret-key-123" not in stored


def test_changed_while_asking_adds_no_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    # While the model is asked, another request makes a new current version.
    provider = FakeProvider(
        {"sql": NEW_SQL},
        on_call=lambda: ws_service.add_version(tab, "other", OTHER_SQL),
    )

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason == CHANGED_REASON
    assert result.version is None
    assert tab.versions.count() == 2  # the original plus the other request's version; none from this refinement
    assert tab.current().sql == OTHER_SQL
    messages = list(WorkspaceMessage.objects.filter(tab=tab).order_by("id"))
    assert messages[-1].role == "assistant"
    assert messages[-1].text == CHANGED_LINE


def test_refused_base_query_gives_no_version_and_no_model_call(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user, title="Хуучин")
    ws_service.add_version(tab, "хуучин", BAD_SQL)
    provider = FakeProvider()

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason != ""
    assert result.version is None
    assert provider.calls == []
    assert tab.versions.count() == 1


def test_history_has_earlier_turns_not_this_one(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="Нэгдүгээр асуулт")
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.ASSISTANT, text="Нэгдүгээр хариулт")
    provider = FakeProvider({"sql": NEW_SQL})

    ws_service.refine_tab(user, tab, "Хоёрдугаар зааварчилгаа", DAY, provider, host=FakeHost())

    history = _history_block(provider.calls[0][1])
    assert "user: Нэгдүгээр асуулт" in history
    assert "assistant: Нэгдүгээр хариулт" in history
    assert "Хоёрдугаар зааварчилгаа" not in history


def test_setting_off_stores_lines_and_no_version(db: None, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    provider = FakeProvider()

    result = ws_service.refine_tab(user, tab, "Нийт ажилтан", DAY, provider, host=FakeHost())

    assert result.status == "off"
    assert result.reason == OFF_REASON
    assert result.version is None
    assert provider.calls == []
    assert tab.versions.count() == 0
    messages = list(WorkspaceMessage.objects.filter(tab=tab).order_by("id"))
    assert [m.text for m in messages] == ["Нийт ажилтан", OFF_LINE]


def _last_text(tab: WorkspaceTab) -> str:
    return WorkspaceMessage.objects.filter(tab=tab).order_by("id").last().text


def test_stored_success_line_is_literal(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider({"sql": NEW_SQL}), host=FakeHost())

    assert result.status == "ok"
    assert _last_text(tab) == "Хүснэгтийг шинэчиллээ."


def test_first_question_race_keeps_one_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    # Another request builds the table while this first question is being asked.
    provider = FakeProvider({"sql": NEW_SQL}, on_call=lambda: ws_service.add_version(tab, "other", OTHER_SQL))

    result = ws_service.refine_tab(user, tab, "Нийт ажилтан", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason == CHANGED_REASON
    assert result.version is None
    assert tab.versions.count() == 1
    assert tab.current().sql == OTHER_SQL
    assert _last_text(tab) == CHANGED_LINE


def test_error_after_viewer_line_gives_one_line_and_no_version(db: None, role_user, monkeypatch) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the database went away: secret-detail")

    monkeypatch.setattr(ws_service, "base_columns", boom)
    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider(), host=FakeHost())

    assert result.status == "refused"
    assert result.reason == ERROR_REASON
    assert result.version is None
    assert tab.versions.count() == 1
    messages = list(WorkspaceMessage.objects.filter(tab=tab).order_by("id"))
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].text == "Хэлтсийг нэм"
    assert messages[1].text == ERROR_LINE
    assert "secret-detail" not in messages[1].text


def test_tab_closed_during_call_stores_nothing(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider(
        {"sql": NEW_SQL},
        on_call=lambda: WorkspaceTab.objects.filter(pk=tab.pk).delete(),
    )

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, provider, host=FakeHost())

    assert result.status == "refused"
    assert result.reason == TAB_GONE_REASON
    assert result.version is None
    assert not WorkspaceTab.objects.filter(pk=tab.pk).exists()


def test_base_refusal_has_its_own_line(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user, title="Хуучин")
    ws_service.add_version(tab, "хуучин", BAD_SQL)

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider(), host=FakeHost())

    assert result.status == "refused"
    assert result.reason == BASE_REASON
    assert _last_text(tab) == BASE_LINE
    assert _last_text(tab) != REFUSED_LINE


def test_add_version_makes_the_new_current(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)

    version = ws_service.add_version(tab, "нэг", SQL)

    assert tab.current().pk == version.pk
    assert version.settings == ""


def test_undo_goes_back_one_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    ws_service.add_version(tab, "хоёр", OTHER_SQL)

    current = ws_service.undo(tab)

    assert current is not None
    assert current.sql == SQL
    assert tab.versions.count() == 1


def test_rename_changes_the_title(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)

    ws_service.rename(tab, "Шинэ нэр")

    tab.refresh_from_db()
    assert tab.title == "Шинэ нэр"


def test_refine_stores_the_labels_of_the_attempt_that_worked(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    refused = {"sql": BAD_SQL, "labels": [{"column": "NAME", "label": "Нэр"}]}
    worked = {"sql": NEW_SQL, "labels": [{"column": "id", "label": "Дугаар"}, {"column": "DEPT", "label": "Хэлтэс"}]}

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider(refused, worked), host=FakeHost())

    assert result.status == "ok"
    assert json.loads(result.version.labels) == {"ID": "Дугаар", "DEPT": "Хэлтэс"}
    assert json.loads(tab.current().labels) == {"ID": "Дугаар", "DEPT": "Хэлтэс"}

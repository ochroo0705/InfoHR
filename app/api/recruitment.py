"""Recruitment API under /api/v1/recruitment: the vacancy list, the vacancy page, the vacancy form's options, the budget
line, the candidate page and the purge list, as the React pages read them; and the writes those pages post.

GET /recruitment/vacancies (one batch of the list), GET /recruitment/vacancies/options and /vacancies/slot-line (the
manage right), GET /recruitment/vacancies/{pk} (the vacancy page: its stage bar and one batch of candidates), GET
/recruitment/candidates/{pk} (the candidate page) and GET /recruitment/purge (the manage right). The writes: POST
/recruitment/vacancies (add) and /vacancies/{pk} (edit), POST /vacancies/{pk}/candidates (add a candidate), POST
/candidates/{pk}/move, /reject, /reopen, /comment, /files (CV upload) and /convert, POST /purge, and GET
/recruitment/files/{pk} (the CV download). The rules come from recruitment.services and recruitment.access; this module
reads the request and presents the answer.

Every route of this router runs `_recruitment_auth` first: a signed-in session (401 without one), then the module gate
`_module_on` (404 on every route while the recruitment module is off). A vacancy or candidate the user may not see is
404 (as the Django pages); a visible object whose action needs the manage right is 403 "forbidden". Reads answer
Cache-Control no-store: candidates are personal data. A write answers 200 with RecruitWriteResultOut (ok true, or ok
false with the service's message in `error` or the form's errors); a refused write changes nothing.
"""

from datetime import date, datetime
from typing import Any

from accounts import modules
from accounts.models import User
from config import batching
from django import forms
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from macs.models import Branch, Position
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import django_auth
from recruitment import access
from recruitment.forms import CandidateForm, RejectForm
from recruitment.models import Candidate, Vacancy, VacancyStatus
from recruitment.services import candidate_page, files, pipeline, slot_line, vacancy_page, visibility

from api.errors import ApiError, form_error_payload
from api.params import batch_offset
from api.popups import FORBIDDEN, NOT_FOUND, request_user, service_errors

MODULE_KEY = "recruitment"  # the key in accounts.modules.MODULES
EMPTY_TEXT = "Ажлын байр олдсонгүй"  # the list's text when no row matches (_vacancy_rows.html)
NO_FILE = "Файл сонгоно уу."  # the upload's text when no file part was sent (candidate_file_upload in views.py)
MAX_ID_LENGTH = 18  # the same cap the batch offset uses: a longer number cannot be an id of this database


class RecruitWriteResultOut(Schema):
    """The answer of every recruitment write: ok true, or ok false with the service's message (error) or the form's
    errors (field_errors, form_errors). The same shape as the leave writes; a refused write changes nothing."""

    ok: bool
    error: str
    field_errors: dict[str, list[str]]
    form_errors: list[str]


class RecruitVacancyCreatedOut(RecruitWriteResultOut):
    id: int | None = None  # the new vacancy's id when the add is saved; null on a refusal


class RecruitChoiceOut(Schema):
    id: int
    label: str


class RecruitStringChoiceOut(Schema):
    value: str
    label: str


class RecruitCountsOut(Schema):
    new: int
    screening: int
    interview: int
    offer: int
    hired: int


class RecruitVacancyRowOut(Schema):
    id: int
    title: str
    position: str  # the position's name
    department: str
    hiring_manager: str  # «<family> <given>»; «» when the vacancy has no manager
    status: str  # open, closed or filled
    status_label: str
    headcount: int
    deadline: str | None  # YYYY-MM-DD; null when there is no deadline
    counts: RecruitCountsOut  # the candidates per stage (the five counted stages)


class RecruitVacancyListOut(Schema):
    status: str  # open, closed, filled or all (an unknown filter is open)
    q: str  # the search text as used: stripped and cut to 100 characters
    rows: list[RecruitVacancyRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    can_manage: bool
    empty_text: str


class RecruitVacancyOptionsOut(Schema):
    positions: list[RecruitChoiceOut]
    departments: list[RecruitChoiceOut]
    branches: list[RecruitChoiceOut]
    managers: list[RecruitChoiceOut]
    statuses: list[RecruitStringChoiceOut]  # empty for a new vacancy, which has no status field


class RecruitSlotLineOut(Schema):
    numbers: str  # «2026 он · орон тоо 3 · ажиллаж буй 2 · сул 1»; «» when there is no branch to check
    warning: str  # one short reason; «» when all is well


class RecruitStageItemOut(Schema):
    key: str  # open (the active stages), a stage value, or all
    label: str
    count: int


class RecruitCandidateRowOut(Schema):
    id: int
    name: str  # «<surname> <given_name>»
    stage: str
    stage_label: str
    phone: str
    source: str
    created: str  # YYYY-MM-DD


class RecruitVacancyOut(Schema):
    id: int
    title: str
    status: str
    status_label: str
    position: str
    department: str
    branch: str  # the branch's name; «» when none
    headcount: int
    deadline: str | None  # YYYY-MM-DD
    desired_start: str | None  # YYYY-MM-DD
    description: str
    can_manage: bool
    is_open: bool
    slot_line: RecruitSlotLineOut | None  # only for a manager on an open vacancy, and only with the slot switch on
    stage_key: str  # the stage filter as used: a stage value, open or all
    stage_bar: list[RecruitStageItemOut]
    candidates: list[RecruitCandidateRowOut]  # this batch only; the first call and later batches differ here alone
    next_offset: int | None  # the offset of the next batch of candidates; None when this is the last one


class RecruitVacancyFormOut(Schema):
    """The vacancy edit pop-up's first values: the ids the form posts back (names are on the vacancy page)."""

    title: str
    position: int
    department: int
    branch: int | None
    headcount: int
    hiring_manager: int | None
    deadline: str | None  # YYYY-MM-DD; null when blank
    desired_start: str | None  # YYYY-MM-DD; null when blank
    status: str  # open, closed or filled
    description: str


class RecruitProgressOut(Schema):
    key: str
    label: str
    state: str  # done, current or todo; none lit when the candidate is rejected or withdrawn


class RecruitEventOut(Schema):
    at: str  # YYYY-MM-DD HH:MM, local time
    from_label: str  # «» for the first row (the candidate was added)
    to_label: str
    note: str
    by: str  # the person's name, their username, or «—»


class RecruitCommentOut(Schema):
    id: int
    text: str
    by: str
    at: str  # YYYY-MM-DD HH:MM, local time


class RecruitFileOut(Schema):
    """A CV or other file. The stored path is never sent: the download is a plain link to the file's own address."""

    id: int
    name: str  # the original file name
    uploaded: str  # YYYY-MM-DD
    by: str


class RecruitCandidateOut(Schema):
    id: int
    name: str  # «<surname> <given_name>»
    vacancy_id: int
    vacancy_title: str
    stage: str
    stage_label: str
    source: str
    phone: str
    email: str
    notes: str
    reject_reason: str
    employee_id: int | None  # the linked employee; null unless the user may see that person
    progress: list[RecruitProgressOut]
    move_to: list[str]  # the stages a manager may move to now (their labels are in `progress`)
    move_confirm: list[str]  # the subset of move_to that asks first
    can_manage: bool
    can_reject: bool
    can_reopen: bool
    can_convert: bool
    events: list[RecruitEventOut]  # oldest first
    comments: list[RecruitCommentOut]  # oldest first
    files: list[RecruitFileOut]  # oldest first
    max_mb: int
    extensions: str  # the allowed file types, comma-separated


class RecruitPurgeRowOut(Schema):
    id: int
    name: str
    vacancy_title: str
    stage_label: str
    closed: str | None  # YYYY-MM-DD: the day the candidate was rejected or withdrew


class RecruitPurgeOut(Schema):
    rows: list[RecruitPurgeRowOut]  # the candidates the purge would remove today, oldest closed first
    months: int  # the retention period in months
    is_admin: bool  # the user may change the retention period (the admin link shows)


class RecruitVacancyIn(Schema):
    """The vacancy pop-up as posted: ids as numbers (null when blank), dates as YYYY-MM-DD text ("" when blank)."""

    title: str = ""
    position: int | None = None
    department: int | None = None
    branch: int | None = None
    headcount: int | None = None
    hiring_manager: int | None = None
    deadline: str = ""
    desired_start: str = ""
    description: str = ""


class RecruitVacancyUpdateIn(RecruitVacancyIn):
    status: str = ""  # open, closed or filled (the edit pop-up's status select)


class RecruitCandidateIn(Schema):
    surname: str = ""
    given_name: str = ""
    phone: str = ""
    email: str = ""
    source: str = ""
    notes: str = ""


class RecruitMoveIn(Schema):
    to: str = ""  # a stage value: new, screening, interview or offer
    note: str = ""


class RecruitRejectIn(Schema):
    reason: str = ""  # required unless the candidate withdrew
    withdrawn: bool = False


class RecruitCommentIn(Schema):
    text: str = ""


class RecruitConvertOut(Schema):
    ok: bool
    path: str  # the hire form's address, prefilled from the candidate; "" on a refusal
    error: str  # the refusal text; "" when ok


class RecruitPurgeResultOut(Schema):
    ok: bool
    deleted: int  # how many candidates were removed


# --- the module gate and the login -----------------------------------------------------------------------------------


def _module_on() -> None:
    """The module gate of every recruitment route: 404 while the recruitment module is off. Written once; the router's
    auth runs it, so no route can skip it."""
    if not modules.enabled(MODULE_KEY):
        raise ApiError(404, [NOT_FOUND])


def _recruitment_auth(request: HttpRequest) -> User | None:
    """The router's auth: a signed-in session first (401 without one), then the module gate (404 while it is off)."""
    user = django_auth(request)
    if user:
        _module_on()
    return user


recruitment_router = Router(tags=["recruitment"], auth=_recruitment_auth)


# --- helpers ---------------------------------------------------------------------------------------------------------


def _manage(request: HttpRequest) -> User:
    user = request_user(request)
    if not visibility.can_manage(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _id_param(raw: str | None) -> int | None:
    """An id sent as text: digits only, else None (the Django pages read their ids the same way)."""
    if raw and raw.isascii() and raw.isdigit() and len(raw) <= MAX_ID_LENGTH:
        return int(raw)
    return None


def _date_param(raw: str | None) -> date | None:
    """A date sent as YYYY-MM-DD, else None."""
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _vacancy_param(user: User, raw: str | None) -> Vacancy | None:
    """The vacancy named by an optional id: None when none is sent; 404 for junk or a vacancy the user may not see."""
    if not raw:
        return None
    pk = _id_param(raw)
    if pk is None:
        raise ApiError(404, [NOT_FOUND])
    with service_errors():
        return access.vacancy_or_404(user, pk)


def _who(user: User | None) -> str:
    """A person's name as the templates print it: the full name, else the username, else a dash."""
    if user is None:
        return "—"
    return user.get_full_name() or user.username or "—"


def _day(value: datetime) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%d")


def _moment(value: datetime) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _day_or_none(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _name(candidate: Candidate) -> str:
    return f"{candidate.surname} {candidate.given_name}"


def _slot_out(line: slot_line.SlotLine | None) -> RecruitSlotLineOut | None:
    if line is None:
        return None
    return RecruitSlotLineOut(numbers=line.numbers, warning=line.warning)


def _vacancy_row(vacancy: Vacancy) -> RecruitVacancyRowOut:
    manager = vacancy.hiring_manager
    return RecruitVacancyRowOut(
        id=vacancy.pk,
        title=vacancy.title,
        position=vacancy.position.name,
        department=vacancy.department.name,
        hiring_manager=manager.full_name if manager is not None else "",
        status=vacancy.status,
        status_label=vacancy.get_status_display(),
        headcount=vacancy.headcount,
        deadline=_day_or_none(vacancy.deadline),
        counts=RecruitCountsOut(
            new=vacancy.c_new,
            screening=vacancy.c_screening,
            interview=vacancy.c_interview,
            offer=vacancy.c_offer,
            hired=vacancy.c_hired,
        ),
    )


def _candidate_row(candidate: Candidate) -> RecruitCandidateRowOut:
    return RecruitCandidateRowOut(
        id=candidate.pk,
        name=_name(candidate),
        stage=candidate.stage,
        stage_label=candidate.get_stage_display(),
        phone=candidate.phone,
        source=candidate.source,
        created=_day(candidate.created_at),
    )


# --- the vacancy list ------------------------------------------------------------------------------------------------


@recruitment_router.get("/vacancies", response=RecruitVacancyListOut)
def vacancies_list(
    request: HttpRequest,
    response: HttpResponse,
    status: str | None = None,
    q: str | None = None,
    offset: str = "",
) -> RecruitVacancyListOut:
    """One batch of the vacancy list: the visible vacancies with the chosen status and the search words."""
    user = request_user(request)
    status_key = vacancy_page.parse_status(status)
    search = vacancy_page.clean_search(q)
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    batch, more = vacancy_page.vacancy_batch(user, status_key, search, start, size)
    response["Cache-Control"] = "no-store"
    return RecruitVacancyListOut(
        status=status_key,
        q=search,
        rows=[_vacancy_row(vacancy) for vacancy in batch],
        next_offset=start + size if more else None,
        can_manage=visibility.can_manage(user),
        empty_text=EMPTY_TEXT,
    )


# --- the vacancy form and the budget line (the manage right) ---------------------------------------------------------


@recruitment_router.get("/vacancies/options", response=RecruitVacancyOptionsOut)
def vacancy_options_read(
    request: HttpRequest, response: HttpResponse, vacancy: str | None = None
) -> RecruitVacancyOptionsOut:
    """The choices of the vacancy form. With `vacancy`, the edit form's choices: its manager and the statuses."""
    user = _manage(request)
    current = _vacancy_param(user, vacancy)
    options = vacancy_page.vacancy_options(user, current)
    response["Cache-Control"] = "no-store"
    return RecruitVacancyOptionsOut(
        positions=[RecruitChoiceOut(id=pk, label=label) for pk, label in options.positions],
        departments=[RecruitChoiceOut(id=pk, label=label) for pk, label in options.departments],
        branches=[RecruitChoiceOut(id=pk, label=label) for pk, label in options.branches],
        managers=[RecruitChoiceOut(id=pk, label=label) for pk, label in options.managers],
        statuses=[RecruitStringChoiceOut(value=value, label=label) for value, label in options.statuses],
    )


# The budget line is declared before /vacancies/{pk} so the word is never read as a vacancy id.
@recruitment_router.get("/vacancies/slot-line", response=RecruitSlotLineOut | None)
def vacancy_slot_line(
    request: HttpRequest,
    response: HttpResponse,
    position: str | None = None,
    branch: str | None = None,
    desired_start: str | None = None,
    headcount: str | None = None,
    vacancy: str | None = None,
) -> RecruitSlotLineOut | None:
    """The budget line for the position, branch and start picked in the vacancy form. Junk headcount is 1, junk ids
    and dates are none; the answer is null when the line is not shown (no position, the slot switch off)."""
    _manage(request)
    position_id = _id_param(position)
    branch_id = _id_param(branch)
    line = slot_line.describe(
        position=Position.objects.filter(pk=position_id).first() if position_id is not None else None,
        branch=Branch.objects.filter(pk=branch_id).first() if branch_id is not None else None,
        start=_date_param(desired_start),
        headcount=_id_param(headcount) or 1,
        exclude_vacancy=_id_param(vacancy),
    )
    response["Cache-Control"] = "no-store"
    return _slot_out(line)


# --- the vacancy page ------------------------------------------------------------------------------------------------


@recruitment_router.get("/vacancies/{pk}", response=RecruitVacancyOut)
def vacancy_read(
    request: HttpRequest, response: HttpResponse, pk: int, stage: str | None = None, offset: str = ""
) -> RecruitVacancyOut:
    """The vacancy page: the vacancy, its stage bar and one batch of its candidates. A later batch repeats the body."""
    user = request_user(request)
    with service_errors():
        vacancy = access.vacancy_or_404(user, pk)
    manage = visibility.can_manage(user)
    is_open = vacancy.status == VacancyStatus.OPEN
    stage_key = vacancy_page.parse_stage(stage)
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    rows, more = vacancy_page.candidate_batch(vacancy, stage_key, start, size)
    line = None
    if manage and is_open:
        line = slot_line.describe(
            position=vacancy.position,
            branch=vacancy.branch,
            start=vacancy.desired_start,
            headcount=vacancy.headcount,
            exclude_vacancy=vacancy.pk,
        )
    response["Cache-Control"] = "no-store"
    return RecruitVacancyOut(
        id=vacancy.pk,
        title=vacancy.title,
        status=vacancy.status,
        status_label=vacancy.get_status_display(),
        position=vacancy.position.name,
        department=vacancy.department.name,
        branch=vacancy.branch.name if vacancy.branch is not None else "",
        headcount=vacancy.headcount,
        deadline=_day_or_none(vacancy.deadline),
        desired_start=_day_or_none(vacancy.desired_start),
        description=vacancy.description,
        can_manage=manage,
        is_open=is_open,
        slot_line=_slot_out(line),
        stage_key=stage_key,
        stage_bar=[
            RecruitStageItemOut(key=item.key, label=item.label, count=item.count)
            for item in vacancy_page.stage_bar(vacancy)
        ],
        candidates=[_candidate_row(candidate) for candidate in rows],
        next_offset=start + size if more else None,
    )


@recruitment_router.get("/vacancies/{pk}/form", response=RecruitVacancyFormOut)
def vacancy_form_read(request: HttpRequest, response: HttpResponse, pk: int) -> RecruitVacancyFormOut:
    """The edit pop-up's values as the form posts them back: 404 for a vacancy the user may not see, then 403 without
    the manage right (as the edit route)."""
    user = request_user(request)
    with service_errors():
        vacancy = access.vacancy_or_404(user, pk)
    _manage(request)
    response["Cache-Control"] = "no-store"
    return RecruitVacancyFormOut(
        title=vacancy.title,
        position=vacancy.position_id,
        department=vacancy.department_id,
        branch=vacancy.branch_id,
        headcount=vacancy.headcount,
        hiring_manager=vacancy.hiring_manager_id,
        deadline=_day_or_none(vacancy.deadline),
        desired_start=_day_or_none(vacancy.desired_start),
        status=vacancy.status,
        description=vacancy.description,
    )


# --- the candidate page ----------------------------------------------------------------------------------------------


@recruitment_router.get("/candidates/{pk}", response=RecruitCandidateOut)
def candidate_read(request: HttpRequest, response: HttpResponse, pk: int) -> RecruitCandidateOut:
    """The candidate page: the person, the progress, the actions the user may take, the history, comments and files."""
    user = request_user(request)
    with service_errors():
        candidate = access.candidate_or_404(user, pk)
    page = candidate_page.candidate_page(user, candidate)
    response["Cache-Control"] = "no-store"
    return RecruitCandidateOut(
        id=candidate.pk,
        name=_name(candidate),
        vacancy_id=candidate.vacancy_id,
        vacancy_title=page.vacancy.title,
        stage=candidate.stage,
        stage_label=candidate.get_stage_display(),
        source=candidate.source,
        phone=candidate.phone,
        email=candidate.email,
        notes=candidate.notes,
        reject_reason=candidate.reject_reason,
        employee_id=candidate.employee_id if page.employee_visible else None,
        progress=[RecruitProgressOut(key=key, label=label, state=state) for key, label, state in page.progress],
        move_to=page.move_to,
        move_confirm=page.move_confirm,
        can_manage=page.can_manage,
        can_reject=page.can_reject,
        can_reopen=page.can_reopen,
        can_convert=page.can_convert,
        events=[
            RecruitEventOut(
                at=_moment(event.at),
                from_label=event.get_from_stage_display() if event.from_stage else "",
                to_label=event.get_to_stage_display(),
                note=event.note,
                by=_who(event.by),
            )
            for event in page.events
        ],
        comments=[
            RecruitCommentOut(id=comment.pk, text=comment.text, by=_who(comment.by), at=_moment(comment.at))
            for comment in page.comments
        ],
        files=[
            RecruitFileOut(id=row.pk, name=row.name, uploaded=_day(row.uploaded_at), by=_who(row.uploaded_by))
            for row in page.files
        ],
        max_mb=page.max_mb,
        extensions=page.extensions,
    )


# --- the purge (the manage right) ------------------------------------------------------------------------------------


@recruitment_router.get("/purge", response=RecruitPurgeOut)
def purge_read(request: HttpRequest, response: HttpResponse) -> RecruitPurgeOut:
    """The rejected or withdrawn candidates the purge would remove today, and the retention period."""
    user = _manage(request)
    page = candidate_page.purge_page(user, timezone.localdate())
    response["Cache-Control"] = "no-store"
    return RecruitPurgeOut(
        rows=[
            RecruitPurgeRowOut(
                id=row.pk,
                name=_name(row),
                vacancy_title=row.vacancy.title,
                stage_label=row.get_stage_display(),
                closed=_day(row.closed_at) if row.closed_at is not None else None,
            )
            for row in page.rows
        ],
        months=page.months,
        is_admin=page.is_admin,
    )


# --- the writes ------------------------------------------------------------------------------------------------------
# Every write answers 200 with RecruitWriteResultOut (or RecruitConvertOut, RecruitPurgeResultOut). The rights are
# checked after the object is found, as the Django views do: an unknown or hidden object is 404 first, then a missing
# manage right is 403. A refused write changes nothing; the audit lines are the services' own.


def _saved() -> dict[str, Any]:
    return {"ok": True, "error": "", "field_errors": {}, "form_errors": []}


def _refused_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "field_errors": {}, "form_errors": []}


def _refused_form(form: forms.BaseForm) -> dict[str, Any]:
    payload = form_error_payload(form)
    return {"ok": False, "error": "", "field_errors": payload["field_errors"], "form_errors": payload["form_errors"]}


def _text(value: object) -> str:
    """An id or a number as the browser posts it: its text, or empty for none."""
    return "" if value is None else str(value)


def _vacancy_data(payload: RecruitVacancyIn) -> dict[str, str]:
    """The vacancy form's posted values, by its field names."""
    return {
        "title": payload.title,
        "position": _text(payload.position),
        "department": _text(payload.department),
        "branch": _text(payload.branch),
        "headcount": _text(payload.headcount),
        "hiring_manager": _text(payload.hiring_manager),
        "deadline": payload.deadline,
        "desired_start": payload.desired_start,
        "description": payload.description,
    }


def _visible_vacancy(user: User, pk: int) -> Vacancy:
    with service_errors():
        return access.vacancy_or_404(user, pk)


def _visible_candidate(user: User, pk: int) -> Candidate:
    with service_errors():
        return access.candidate_or_404(user, pk)


@recruitment_router.post("/vacancies", response=RecruitVacancyCreatedOut)
def vacancy_create(request: HttpRequest, payload: RecruitVacancyIn) -> dict[str, Any]:
    """Add a vacancy (open, created by the user). 403 without the manage right; the new vacancy's id comes back."""
    user = _manage(request)
    vacancy, form = vacancy_page.create_vacancy(user, _vacancy_data(payload))
    if vacancy is None:
        return _refused_form(form)
    return {**_saved(), "id": vacancy.pk}


@recruitment_router.post("/vacancies/{pk}", response=RecruitWriteResultOut)
def vacancy_update(request: HttpRequest, pk: int, payload: RecruitVacancyUpdateIn) -> dict[str, Any]:
    """Change a vacancy. 404 for one the user may not see, then 403 without the manage right."""
    user = request_user(request)
    vacancy = _visible_vacancy(user, pk)
    _manage(request)
    updated, form = vacancy_page.update_vacancy(user, vacancy, {**_vacancy_data(payload), "status": payload.status})
    if updated is None:
        return _refused_form(form)
    return _saved()


@recruitment_router.post("/vacancies/{pk}/candidates", response=RecruitWriteResultOut)
def candidate_add(request: HttpRequest, pk: int, payload: RecruitCandidateIn) -> dict[str, Any]:
    """Add a candidate to an open vacancy. A closed or filled vacancy is refused with the Django text first."""
    user = request_user(request)
    vacancy = _visible_vacancy(user, pk)
    _manage(request)
    refusal = vacancy_page.candidate_add_refusal(vacancy)
    if refusal:
        return _refused_error(refusal)
    form = CandidateForm(payload.model_dump())
    if not form.is_valid():
        return _refused_form(form)
    pipeline.add_candidate(vacancy, by=user, **form.cleaned_data)
    return _saved()


@recruitment_router.post("/candidates/{pk}/move", response=RecruitWriteResultOut)
def candidate_move(request: HttpRequest, pk: int, payload: RecruitMoveIn) -> dict[str, Any]:
    """Move a candidate to the next or another open stage. The service's refusal text comes back in `error`."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    _manage(request)
    try:
        pipeline.move(candidate, payload.to, by=user, note=payload.note)
    except pipeline.PipelineError as error:
        return _refused_error(error.message)
    return _saved()


@recruitment_router.post("/candidates/{pk}/reject", response=RecruitWriteResultOut)
def candidate_reject(request: HttpRequest, pk: int, payload: RecruitRejectIn) -> dict[str, Any]:
    """Reject a candidate, or record that they withdrew. A missing reason is a field error under `reason`."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    _manage(request)
    form = RejectForm({"reason": payload.reason, "withdrawn": payload.withdrawn})
    if not form.is_valid():
        return _refused_form(form)
    try:
        pipeline.reject(
            candidate, by=user, reason=form.cleaned_data["reason"], withdrawn=form.cleaned_data["withdrawn"]
        )
    except pipeline.PipelineError as error:
        return _refused_error(error.message)
    return _saved()


@recruitment_router.post("/candidates/{pk}/reopen", response=RecruitWriteResultOut)
def candidate_reopen(request: HttpRequest, pk: int) -> dict[str, Any]:
    """Reopen a rejected or withdrawn candidate as new."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    _manage(request)
    try:
        pipeline.reopen(candidate, by=user)
    except pipeline.PipelineError as error:
        return _refused_error(error.message)
    return _saved()


@recruitment_router.post("/candidates/{pk}/comment", response=RecruitWriteResultOut)
def candidate_comment(request: HttpRequest, pk: int, payload: RecruitCommentIn) -> dict[str, Any]:
    """Add a comment. Any user who sees the candidate may comment, so no manage right is asked."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    try:
        pipeline.comment(candidate, by=user, text=payload.text)
    except pipeline.PipelineError as error:
        return _refused_error(error.message)
    return _saved()


@recruitment_router.post("/candidates/{pk}/files", response=RecruitWriteResultOut)
def candidate_file_upload(request: HttpRequest, pk: int, file: File[UploadedFile | None] = None) -> dict[str, Any]:
    """Attach a CV (multipart field `file`). The file's type, size and emptiness are checked by files.save."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    _manage(request)
    if file is None:
        return _refused_error(NO_FILE)
    try:
        files.save(candidate, file, by=user)
    except files.FileRejected as error:
        return _refused_error(error.message)
    return _saved()


@recruitment_router.get("/files/{pk}")
def candidate_file_download(request: HttpRequest, pk: int) -> HttpResponse:
    """The CV itself, under its original name; any user who sees the candidate may download it. A stored file that is
    missing is 404. The response is the file, not JSON, so it has no response schema."""
    user = request_user(request)
    with service_errors():
        row = access.file_or_404(user, pk)
    try:
        download = files.open(row, by=user)
    except FileNotFoundError:
        raise HttpError(404, NOT_FOUND) from None
    download["Cache-Control"] = "no-store"
    return download


@recruitment_router.post("/candidates/{pk}/convert", response=RecruitConvertOut)
def candidate_convert(request: HttpRequest, pk: int) -> dict[str, Any]:
    """The hire form's address for this candidate (prefilled), or the refusal text. Writes nothing; the link is made
    only when the hire is saved."""
    user = request_user(request)
    candidate = _visible_candidate(user, pk)
    _manage(request)
    path, error = candidate_page.convert_answer(user, candidate, timezone.localdate())
    return {"ok": not error, "path": path, "error": error}


@recruitment_router.post("/purge", response=RecruitPurgeResultOut)
def purge_run(request: HttpRequest) -> dict[str, Any]:
    """Delete the rejected or withdrawn candidates past the retention period and their files (403 without the right)."""
    user = _manage(request)
    deleted = pipeline.purge(by=user, today=timezone.localdate())
    return {"ok": True, "deleted": deleted}

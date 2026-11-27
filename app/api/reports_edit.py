"""The editors of a report cell, as the React grid draws them (decision D-080, step 5f).

- GET /api/v1/reports/cell/editor?person&field: the editor of one employee field (reports.services.cell_editors).
- POST /api/v1/reports/cell: saves it. Answers {ok, text, error, editor}; a clash or another refusal answers ok false
  with the editor to show (the current value after a clash, the typed text otherwise).
- GET /api/v1/reports/row-cell/editor?person&kind&key&field and POST /api/v1/reports/row-cell: the same for one cell
  of a children or contacts row. The save posts back the hidden values the editor returned, unchanged.
- GET /api/v1/reports/correct/editor?person&key&record and POST /api/v1/reports/correct: the correction editor of a
  job field (department, position, manager; `record` is the job record) or of the base salary (no record).
- POST /api/v1/reports/cells: the bulk edit (reports.bulk_edit). Body {apply, cells:[{person, field, text, old}]}; a
  dry run when apply is false. Answers {cells:[{person, field, ok, text, error}], saved}. The body is read raw and
  checked by bulk_edit.parse_body, so a body of the wrong shape is 400 {"error": ...} as the Django view answers.

The rules are the services' and the cell_edit, row_edit and corrections modules'; these routes only read the body or
the query and answer the editor. A login is needed (401 "not_authenticated"). An unknown field, kind or key, an unseen
employee or row, and a missing record are 404; a right that is not held is 403 "forbidden". Every answer is marked
Cache-Control: no-store, since the editor carries the stale token and the values of a person.

This router is registered in api/main.py before the report router, so the paths `cell`, `row-cell`, `correct` are not
read as report keys by `/reports/{key}`.
"""

import json
import re
from collections.abc import Callable
from functools import wraps
from typing import Any, Literal

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth
from reports import bulk_edit
from reports.services import cell_editors as editors
from reports.services.cell_editors import EditorModel, EditResult

from api.errors import ApiError
from api.popups import NOT_FOUND, request_user, service_errors

edit_router = Router(tags=["reports"], auth=django_auth)


class ReportEditorChoiceOut(Schema):
    value: str
    label: str


class ReportEditorOut(Schema):
    kind: Literal["text", "choice", "date", "number"]  # the input the editor draws
    name: str  # the form field's name (the value the save posts back as the field)
    value: str  # the value as shown: a date as ISO, a choice as its option value
    label: str  # a choice's label for the value ("" for the empty option, and for the other kinds)
    choices: list[ReportEditorChoiceOut]  # a choice's options, the empty option included; [] for the other kinds
    required: bool
    maxlength: int | None  # text only
    loaded: str  # the stale token of a cell; "" for a row, whose tokens are in `hidden`
    hidden: dict[str, str]  # a row editor: the other fields of the row form at their current values
    reason: bool  # the correction editor asks for a reason
    old: str  # the correction editor: the value it replaces
    note: str  # the correction editor: the note under the input
    reason_text: str  # the correction editor: the reason typed, kept after a failed save
    blocked: str  # the correction editor: why no input is shown ("" when it can be corrected)
    error: str  # the message of a failed save


class ReportEditResultOut(Schema):
    ok: bool
    text: str  # the value as the cell shows it now, after a save ("" on a refusal)
    error: str  # the message of a refusal ("" on success)
    editor: ReportEditorOut | None  # the editor to show after a refusal; None on success


class ReportEditCellIn(Schema):
    person: int
    field: str
    value: str = ""
    loaded: str = ""  # the stale token the editor opened with


class ReportEditRowIn(Schema):
    person: int
    kind: str
    key: int
    field: str
    values: dict[str, str] = {}  # the visible field plus the hidden fields the row editor returned


class ReportEditCorrectIn(Schema):
    person: int
    key: str
    record: int | None = None  # the job record; None for the base salary
    value: str = ""
    old: str = ""  # the text the editor showed
    reason: str = ""


class ReportEditBulkCellOut(Schema):
    person: int
    field: str
    ok: bool
    text: str  # the value as the cell shows it now ("" on a refusal)
    error: str  # the reason of a refused cell ("" on success)


class ReportEditBulkOut(Schema):
    cells: list[ReportEditBulkCellOut]  # one outcome per posted cell, in the posted order
    saved: int  # the cells written (0 for a dry run)


def _editor(model: EditorModel) -> ReportEditorOut:
    return ReportEditorOut(
        kind=model.kind,
        name=model.name,
        value=model.value,
        label=model.label,
        choices=[ReportEditorChoiceOut(value=c.value, label=c.label) for c in model.choices],
        required=model.required,
        maxlength=model.maxlength,
        loaded=model.loaded,
        hidden=model.hidden,
        reason=model.reason,
        old=model.old,
        note=model.note,
        reason_text=model.reason_text,
        blocked=model.blocked,
        error=model.error,
    )


def _result(result: EditResult) -> ReportEditResultOut:
    return ReportEditResultOut(
        ok=result.ok,
        text=result.text,
        error=result.error,
        editor=_editor(result.editor) if result.editor is not None else None,
    )


def _record_id(record: str) -> int | None:
    """The record query parameter: "" for none (the base salary), a number otherwise; anything else is 404."""
    if record == "":
        return None
    if not re.fullmatch(r"[0-9]+", record):  # ASCII digits only: int() would raise on "²" and accept other scripts
        raise HttpError(404, NOT_FOUND)
    return int(record)


def _no_store_errors(view: Callable[..., Any]) -> Callable[..., Any]:
    """Marks the answer of a refusal (ApiError, HttpError: the 403, 404 and 400 of these routes) Cache-Control:
    no-store, like the success answer. The body and the status are the API's own: the exception goes through the
    API's handler (api.main), which is imported here, not at module load, because api.main imports this module."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        try:
            return view(request, *args, **kwargs)
        except (ApiError, HttpError) as exc:
            from api.main import api

            refusal = api.on_exception(request, exc)
            refusal["Cache-Control"] = "no-store"
            return refusal

    return wrapper


# --- a cell -----------------------------------------------------------------------------------------


@edit_router.get("/cell/editor", response=ReportEditorOut)
@_no_store_errors
def cell_editor(request: HttpRequest, response: HttpResponse, person: int, field: str) -> ReportEditorOut:
    """The editor of one employee field in a report cell, with the stored value and the stale token."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    with service_errors():
        model = editors.open_cell(user, person, field)
    return _editor(model)


@edit_router.post("/cell", response=ReportEditResultOut)
@_no_store_errors
def cell_save(request: HttpRequest, response: HttpResponse, payload: ReportEditCellIn) -> ReportEditResultOut:
    """Saves one employee field through the cell_edit rules. A refusal answers ok false with the editor to show."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    with service_errors():
        result = editors.save_cell(user, payload.person, payload.field, payload.value, payload.loaded)
    return _result(result)


# --- a children or contacts row -----------------------------------------------------------------------


@edit_router.get("/row-cell/editor", response=ReportEditorOut)
@_no_store_errors
def row_editor(
    request: HttpRequest, response: HttpResponse, person: int, kind: str, key: int, field: str
) -> ReportEditorOut:
    """The editor of one cell of a children or contacts row, with the other fields of the row as hidden values."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    with service_errors():
        model = editors.open_row(user, person, kind, key, field)
    return _editor(model)


@edit_router.post("/row-cell", response=ReportEditResultOut)
@_no_store_errors
def row_save(request: HttpRequest, response: HttpResponse, payload: ReportEditRowIn) -> ReportEditResultOut:
    """Saves one field of one row through the row_edit rules. A row changed meanwhile answers ok false with a fresh
    editor showing the current values."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    with service_errors():
        result = editors.save_row(user, payload.person, payload.kind, payload.key, payload.field, payload.values)
    return _result(result)


# --- a correction of a job field or of the base salary ------------------------------------------------


@edit_router.get("/correct/editor", response=ReportEditorOut)
@_no_store_errors
def correct_editor(
    request: HttpRequest, response: HttpResponse, person: int, key: str, record: str = ""
) -> ReportEditorOut:
    """The correction editor of one job field (with the job record) or of the base salary (no record). A cell that may
    not be corrected now answers only its message in `blocked`."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    record_id = _record_id(record)
    with service_errors():
        model = editors.open_correct(user, person, key, record_id)
    return _editor(model)


# --- the bulk edit of many cells ----------------------------------------------------------------------


@edit_router.post("/cells", response=ReportEditBulkOut)
@_no_store_errors
def cells_bulk(request: HttpRequest, response: HttpResponse) -> ReportEditBulkOut | HttpResponse:
    """Checks every cell (a dry run when apply is false) and saves the ok ones when true. The body is read here, not by
    Ninja, so a body of the wrong shape or over 500 cells is the Django view's 400 {"error": ...}. A refused field or
    right is a refused cell, answered with 200."""
    user = request_user(request)
    try:
        body = json.loads(request.body)
    except ValueError:  # not JSON (or not UTF-8): the same text as a body of the wrong shape
        body = None
    try:
        apply, cells = bulk_edit.parse_body(body)
    except ValueError as exc:
        refused = JsonResponse({"error": str(exc)}, status=400)
        refused["Cache-Control"] = "no-store"
        return refused
    response["Cache-Control"] = "no-store"
    outcomes = bulk_edit.run(user, cells, apply=apply)
    return ReportEditBulkOut(
        cells=[
            ReportEditBulkCellOut(person=o.person, field=o.field, ok=o.ok, text=o.text, error=o.error) for o in outcomes
        ],
        saved=sum(1 for o in outcomes if o.ok) if apply else 0,
    )


@edit_router.post("/correct", response=ReportEditResultOut)
@_no_store_errors
def correct_save(request: HttpRequest, response: HttpResponse, payload: ReportEditCorrectIn) -> ReportEditResultOut:
    """Saves one correction through the corrections rules (the activity log, the stale check). A blocked cell writes
    nothing and answers its message."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    with service_errors():
        result = editors.save_correct(
            user, payload.person, payload.key, payload.record, payload.value, payload.old, payload.reason
        )
    return _result(result)

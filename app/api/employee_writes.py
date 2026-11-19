"""The employee page's form state and save, as the React page calls them:

- GET /api/v1/employees/{pk}/page-form: the fields of the header, work and bank forms (the salary fields carry the
  `si-` prefix), their stored values, and the `loaded` snapshots the stale check needs.
- POST /api/v1/employees/{pk}/save (multipart): the values the page holds, a photo and the chosen tab.
- POST /api/v1/employees/{pk}/personal/sections/{section} (JSON): one personal-tab section's values, its clash
  choices and its `loaded` snapshot.
- GET /api/v1/employees/{pk}/personal/{kind}/form: one personal-list row's pop-up (add, or edit with `key`): its
  fields, its hidden `loaded_*` values and the address's city/district/street presets.
- POST /api/v1/employees/{pk}/personal/{kind} (add), POST .../{kind}/{key} (edit) and POST .../{kind}/{key}/delete
  (JSON `values` with the form's fields and hidden `loaded_*` values).

The rules are employees.services.page_writes (save_page, page_form_state, row_form, add_row, edit_row, delete_row)
and the stale check is employees.stale.
This module reads the JSON the page sends, builds the POST the Django page would have sent (so save_page runs
unchanged) and presents the result. A clash or an invalid field is a business outcome: it answers 200 with the
result. A missing right is 403 (code "forbidden"), a row outside the user's scope is 404, no login is 401.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from accounts.models import User
from django.forms import BaseForm
from django.forms import Form as DjangoForm
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.utils.datastructures import MultiValueDict
from employees import access, sections, stale
from employees.forms import CreateLoginForm
from employees.models import Employee
from employees.services import page_writes
from employees.services import personal_writes as pw
from employees.services.detail_page import needs_setup
from employees.services.form_schema import describe_form, empty_lists, hidden_values
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.popups import FORBIDDEN as _FORBIDDEN
from api.popups import NOT_FOUND as _NOT_FOUND
from api.popups import EmployeeFormChoiceOut as EmployeeFormChoiceOut  # re-exported for api.hire
from api.popups import EmployeeFormFieldOut, money_kinds, service_errors

employee_write_router = Router(tags=["employees"])

_BAD_VALUES = "Хадгалах мэдээлэл буруу байна."
_PHOTO_FIELDS = ("photo", "photo_clear")  # the photo has its own part in the save, not a box in the form
_STALE_FORM = "Хуудсыг дахин ачаалж, дахин оролдоно уу."  # a save without the snapshot the page showed


class EmployeeFormPageOut(Schema):
    loaded: str  # the header/work/bank form's snapshot (JSON), posted back as `loaded`; "" without that form
    si_loaded: str  # the salary form's snapshot (JSON), posted back as `si-loaded`; "" without that form
    fields: list[EmployeeFormFieldOut]


class EmployeeWriteResultOut(Schema):
    ok: bool
    field_errors: dict[str, list[str]]  # by HTML name (salary fields carry «si-»)
    form_errors: list[str]
    conflicts: dict[str, str]  # HTML name -> the value MACS stored meanwhile, as the user reads it
    loaded: str  # a fresh snapshot of the header/work/bank form on the stored employee
    si_loaded: str  # a fresh snapshot of the salary form on the stored employee, "" without the salary right
    tab: str  # on success the posted tab; on failure the tab that shows the first error


class EmployeeWriteSectionIn(Schema):
    values: dict[str, str]  # the section's fields by HTML name, as the page would post them
    resolve: dict[str, str] = {}  # a clash's choice by field name: "mine" or "theirs"
    loaded: str  # the personal tab's `loaded` snapshot the page showed (stale check); required, missing is 400


class EmployeeFormEmptyListOut(Schema):
    slug: str
    label: str


class EmployeeFormOut(Schema):
    title: str  # the pop-up's title, «<list>: нэмэх» for an add, «<list>: засах» for an edit
    fields: list[EmployeeFormFieldOut]
    hidden: dict[str, str]  # the hidden loaded_* values (the stale check); post them back with the row
    empty_lists: list[EmployeeFormEmptyListOut]  # code lists the form needs that have no entries yet
    can_delete: bool  # true on an edit


class EmployeeWriteRowIn(Schema):
    values: dict[str, str]  # the row form's fields and hidden loaded_* values, by HTML name


class EmployeeWriteNoteIn(Schema):
    text: str  # a blank text (after the strip) writes nothing and still answers 204


class EmployeeWriteLoginIn(Schema):
    username: str


class EmployeeWriteLoginOut(Schema):
    username: str
    password: str  # the temporary password, shown once; the response is no-store


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _scoped_employee(user: User, pk: int) -> Employee:
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    return employee


def _require_a_right(user: User) -> None:
    if not (access.can_manage(user) or access.can_manage_salary(user)):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")


def _require_personal(request: HttpRequest, pk: int) -> Employee:
    """A personal-row route's scope: the employee the user may see (404), then the manage and personal rights (403)."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    if not (access.can_manage(user) and access.can_view_personal(user, employee)):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    return employee


def _correction_form_out(form: BaseForm, which: str) -> dict[str, Any]:
    """The pop-up of a correction. The amount is a MoneyField: its box takes the money kind, not a plain text box."""
    # A ModelForm (the job correction) is a BaseForm, not a Form; the describe helpers only read the form's fields.
    shown = cast(DjangoForm, form)
    fields = describe_form(shown)
    money_kinds(form, fields)
    return {
        "title": page_writes.CORRECTION_TITLES[which],
        "fields": fields,
        "hidden": hidden_values(shown),
        "empty_lists": empty_lists(shown),
        "can_delete": False,
    }


def _correction_get(request: HttpRequest, pk: int, which: str, record_id: int | None) -> dict[str, Any]:
    user = _user(request)
    employee = _scoped_employee(user, pk)
    with service_errors():
        form = page_writes.correction_form(user, employee, which, record_id)
    return _correction_form_out(form, which)


def _correction_post(
    request: HttpRequest, pk: int, which: str, record_id: int | None, payload: EmployeeWriteRowIn
) -> dict[str, Any]:
    user = _user(request)
    employee = _scoped_employee(user, pk)
    with service_errors():
        result = page_writes.submit_correction(user, employee, which, record_id, payload.values)
    return _row_out(result)


@contextmanager
def _row_errors() -> Iterator[None]:
    """An unknown personal list or row is a 404 in the API's own shape (the rules raise Http404); a row save without
    the loaded values its form showed is a 400 (nothing written)."""
    try:
        yield
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except page_writes.RowSnapshotMissing:
        raise ApiError(400, [_STALE_FORM]) from None


def _row_out(result: page_writes.RowResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "field_errors": result.field_errors,
        "form_errors": result.form_errors,
        "conflicts": {},
        "loaded": "",
        "si_loaded": "",
        "tab": "",
    }


def _require_snapshots(user: User, post: QueryDict) -> None:
    """A save must carry the snapshot of each form the user may change (the stale check needs it): `loaded` for the
    header/work/bank form, `si-loaded` for the salary form. The page always sends them; without them, 400."""
    if access.can_manage(user) and not post.get(stale.LOADED):
        raise ApiError(400, [_STALE_FORM])
    if access.can_manage_salary(user) and not post.get(f"si-{stale.LOADED}"):
        raise ApiError(400, [_STALE_FORM])


def _post_from(values_json: str, tab: str, photo_clear: bool, photo: UploadedFile | None) -> QueryDict:
    """The POST the Django page would send: every value by its HTML name, the tab, the photo's checkbox and the
    photo's name (so a photo the browser refuses lands in field_errors, as its box would)."""
    try:
        values = json.loads(values_json)
    except ValueError:
        raise ApiError(400, [_BAD_VALUES]) from None
    if not isinstance(values, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in values.items()
    ):
        raise ApiError(400, [_BAD_VALUES])
    post: QueryDict = QueryDict(mutable=True)
    for name, value in values.items():
        post[name] = value
    post["tab"] = tab
    if photo_clear:
        post["photo_clear"] = "on"
    if photo is not None:
        post["photo"] = photo.name or "photo"
    return post


@employee_write_router.get("/{pk}/page-form", auth=django_auth, response=EmployeeFormPageOut)
def employee_page_form(request: HttpRequest, pk: int) -> dict[str, Any]:
    """The header, work and bank fields and the salary fields of one employee the user may see, with their stored
    values (404 outside the user's scope; 403 without the manage or the salary right)."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    _require_a_right(user)
    form, si_form = page_writes.page_form_state(user, employee)
    fields: list[dict[str, object]] = []
    if form is not None:
        names = [name for name in form.fields if name not in _PHOTO_FIELDS]
        fields.extend(describe_form(form, names=names))
    if si_form is not None:
        fields.extend(describe_form(si_form))  # the salary form's HTML names carry its «si-» prefix
    return {
        "loaded": stale.snapshot(form) if form is not None else "",
        "si_loaded": stale.snapshot(si_form) if si_form is not None else "",
        "fields": fields,
    }


@employee_write_router.post("/{pk}/save", auth=django_auth, response=EmployeeWriteResultOut)
def employee_save(
    request: HttpRequest,
    pk: int,
    values_json: Form[str],
    photo: File[UploadedFile | None] = None,
    photo_clear: Form[bool] = False,
    tab: Form[str] = "",
) -> dict[str, Any]:
    """Save what the user may change on the employee page. `values_json` is a JSON object of HTML name -> string
    (the fields, `loaded`, `si-loaded` and any `resolve-<name>`). Business outcomes answer 200 with the result."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    _require_a_right(user)
    post = _post_from(values_json, tab, photo_clear, photo)
    _require_snapshots(user, post)
    files = MultiValueDict({"photo": [photo]}) if photo is not None else MultiValueDict()
    # The React page posts only the fields it changed: the salary fields it did not post are completed from si-loaded.
    result = page_writes.save_page(user, employee, post, files, complete_salary=True)
    stored = Employee.objects.get(pk=employee.pk)
    si_loaded = stale.snapshot(page_writes.salary_form(stored)) if access.can_manage_salary(user) else ""
    return {
        "ok": result.ok,
        "field_errors": result.field_errors,
        "form_errors": result.form_errors,
        "conflicts": result.conflicts,
        "loaded": result.loaded,
        "si_loaded": si_loaded,
        "tab": result.tab,
    }


@employee_write_router.post("/{pk}/personal/sections/{section}", auth=django_auth, response=EmployeeWriteResultOut)
def employee_personal_section_save(
    request: HttpRequest, pk: int, section: str, payload: EmployeeWriteSectionIn
) -> dict[str, Any]:
    """Save one section of the personal tab (the same save as the Django section form). Business outcomes answer
    200 with the result; an unknown section is 404, a user without the manage and personal rights is 403."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    if section not in sections.SECTIONS:
        raise HttpError(404, _NOT_FOUND)
    if not (access.can_manage(user) and access.can_view_personal(user, employee)):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    if not payload.loaded:
        raise ApiError(400, [_STALE_FORM])
    post: QueryDict = QueryDict(mutable=True)
    for name, value in payload.values.items():
        post[name] = value
    for name, choice in payload.resolve.items():
        post[f"{stale.RESOLVE}{name}"] = choice
    post[stale.LOADED] = payload.loaded
    result = page_writes.save_section(user, employee, section, post)
    return {
        "ok": result.ok,
        "field_errors": result.field_errors,
        "form_errors": result.form_errors,
        "conflicts": result.conflicts,
        "loaded": result.loaded,
        "si_loaded": "",  # a section save does not touch the salary form
        "tab": result.tab,
    }


# The GET form route is registered before the POST {kind}/{key} routes: Django matches the first path that fits, so
# .../personal/address/form must not fall through to the edit route with key "form". The section route above stays
# first for POST .../personal/sections/{section}.
@employee_write_router.get("/{pk}/personal/{kind}/form", auth=django_auth, response=EmployeeFormOut)
def employee_personal_row_form(
    request: HttpRequest,
    pk: int,
    kind: str,
    key: int | None = None,
    city: str | None = None,
    district: str | None = None,
    street: str | None = None,
) -> dict[str, Any]:
    """The pop-up of one personal-list row: an add form (no key) or the edit form of the row `key`. An address takes
    city, district and street as presets so the district choices follow the city (the Django pop-up's rule)."""
    employee = _require_personal(request, pk)
    overrides = {
        name: value for name, value in (("city", city), ("district", district), ("street", street)) if value is not None
    }
    with _row_errors():
        form = page_writes.row_form(kind, employee, key, overrides)
    title = f"{pw.TITLES[kind]}: {'засах' if key is not None else 'нэмэх'}"
    return {
        "title": title,
        "fields": describe_form(form),
        "hidden": hidden_values(form),
        "empty_lists": empty_lists(form),
        "can_delete": key is not None,
    }


@employee_write_router.post("/{pk}/personal/{kind}", auth=django_auth, response=EmployeeWriteResultOut)
def employee_personal_row_add(request: HttpRequest, pk: int, kind: str, payload: EmployeeWriteRowIn) -> dict[str, Any]:
    """Add one row of a personal list. A refused form answers 200 with ok false; an unknown list is 404."""
    user = _user(request)
    employee = _require_personal(request, pk)
    with _row_errors():
        result = page_writes.add_row(user, employee, kind, payload.values)
    return _row_out(result)


@employee_write_router.post("/{pk}/personal/{kind}/{key}", auth=django_auth, response=EmployeeWriteResultOut)
def employee_personal_row_edit(
    request: HttpRequest, pk: int, kind: str, key: int, payload: EmployeeWriteRowIn
) -> dict[str, Any]:
    """Change one row of a personal list if it still matches the loaded values posted back (a changed row answers
    200 with ok false and the message in form_errors). Missing loaded values: 400, nothing written; unknown row: 404."""
    user = _user(request)
    employee = _require_personal(request, pk)
    with _row_errors():
        result = page_writes.edit_row(user, employee, kind, key, payload.values)
    return _row_out(result)


@employee_write_router.post("/{pk}/personal/{kind}/{key}/delete", auth=django_auth, response=EmployeeWriteResultOut)
def employee_personal_row_delete(
    request: HttpRequest, pk: int, kind: str, key: int, payload: EmployeeWriteRowIn
) -> dict[str, Any]:
    """Delete one row of a personal list, on the loaded values posted back (same rules as the edit)."""
    user = _user(request)
    employee = _require_personal(request, pk)
    with _row_errors():
        result = page_writes.delete_row(user, employee, kind, key, payload.values)
    return _row_out(result)


# The salary and job corrections: the specific paths (set, correct) never shadow one another; each GET .../form is the
# pop-up of the POST on the same path without .../form.
@employee_write_router.get("/{pk}/salary/set/form", auth=django_auth, response=EmployeeFormOut)
def employee_salary_set_form(request: HttpRequest, pk: int) -> dict[str, Any]:
    """The pop-up to set the first salary (404 outside the user's scope; 403 without the salary right or once a salary
    exists)."""
    return _correction_get(request, pk, "set-salary", None)


@employee_write_router.post("/{pk}/salary/set", auth=django_auth, response=EmployeeWriteResultOut)
def employee_salary_set(request: HttpRequest, pk: int, payload: EmployeeWriteRowIn) -> dict[str, Any]:
    """Set the first salary and write its activity entry. A refused form answers 200 with ok false."""
    return _correction_post(request, pk, "set-salary", None, payload)


@employee_write_router.get("/{pk}/salary/{record_id}/correct/form", auth=django_auth, response=EmployeeFormOut)
def employee_salary_correct_form(request: HttpRequest, pk: int, record_id: int) -> dict[str, Any]:
    """The pop-up to correct one salary row (403 for a scheduled row; 404 for another employee's row)."""
    return _correction_get(request, pk, "correct-salary", record_id)


@employee_write_router.post("/{pk}/salary/{record_id}/correct", auth=django_auth, response=EmployeeWriteResultOut)
def employee_salary_correct(
    request: HttpRequest, pk: int, record_id: int, payload: EmployeeWriteRowIn
) -> dict[str, Any]:
    """Correct one salary row; the reason is required. A refused correction answers 200 with ok false."""
    return _correction_post(request, pk, "correct-salary", record_id, payload)


@employee_write_router.get("/{pk}/job/{record_id}/correct/form", auth=django_auth, response=EmployeeFormOut)
def employee_job_correct_form(request: HttpRequest, pk: int, record_id: int) -> dict[str, Any]:
    """The pop-up to correct one job row (403 without the manage right or for a scheduled row)."""
    return _correction_get(request, pk, "correct-job", record_id)


@employee_write_router.post("/{pk}/job/{record_id}/correct", auth=django_auth, response=EmployeeWriteResultOut)
def employee_job_correct(request: HttpRequest, pk: int, record_id: int, payload: EmployeeWriteRowIn) -> dict[str, Any]:
    """Correct one job row; the reason is required. A refused correction answers 200 with ok false."""
    return _correction_post(request, pk, "correct-job", record_id, payload)


@employee_write_router.post("/{pk}/note", auth=django_auth, response={204: None})
def employee_note_add(request: HttpRequest, pk: int, payload: EmployeeWriteNoteIn) -> tuple[int, None]:
    """Add a note to the employee's activity log (a manager's right; 404 outside the user's scope, 403 without it)."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    if not access.can_manage(user):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    page_writes.add_note(user, employee, payload.text)
    return 204, None


@employee_write_router.post("/{pk}/setup/{key}", auth=django_auth, response={204: None})
def employee_setup_toggle(request: HttpRequest, pk: int, key: str) -> tuple[int, None]:
    """Tick or untick one setup item (Бүрдүүлэлт) while the employee's checklist is open. 403 without the manage right
    or once the checklist is closed; a system item answers 400."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    if not (access.can_manage(user) and needs_setup(employee)):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    try:
        page_writes.toggle_setup(user, employee, key)
    except ValueError:
        raise ApiError(400, [_BAD_VALUES]) from None
    return 204, None


@employee_write_router.post("/{pk}/login", auth=django_auth, response=EmployeeWriteLoginOut)
def employee_login_create(
    request: HttpRequest, response: HttpResponse, pk: int, payload: EmployeeWriteLoginIn
) -> dict[str, Any]:
    """Create the employee's login and answer its temporary password once (no-store). An invalid username is a 400
    with field_errors["username"]; a refused creation (a second login, a taken name) is a 400 with form_errors."""
    user = _user(request)
    employee = _scoped_employee(user, pk)
    if not access.can_manage(user):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    form = CreateLoginForm({"username": payload.username})
    if not form.is_valid():
        raise ApiError(400, **form_error_payload(form))
    try:
        login_name, password = page_writes.create_login(user, employee, form.cleaned_data["username"])
    except ValueError as error:
        raise ApiError(400, [str(error)]) from None
    response["Cache-Control"] = "no-store"  # the password lives only in this response
    return {"username": login_name, "password": password}

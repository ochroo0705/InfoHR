"""The Lists screen API under /api/v1/lists: the index with its search, the «Утгын холбоо» page, one list and the entry
pop-up's form, as the React page reads them. Rules are in lists.service and lists.forms; this module reads the request
and presents the answer.

GET /lists?q= (the lists to show, their counts and hits), GET /lists/meaning (the meanings and their options), GET
/lists/{slug} (one list's columns and rows) and GET /lists/{slug}/form?pk= (the add pop-up, or the edit pop-up with pk).

Writes: POST /lists/meaning (save the meanings), POST /lists/{slug} (add), POST /lists/{slug}/quick (quick-add from a
form dropdown), POST /lists/{slug}/{pk} (edit) and POST /lists/{slug}/{pk}/delete. A refused write (an invalid form, an
entry in use) answers 200 with ok false and writes nothing. The writes go through lists.service, so they are the same
as the Django pop-up's.

Only holders of lists.manage_lists may use it (403 "forbidden" for others, 401 for no login). An unknown list is 404.
"""

from typing import Any

from django.http import HttpRequest
from lists import service
from lists.forms import entry_form
from lists.registry import LISTS, MEANINGS, QUICK, ListSpec
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.popups import FORBIDDEN, request_user, service_errors

list_router = Router(tags=["lists"])
_NOT_FOUND = "Хуудас олдсонгүй"  # the same message as the other API routes


class ListIndexItemOut(Schema):
    slug: str
    label: str
    count: int  # every entry of the list
    hits: int  # entries matching the search; 0 when the search matched the list's own name or there is no search


class ListIndexOut(Schema):
    items: list[ListIndexItemOut]
    show_meanings: bool  # the «Утгын холбоо» card shows
    meanings_count: int
    q: str  # the search text, trimmed


class ListMeaningOptionOut(Schema):
    value: int
    label: str  # the entry's name, or its pk as text when the name is empty


class ListMeaningRowOut(Schema):
    key: str
    label: str
    hint: str
    current: int | None  # the chosen entry's pk, None when nothing is chosen
    options: list[ListMeaningOptionOut]


class ListMeaningOut(Schema):
    rows: list[ListMeaningRowOut]


class ListColumnOut(Schema):
    name: str
    label: str


class ListRowOut(Schema):
    id: int
    cells: list[str]  # a choice field shows its label; an empty value is ""


class ListPageOut(Schema):
    slug: str
    label: str
    columns: list[ListColumnOut]
    rows: list[ListRowOut]


class ListChoiceOut(Schema):
    value: str
    label: str


class ListFieldOut(Schema):
    name: str
    label: str
    kind: str  # text | select | number
    required: bool
    max_length: int | None
    value: str
    choices: list[ListChoiceOut]  # [] unless kind is select; the blank option comes first
    errors: list[str]


class ListFormOut(Schema):
    title: str  # the list's label for an add, «<label>: засах» for an edit
    fields: list[ListFieldOut]
    can_delete: bool  # true for an edit


def _manager(request: HttpRequest) -> None:
    if not request_user(request).has_perm("lists.manage_lists"):
        raise ApiError(403, [FORBIDDEN], code="forbidden")


def _spec(slug: str) -> ListSpec:
    spec = LISTS.get(slug)
    if spec is None:
        raise HttpError(404, _NOT_FOUND)
    return spec


def _entry(spec: ListSpec, raw: str) -> Any:
    """The entry with the signed pk `raw`; a junk or out-of-range pk and an unknown pk are both 404."""
    pk = service.parse_id(raw)
    entry = spec.model.objects.filter(pk=pk).first() if pk is not None else None
    if entry is None:
        raise HttpError(404, _NOT_FOUND)
    return entry


@list_router.get("", response=ListIndexOut, auth=django_auth)
def list_index(request: HttpRequest, q: str = "") -> ListIndexOut:
    _manager(request)
    text = q.strip()
    items = [
        ListIndexItemOut(slug=item.slug, label=item.label, count=item.count, hits=item.hits)
        for item in service.index_items(text)
    ]
    return ListIndexOut(
        items=items,
        show_meanings=service.show_meanings(text),
        meanings_count=len(MEANINGS),
        q=text,
    )


# Declared before /{slug}: «meaning» is a fixed route, not a list.
@list_router.get("/meaning", response=ListMeaningOut, auth=django_auth)
def list_meaning(request: HttpRequest) -> ListMeaningOut:
    _manager(request)
    rows = [
        ListMeaningRowOut(
            key=row.key,
            label=row.label,
            hint=row.hint,
            current=row.current,
            options=[ListMeaningOptionOut(value=pk, label=name or str(pk)) for pk, name in row.options],
        )
        for row in service.meaning_rows()
    ]
    return ListMeaningOut(rows=rows)


@list_router.get("/{slug}", response=ListPageOut, auth=django_auth)
def list_rows(request: HttpRequest, slug: str) -> ListPageOut:
    _manager(request)
    _spec(slug)
    with service_errors():
        page = service.list_page(slug)
    return ListPageOut(
        slug=page.slug,
        label=page.label,
        columns=[ListColumnOut(name=column.name, label=column.label) for column in page.columns],
        rows=[ListRowOut(id=row.pk, cells=row.cells) for row in page.rows],
    )


@list_router.get("/{slug}/form", response=ListFormOut, auth=django_auth)
def list_form(request: HttpRequest, slug: str, pk: str = "") -> ListFormOut:
    """The add pop-up with no pk, the edit pop-up with one. The rights are checked before the entry is looked up."""
    _manager(request)
    spec = _spec(slug)
    if pk:
        form = entry_form(spec)(instance=_entry(spec, pk))
        title, can_delete = f"{spec.label}: засах", True
    else:
        form = entry_form(spec)()
        title, can_delete = spec.label, False
    fields = [
        ListFieldOut(
            name=field.name,
            label=field.label,
            kind=field.kind,
            required=field.required,
            max_length=field.max_length,
            value=field.value,
            choices=[ListChoiceOut(value=value, label=label) for value, label in field.choices],
            errors=field.errors,
        )
        for field in service.entry_fields(spec, form)
    ]
    return ListFormOut(title=title, fields=fields, can_delete=can_delete)


class ListValuesIn(Schema):
    values: dict[str, str] = {}  # the form's boxes by field name; a box left empty is ""


class ListQuickIn(Schema):
    values: dict[str, str] = {}
    name: str | None = None  # the plain body Select.postName sends for a list with no pop-up: {"name": "..."}


class ListOkOut(Schema):
    ok: bool


class ListSaveOut(Schema):
    ok: bool
    form_errors: list[str] = []
    field_errors: dict[str, list[str]] = {}


class ListQuickOut(Schema):
    value: int  # the entry's pk, as Select reads it
    label: str  # the entry's stored name
    existed: bool  # True when a matching entry was picked instead of a new one created


class ListQuickErrorOut(Schema):
    error: str  # the first form error, as Select shows it
    field_errors: dict[str, list[str]] = {}


def _quick_spec(slug: str) -> ListSpec:
    spec = QUICK.get(slug)
    if spec is None:
        raise HttpError(404, _NOT_FOUND)
    return spec


def _save(spec: ListSpec, values: dict[str, str], entry: Any | None) -> ListSaveOut:
    result = service.save_entry(spec, values, entry=entry)
    if not result.ok:
        return ListSaveOut(ok=False, **form_error_payload(result.form))
    return ListSaveOut(ok=True)


@list_router.post("/meaning", response=ListOkOut, auth=django_auth)
def list_meaning_save(request: HttpRequest, payload: ListValuesIn) -> ListOkOut:
    """Set each meaning to the chosen entry; an empty choice deletes it, a junk or unknown pk changes nothing."""
    _manager(request)
    service.save_meanings(payload.values)
    return ListOkOut(ok=True)


@list_router.post("/{slug}", response=ListSaveOut, auth=django_auth)
def list_add(request: HttpRequest, slug: str, payload: ListValuesIn) -> ListSaveOut:
    """Add an entry to a list. Refused (ok false, status 200, nothing written) when the form is invalid."""
    _manager(request)
    return _save(_spec(slug), payload.values, None)


# Declared before /{slug}/{pk}: «quick» is a fixed route, not an id.
@list_router.post("/{slug}/quick", response={200: ListQuickOut, 400: ListQuickErrorOut}, auth=django_auth)
def list_quick(request: HttpRequest, slug: str, payload: ListQuickIn) -> Any:
    """Pick the entry with the same name, or create it, for a form dropdown. A form error answers 400."""
    _manager(request)
    spec = _quick_spec(slug)
    values = dict(payload.values)
    if payload.name is not None:
        values.setdefault("name", payload.name)
    result = service.quick_add(spec, values)
    if result.ok:
        assert result.id is not None  # set when ok is True
        return 200, ListQuickOut(value=result.id, label=result.name, existed=result.existed)
    return 400, ListQuickErrorOut(
        error=service.first_error(result.form),
        field_errors=form_error_payload(result.form)["field_errors"],
    )


@list_router.post("/{slug}/{pk}", response=ListSaveOut, auth=django_auth)
def list_edit(request: HttpRequest, slug: str, pk: str, payload: ListValuesIn) -> ListSaveOut:
    """Change entry `pk`; 404 for an unknown or junk pk. The same refusals as the add."""
    _manager(request)
    spec = _spec(slug)
    return _save(spec, payload.values, _entry(spec, pk))


@list_router.post("/{slug}/{pk}/delete", response=ListSaveOut, auth=django_auth)
def list_delete(request: HttpRequest, slug: str, pk: str) -> ListSaveOut:
    """Delete entry `pk`. An entry still in use is refused (ok false, the in-use text, the entry stays)."""
    _manager(request)
    spec = _spec(slug)
    result = service.delete_entry(_entry(spec, pk))
    if not result.ok:
        return ListSaveOut(ok=False, form_errors=[result.error])
    return ListSaveOut(ok=True)

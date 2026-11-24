"""Position-slot screen API under /api/v1/slots: the budget table «Орон тооны төлөвлөгөө» as the React page reads it.

GET /slots?year=&offset= (one batch of the year's rows, with the totals of every row of the year) and
GET /slots/options?year= (the choices of the add and edit pop-up, and the year a new row starts with).

POST /slots (add a row), POST /slots/{pk} (change row pk) and POST /slots/{pk}/delete. They validate with the Django
form employees.views_slots.SlotForm and write through employees.services.slots, so the log is the same as the Django
pop-up's. A refused write (an invalid form, a key already held, the database refusing the write) answers 200 with
ok false and nothing is written.

The rows, the counting and the year come from employees.services.slot_page and employees.services.slots; this module
reads the request, presents the answer and fills in the free-count classes copied from _slot_rows.html. Only holders
of employees.manage_position_slots may use it (403 "forbidden" for others, 401 for no login).
"""

from accounts.models import User
from config import batching
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from employees.models import CompanySettings
from employees.services import slot_page, slots
from employees.services.form_schema import add_info
from employees.services.slot_page import exists_message
from employees.slot_kind import MAIN, TEMPORARY
from employees.views_slots import SlotForm
from macs.models import Branch, NazgRow, Position
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.popups import FORBIDDEN, FieldAddOut, request_user

slot_router = Router(tags=["slots"])

HINT = "Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна."  # the same hint as the Django pop-up
FREE_NEGATIVE = "font-medium text-red-600"  # _slot_rows.html: more people than posts
FREE_ZERO = "text-amber-700"  # _slot_rows.html: every post is taken
_NOT_FOUND = "Хуудас олдсонгүй"  # the same message as the other API routes


class SlotTotalsOut(Schema):
    posts: int
    used: int
    free: int


class SlotRowOut(Schema):
    id: int
    position: str
    position_id: int  # for the edit pop-up, which sends ids
    branch: str
    branch_id: int
    kind: str  # the stored value: Main or Temporary
    kind_label: str  # «Үндсэн» or «Түр»
    posts: int
    used: int
    free: int  # negative when more people use the row than it has posts
    free_class: str  # the classes of the free count, "" for a positive count


class SlotListOut(Schema):
    year: int
    rows: list[SlotRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    totals: SlotTotalsOut  # over every row of the year, not only this batch
    enforce: bool  # CompanySettings.enforce_position_slots: a hire over the posts is refused
    settings_url: str  # the Django admin page where that setting is changed
    empty_text: str  # shown when the year has no rows at all


class SlotIdOptionOut(Schema):
    value: int
    label: str


class SlotKindOptionOut(Schema):
    value: str
    label: str


class SlotOptionsOut(Schema):
    positions: list[SlotIdOptionOut]
    branches: list[SlotIdOptionOut]
    kinds: list[SlotKindOptionOut]
    year: int  # the year a new row starts with
    min_year: int
    max_year: int
    hint: str
    # The quick-add info of the position and branch selects (null when the select cannot take a new entry).
    add_position: FieldAddOut | None = None
    add_branch: FieldAddOut | None = None


def _manager(request: HttpRequest) -> User:
    user = request_user(request)
    if not user.has_perm("employees.manage_position_slots"):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _offset(raw: str) -> int:
    """A non-negative number, else 0 (a bad or negative offset starts at the first batch, never an error)."""
    return int(raw) if raw.isdecimal() and len(raw) <= 18 else 0


def _free_class(free: int) -> str:
    if free < 0:
        return FREE_NEGATIVE
    if free == 0:
        return FREE_ZERO
    return ""


@slot_router.get("", response=SlotListOut, auth=django_auth)
def slot_list(request: HttpRequest, year: str = "", offset: str = "") -> SlotListOut:
    _manager(request)
    today = timezone.localdate()
    chosen = slot_page.year_param(year, today.year)
    lines = slot_page.slot_lines(chosen, today)
    start = _offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    shown, more = batching.window_at(lines, start, size)
    total = slot_page.totals(lines)
    return SlotListOut(
        year=chosen,
        rows=[
            SlotRowOut(
                id=line.row.pk,
                position=line.row.position.name,
                position_id=line.row.position_id,
                branch=line.row.branch.name,
                branch_id=line.row.branch_id,
                kind=line.row.kind,
                kind_label=slot_page.kind_label(line.row.kind),
                posts=line.posts,
                used=line.used,
                free=line.free,
                free_class=_free_class(line.free),
            )
            for line in shown
        ],
        next_offset=start + size if more else None,
        totals=SlotTotalsOut(posts=total.posts, used=total.used, free=total.free),
        enforce=CompanySettings.get().enforce_position_slots,
        settings_url=reverse("admin:employees_companysettings_changelist"),
        empty_text=f"{chosen} оны орон тоо бүртгэгдээгүй",
    )


@slot_router.get("/options", response=SlotOptionsOut, auth=django_auth)
def slot_options(request: HttpRequest, year: str = "") -> SlotOptionsOut:
    _manager(request)
    today = timezone.localdate()
    # The same form the pop-up draws: its widgets carry the quick-add attributes (StyledForm runs mark_addable).
    form = SlotForm()
    return SlotOptionsOut(
        add_position=add_info(form["position"].field.widget),
        add_branch=add_info(form["branch"].field.widget),
        positions=[
            SlotIdOptionOut(value=pk, label=name)
            for pk, name in Position.objects.order_by("name").values_list("pk", "name")
        ],
        branches=[
            SlotIdOptionOut(value=pk, label=name)
            for pk, name in Branch.objects.order_by("name").values_list("pk", "name")
        ],
        kinds=[
            SlotKindOptionOut(value=MAIN, label=slots.KIND_LABELS[MAIN]),
            SlotKindOptionOut(value=TEMPORARY, label=slots.KIND_LABELS[TEMPORARY]),
        ],
        year=slot_page.year_param(year, today.year),
        min_year=slot_page.MIN_YEAR,
        max_year=slot_page.MAX_YEAR,
        hint=HINT,
    )


class SlotWriteIn(Schema):
    # Every box may be empty: the form answers with its own «required» texts (React sends null for an empty box).
    position: int | None = None  # the Position pk
    branch: int | None = None  # the Branch pk
    kind: str = ""  # Main or Temporary
    year: int | None = None
    qty: int | None = None


class SlotWriteResultOut(Schema):
    ok: bool
    id: int | None  # the saved row's pk; None on a refusal and after a delete
    field_errors: dict[str, list[str]]
    form_errors: list[str]


def _refused(form_errors: list[str], field_errors: dict[str, list[str]] | None = None) -> dict[str, object]:
    return {"ok": False, "id": None, "field_errors": field_errors or {}, "form_errors": form_errors}


def _row_or_404(pk: int) -> NazgRow:
    row = NazgRow.objects.select_related("position", "branch").filter(pk=pk).first()
    if row is None:
        raise HttpError(404, _NOT_FOUND)
    return row


def _save(request: HttpRequest, payload: SlotWriteIn, pk: int | None) -> dict[str, object]:
    user = _manager(request)  # the right is checked before the row is looked up, so no pk leaks to a non-holder
    row = _row_or_404(pk) if pk is not None else None
    form = SlotForm(payload.dict(), row=row)
    if not form.is_valid():
        return {"ok": False, "id": None, **form_error_payload(form)}
    data = form.cleaned_data
    try:
        saved = slots.save_row(
            position=data["position"],
            branch=data["branch"],
            kind=data["kind"],
            year=data["year"],
            qty=data["qty"],
            by=user,
            row=row,
        )
    except slots.SlotRowExists as exists:  # another save took the key between the form check and the write
        return _refused([exists_message(exists.row)])
    except slots.SlotWriteDenied as denied:  # the database login lacks the grant on nazg: say so, no 500
        return _refused([denied.message])
    return {"ok": True, "id": saved.pk, "field_errors": {}, "form_errors": []}


@slot_router.post("", response=SlotWriteResultOut, auth=django_auth)
def slot_create(request: HttpRequest, payload: SlotWriteIn) -> dict[str, object]:
    """Add a slot row. Refused (ok false, status 200) when the form is invalid or the key is already held."""
    return _save(request, payload, None)


@slot_router.post("/{pk}", response=SlotWriteResultOut, auth=django_auth)
def slot_update(request: HttpRequest, pk: int, payload: SlotWriteIn) -> dict[str, object]:
    """Change row `pk`; 404 for an unknown pk. The same refusals as the add."""
    return _save(request, payload, pk)


@slot_router.post("/{pk}/delete", response=SlotWriteResultOut, auth=django_auth)
def slot_delete(request: HttpRequest, pk: int) -> dict[str, object]:
    """Delete row `pk`; 404 for an unknown pk. A refused delete (the database login lacks the grant) is ok false."""
    user = _manager(request)
    row = _row_or_404(pk)
    try:
        slots.delete_row(row, by=user)
    except slots.SlotWriteDenied as denied:
        return _refused([denied.message])
    return {"ok": True, "id": None, "field_errors": {}, "form_errors": []}

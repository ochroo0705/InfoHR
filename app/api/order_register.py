"""Order register and print API under /api/v1/orders/.

Routes: GET /register (one batch of the register), GET /print, POST /print/selected, POST /print/start,
GET /print/{token}/status and GET /print/{token}/file (the print job's progress and result).

The rows, the filters, the paging, the sort and the print jobs come from employees.services (order_register,
order_register_page, order_print_page, print_jobs); this module reads the request, presents the service's answer
and fills in the chip classes and labels copied from the register templates (_order_register_items.html,
_order_state.html, _awaiting_chip.html).
"""

import io
from typing import Literal

from accounts.audit import record_export
from accounts.models import User
from config import batching
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from employees import access
from employees.models import OrderState
from employees.services import (
    order_docs,
    order_files,
    order_print_page,
    order_register,
    order_register_page,
    print_jobs,
)
from employees.services.order_files import FilePayload
from employees.services.order_register import RegisterRow
from ninja import Form, Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.errors import ApiError
from api.params import batch_offset
from api.popups import FORBIDDEN, NOT_FOUND, request_user

order_register_router = Router(tags=["orders"])

# The chip classes of _order_register_items.html and _order_state.html, copied verbatim.
SEAL_CHIP = "seal"
REGISTERED_CHIP = "whitespace-nowrap rounded-full px-2 py-0.5 text-xs bg-sky-100 text-sky-900"
OTHER_CHIP = "whitespace-nowrap rounded-full px-2 py-0.5 text-xs bg-slate-200 text-slate-700"
LEGACY_CHIP = "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
NO_DATE = "—"
NO_NUMBER = "—"  # drawn grey by the page (number_muted), as the Django template does

# The «Бүх …» choices of the filter boxes (orders.html); React draws them from this, never from its own text.
ALL_LABELS = {
    "year": "Бүх он",
    "order_type": "Бүх төрөл",
    "department": "Бүх хэлтэс",
    "state": "Бүх төлөв",
}


class OrderRegisterChipOut(Schema):
    label: str
    class_name: str  # the chip's Tailwind classes, copied from _awaiting_chip.html


AWAITING_CHIP = OrderRegisterChipOut(
    label="Гарын үсэг хүлээж байна",
    class_name=(
        "whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 "
        "no-underline"
    ),
)


class OrderRegisterRowOut(Schema):
    key: str  # "o<order_id>" for an order of this program, "c<command_id>" for an old MACS row
    order_id: int | None  # None for an old MACS row
    employee_id: int
    number_label: str  # «№ 12 / 2026», «№ 12» without a date, «—» without a number
    date_label: str  # YYYY-MM-DD, or «—»
    employee_name: str
    department: str
    summary: str
    state: str  # an OrderState value, or "legacy" for an old MACS row
    state_label: str
    chip_class: str  # the classes of the state chip
    awaiting: bool  # the change behind the order waits for its signed order
    awaiting_chip: OrderRegisterChipOut | None  # the amber chip drawn after the state chip; None when not awaiting
    number_muted: bool  # the number is missing: the label is a grey «—»
    cancelled: bool  # the row is drawn struck through
    pickable: bool  # the row has a checkbox for «Сонгосныг хэвлэх»
    opens: Literal["detail", "employee"]  # what a row click opens


class OrderRegisterQueryOut(Schema):
    year: int | None
    order_type: int | None
    department: int | None
    state: str  # "" for every state
    q: str
    sort: str


class OrderRegisterSortHeadOut(Schema):
    next: str  # the sort a click on this header sends
    arrow: str  # «↑», «↓» or ""
    aria: str  # the aria-sort value, or ""


class OrderRegisterOptionOut(Schema):
    value: str
    label: str


class OrderRegisterOptionsOut(Schema):
    years: list[OrderRegisterOptionOut]
    types: list[OrderRegisterOptionOut]
    states: list[OrderRegisterOptionOut]
    departments: list[OrderRegisterOptionOut]


class OrderRegisterAllLabelsOut(Schema):
    year: str
    order_type: str
    department: str
    state: str


class OrderRegisterOut(Schema):
    rows: list[OrderRegisterRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    can_manage: bool
    report_link: bool  # «Тайлан гаргах» is shown: reports.view_reports and macs.view_employees
    background_from: int  # this many selected orders or more are printed in the background
    query: OrderRegisterQueryOut
    sort_heads: dict[str, OrderRegisterSortHeadOut]
    options: OrderRegisterOptionsOut
    all_labels: OrderRegisterAllLabelsOut


def _number_label(row: RegisterRow) -> str:
    if not row.number:
        return NO_NUMBER
    if row.date:
        return f"№ {row.number} / {row.date.year}"
    return f"№ {row.number}"


def _chip(row: RegisterRow) -> str:
    if row.state == order_register.LEGACY:
        return LEGACY_CHIP
    if row.state == OrderState.SIGNED:
        return SEAL_CHIP
    if row.state == OrderState.REGISTERED:
        return REGISTERED_CHIP
    return OTHER_CHIP


def _row_out(row: RegisterRow, can_manage: bool) -> OrderRegisterRowOut:
    key = f"o{row.order_id}" if row.order_id is not None else f"c{row.command_id}"
    return OrderRegisterRowOut(
        key=key,
        order_id=row.order_id,
        employee_id=row.employee_id,
        number_label=_number_label(row),
        date_label=row.date.isoformat() if row.date else NO_DATE,
        employee_name=row.employee_name,
        department=row.department,
        summary=row.summary,
        state=row.state,
        state_label=row.state_label,
        chip_class=_chip(row),
        awaiting=row.awaiting,
        awaiting_chip=AWAITING_CHIP if row.awaiting else None,
        number_muted=not row.number,
        cancelled=row.state == OrderState.CANCELLED,
        pickable=row.order_id is not None and row.state != OrderState.CANCELLED and can_manage,
        opens="detail" if row.order_id is not None else "employee",
    )


@order_register_router.get("/register", response=OrderRegisterOut, auth=django_auth)
def order_register_batch(
    request: HttpRequest,
    year: str = "",
    order_type: str = "",
    department: str = "",
    state: str = "",
    q: str = "",
    sort: str = "",
    offset: str = "",
) -> OrderRegisterOut:
    user = request_user(request)
    query = order_register_page.parse_query(
        {"year": year, "order_type": order_type, "department": department, "state": state, "q": q, "sort": sort}
    )
    today = timezone.localdate()
    options = order_register_page.filter_options(today)
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    rows, more = order_register.register_page(
        user,
        year=query.year,
        order_type=query.order_type,
        department_id=query.department,
        state=query.state or None,
        offset=start,
        size=size,
        today=today,
        q=query.q,
        sort=query.sort,
    )
    can_manage = access.can_manage(user)
    return OrderRegisterOut(
        rows=[_row_out(row, can_manage) for row in rows],
        next_offset=start + size if more else None,
        can_manage=can_manage,
        report_link=user.has_perm("reports.view_reports") and user.has_perm("macs.view_employees"),
        background_from=print_jobs.BACKGROUND_FROM,
        query=OrderRegisterQueryOut(
            year=query.year,
            order_type=query.order_type,
            department=query.department,
            state=query.state,
            q=query.q,
            sort=query.sort,
        ),
        sort_heads={
            name: OrderRegisterSortHeadOut(**head) for name, head in order_register.sort_heads(query.sort).items()
        },
        options=OrderRegisterOptionsOut(
            years=[OrderRegisterOptionOut(value=str(y), label=str(y)) for y in options.years],
            types=[OrderRegisterOptionOut(value=str(value), label=label) for value, label in options.types],
            states=[OrderRegisterOptionOut(value=value, label=label) for value, label in options.states],
            departments=[OrderRegisterOptionOut(value=str(pk), label=name) for pk, name in options.departments],
        ),
        all_labels=OrderRegisterAllLabelsOut(**ALL_LABELS),
    )


class OrderPrintRowOut(Schema):
    n: int  # the number inside the department group, from 1
    date: str  # YYYY-MM-DD, or "" for none
    employee_name: str
    position: str
    number: str
    summary: str
    issued_by: str
    register_no: str
    gender: str
    age: str  # "" for none


class OrderPrintGroupOut(Schema):
    department: str
    rows: list[OrderPrintRowOut]


class OrderPrintOut(Schema):
    company: str
    today: str  # YYYY-MM-DD, the day the page is printed
    groups: list[OrderPrintGroupOut]
    empty: bool  # no row matches the filters


@order_register_router.get("/print", response=OrderPrintOut, auth=django_auth)
def order_print(
    request: HttpRequest,
    response: HttpResponse,
    year: str = "",
    order_type: str = "",
    department: str = "",
    state: str = "",
    q: str = "",
    sort: str = "",
) -> OrderPrintOut:
    """Every matching row, grouped by department, as the print page draws it. Writes one export log line."""
    user = request_user(request)
    query = order_register_page.parse_query(
        {"year": year, "order_type": order_type, "department": department, "state": state, "q": q, "sort": sort}
    )
    today = timezone.localdate()
    rows = order_register.register_rows(
        user,
        year=query.year,
        order_type=query.order_type,
        department_id=query.department,
        state=query.state or None,
        today=today,
        q=query.q,
        sort=query.sort,
    )
    record_export(
        request,
        "print_page",
        "Тушаалын бүртгэл",
        filters=order_print_page.register_label(query, order_register_page.filter_options(today)),
        rows=len(rows),
    )
    response["Cache-Control"] = "no-store"  # the printed page must not come back from the Back cache
    groups = order_print_page.build_groups(rows)
    return OrderPrintOut(
        company=order_print_page.company_name(),
        today=today.isoformat(),
        groups=[
            OrderPrintGroupOut(
                department=group.department,
                rows=[
                    OrderPrintRowOut(
                        n=n,
                        date=row.date.isoformat() if row.date else "",
                        employee_name=row.employee_name,
                        position=row.position,
                        number=row.number,
                        summary=row.summary,
                        issued_by=row.issued_by,
                        register_no=row.register_no,
                        gender=row.gender,
                        age="" if row.age is None else str(row.age),
                    )
                    for n, row in enumerate(group.rows, start=1)
                ],
            )
            for group in groups
        ],
        empty=not rows,
    )


PDF_NAME = "tushaal-songoson.pdf"  # the name the Django views give the printout too


class OrderPrintStartOut(Schema):
    token: str
    status: str  # the API path of the job's status: /api/v1/orders/print/<token>/status
    file: str  # the API path of the job's PDF, answered once the job is ready


class OrderPrintStatusOut(Schema):
    state: Literal["running", "ready", "failed"]
    count: int  # the number of orders in the job
    message: str  # "" unless the job failed or went stale


def _manage(user: User) -> None:
    """Printing many orders needs the manage right (403 «forbidden» without it, as the Django views)."""
    if not access.can_manage(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")


@order_register_router.post("/print/selected", auth=django_auth)
def order_print_selected(request: HttpRequest, ids: Form[list[str] | None] = None) -> HttpResponse:
    """The ticked orders as one PDF, one order per page. Form-encoded `ids` so a plain form can post them; each
    printed order is logged like a single download."""
    user = request_user(request)
    _manage(user)
    try:
        data, printed = print_jobs.render_now(user, set(print_jobs.parse_ids(ids or [])))
    except print_jobs.NothingToPrint:
        raise ApiError(400, [print_jobs.NOTHING]) from None
    for order in printed:
        record_export(request, "download_order", print_jobs.export_label(order))
    return order_files.file_response(
        FilePayload(
            handle=io.BytesIO(data),
            content_type=order_docs.PDF_TYPE,
            filename=PDF_NAME,
            inline=False,
            private=True,
        )
    )


@order_register_router.post("/print/start", response=OrderPrintStartOut, auth=django_auth)
def order_print_start(request: HttpRequest, ids: Form[list[str] | None] = None) -> OrderPrintStartOut:
    """Start the ticked orders' PDF as a background job (11 orders or more); the page polls the job's status."""
    user = request_user(request)
    _manage(user)
    parsed = print_jobs.parse_ids(ids or [])
    if not parsed:
        raise ApiError(400, [print_jobs.NOTHING])
    token = print_jobs.start(user, parsed)
    return OrderPrintStartOut(
        token=token,
        status=f"/api/v1/orders/print/{token}/status",
        file=f"/api/v1/orders/print/{token}/file",
    )


@order_register_router.get("/print/{token}/status", response=OrderPrintStatusOut, auth=django_auth)
def order_print_status(request: HttpRequest, token: str) -> OrderPrintStatusOut:
    """The job's state. Only the user who started it may read it (404 otherwise, and for an unknown token)."""
    user = request_user(request)
    _manage(user)
    info = print_jobs.status(user, token)
    if info is None:
        raise HttpError(404, NOT_FOUND)
    return OrderPrintStatusOut(**info)


@order_register_router.get("/print/{token}/file", auth=django_auth)
def order_print_file(request: HttpRequest, token: str) -> HttpResponse:
    """The job's PDF once it is ready. 404 until then, and for another user's or an unknown job."""
    user = request_user(request)
    _manage(user)
    path = print_jobs.pdf_path(user, token)
    if path is None:
        raise HttpError(404, NOT_FOUND)
    return order_files.file_response(
        FilePayload(
            handle=path.open("rb"),
            content_type=order_docs.PDF_TYPE,
            filename=PDF_NAME,
            inline=False,
            private=True,
        )
    )

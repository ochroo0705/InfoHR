"""The event form pop-up without a request: the state behind the GET branches of `views.event_form`.

`build_page` returns what the form shows on first open, after a kind change, and after a date change. The Django view
and the React pop-up both draw from it. The rules stay here (which fields a type has, whether the order block shows,
the note on past and future dates); the caller only renders.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone

from employees import access
from employees.forms import CancelEventForm, EventForm, OrderFieldsForm
from employees.models import Employee, Event, EventType, HrOrder, JobRecord, OrderState
from employees.services import events, history, orders
from employees.services.events import ALLOWED_FIELDS, SALARY_TYPES, EventError
from employees.services.history import salary_on

# Types whose change can need an order (the service decides; a pay or leave change never does).
ORDER_TYPES = frozenset(EventType.values) - {EventType.SALARY_CHANGE, EventType.LEAVE_START, EventType.LEAVE_RETURN}


@dataclass
class EventPage:
    """What the event form pop-up shows.

    `prev_effective` is the literal hidden value the next change must send back. A caller renders it when it is not
    None, and renders the form's effective date as ISO only when it is None (what `_event_form.html` does). `reload` is
    true when a kind or date change rebuilt an open form (no open animation), i.e. when `prev_effective` was sent.
    """

    employee: Employee
    type: str
    title: str
    kinds: list[tuple[str, str, bool]]
    form: EventForm
    order_form: OrderFieldsForm | None
    summary: str
    when: str
    prev_effective: str | None
    reload: bool
    effective_text: bool = False  # the date box is a text box (a date typed that is not real): see `_text_date_box`


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _event_initial(employee: Employee, type: str, effective: date, with_salary: bool) -> dict[str, Any]:
    """The values in force on `effective`, so the form shows what would change."""
    initial: dict[str, Any] = {"effective": effective}
    job: JobRecord | None = history.job_on(employee, effective)
    if job is not None:
        for name in ALLOWED_FIELDS[type]:
            initial[name] = getattr(job, f"{name}_id" if name in ("position", "department", "manager") else name)
    current = salary_on(employee, effective) if with_salary else None
    if current is not None:
        initial["salary"] = current.base_salary
    return initial


def _event_summary(employee: Employee, form: EventForm) -> str:
    """'Нягтлан → Ахлах нягтлан · 2026-11-01-нээс' for the values typed so far."""
    data = getattr(form, "cleaned_data", {})
    effective = data.get("effective")
    job = history.job_on(employee, effective) if effective else None
    if effective is None or job is None:
        return ""
    new = {f: data[f] for f in form.job_fields if f in data and getattr(job, f) != data[f]}
    parts = [f"{d['old']} → {d['new']}" for d in events._diffs(job, new)]
    salary = data.get("salary")
    current = salary_on(employee, effective)
    if form.with_salary and isinstance(salary, Decimal) and (current is None or current.base_salary != salary):
        parts.append(f"{current.base_salary if current else '—'} → {salary}")
    return f"{'; '.join(parts)} · {effective:%Y-%m-%d}-нээс" if parts else ""


def build_page(
    user: User,
    employee: Employee,
    type: str,
    values: Mapping[str, str] | None,
    *,
    prev_effective: str | None = None,
    today: date | None = None,
) -> EventPage:
    """The GET state of the event form.

    `values` None is the first open. Otherwise `values` are the fields typed in the open form, after a kind change or
    a date change; with a date change `prev_effective` is the date the boxes reflected before it.
    """
    _require_record(user, type)
    today = today or timezone.localdate()
    source: Mapping[str, str] = values or {}
    with_salary = access.can_manage_salary(user) and type in SALARY_TYPES
    missing = events.start_placement_missing(employee)  # QC 1d: MACS-only employee with no department/position
    order_form: OrderFieldsForm | None = None
    if type in ORDER_TYPES and orders.event_asks_for_order(type):
        # A form rebuilt from an open one (kind change) keeps the order fields already typed, unvalidated.
        typed_order = {
            name: source[f"order-{name}"]
            for name in OrderFieldsForm.base_fields
            if prev_effective is not None and f"order-{name}" in source
        }
        order_form = OrderFieldsForm(None, prefix="order", initial=typed_order)
    # A date typed in an open form: the form itself reads it, since DateField takes more formats than ISO.
    typed_date: EventForm | None = None
    if source.get("effective"):
        typed_date = EventForm(
            type, source, with_salary=with_salary, start_missing=missing, user=user, employee=employee
        )
        typed_date.full_clean()
    effective: date | None
    summary = ""
    if typed_date is not None and "effective" in typed_date.errors:
        # A date typed but not real (2026-13-45): keep what was typed and show the error, never replace it with today.
        # The hidden prev_effective stays the last real date, so a correction keeps what was typed meanwhile.
        form = typed_date
        # Only the date's own error: the other fields are untouched while the date is still being typed.
        for name in [n for n in form.errors if n != "effective"]:
            del form.errors[name]
        effective = None
        previous_valid = _parse_day(prev_effective)
        page_prev = previous_valid.isoformat() if previous_valid else ""  # the view's literal value, even when empty
    else:
        effective = typed_date.cleaned_data["effective"] if typed_date is not None else today
        initial = _event_initial(employee, type, effective, with_salary)
        initial["reason"] = source.get("reason", "")
        initial["note"] = source.get("note", "")
        previous = _parse_day(prev_effective)
        if previous is not None and values is not None:
            # The date was changed in an open form: keep what the user edited, refill
            # the rest with the values in force on the new date.
            typed = EventForm(
                type, values, with_salary=with_salary, start_missing=missing, user=user, employee=employee
            )
            before = _event_initial(employee, type, previous, with_salary)
            for name, form_field in typed.fields.items():
                if name not in ("effective", "reason", "note") and name in values:
                    value = typed[name].data
                    if form_field.has_changed(before.get(name), value):
                        initial[name] = value
        form = EventForm(
            type, initial=initial, with_salary=with_salary, start_missing=missing, user=user, employee=employee
        )
        page_prev = None  # the view passes None here: the template renders the form's effective date
    _text_date_box(form)
    return _make_page(
        employee,
        type,
        form,
        order_form,
        summary=summary,
        effective=effective,
        today=today,
        prev_effective=page_prev,
        reload=prev_effective is not None,
    )


def summary_line(user: User, employee: Employee, type: str, values: Mapping[str, str]) -> str:
    """The summary line for the values typed so far (the GET `?summary=1` of `views.event_form`)."""
    _require_record(user, type)
    with_salary = access.can_manage_salary(user) and type in SALARY_TYPES
    missing = events.start_placement_missing(employee)  # QC 1d: MACS-only employee with no department/position
    form = EventForm(type, values, with_salary=with_salary, start_missing=missing, user=user, employee=employee)
    form.full_clean()
    return _event_summary(employee, form)


@dataclass
class EventOutcome:
    """What `submit` did. `ok` false means nothing was written; `page` is the bound form to show again. `order` is the
    order the event created (for the MACS number-clash note), None when nothing was written."""

    ok: bool
    page: EventPage
    order: HrOrder | None


@dataclass
class CancelPage:
    """What the cancel pop-up shows: the title and hint of the event, and its empty form."""

    title: str
    hint: str
    form: CancelEventForm
    event: Event


def _require_record(user: User, type: str) -> None:
    if type not in EventType.values:
        raise Http404
    if not access.can_record_event(user, type):
        raise PermissionDenied


def _text_date_box(form: EventForm) -> None:
    """A bound form with a date error: the date box becomes a text box, which keeps the value it cannot hold.
    datepicker.js still enhances it."""
    if form.is_bound and "effective" in form.errors:
        form.fields["effective"].widget.input_type = "text"
        form.fields["effective"].widget.attrs["data-datepicker"] = ""


def _make_page(
    employee: Employee,
    type: str,
    form: EventForm,
    order_form: OrderFieldsForm | None,
    *,
    summary: str,
    effective: date | None,
    today: date,
    prev_effective: str | None,
    reload: bool,
) -> EventPage:
    """The one place an `EventPage` is built: the title and kind list of the type, and the past or future note."""
    placement = type in events.PLACEMENT_TYPES
    return EventPage(
        employee=employee,
        type=type,
        title=events.PLACEMENT_LABEL if placement else EventType(type).label,
        kinds=[(t.value, t.label, t == type) for t in events.PLACEMENT_TYPES] if placement else [],
        form=form,
        order_form=order_form,
        summary=summary,
        when="past" if effective and effective < today else "future" if effective and effective > today else "",
        prev_effective=prev_effective,
        reload=reload,
        effective_text=form.is_bound and "effective" in form.errors,
    )


def _attach_errors(errors: dict[str, str], form: EventForm, order_form: OrderFieldsForm | None) -> None:
    """An order key (`order_*`) goes to the order block's field; any other key to the form field of that name, or to
    the form's general errors when there is no such field."""
    for name, message in errors.items():
        if name.startswith("order_") and order_form is not None:
            order_form.add_service_errors({name: message})
        else:
            form.add_error(name if name in form.fields else None, message)


def _bound_page(
    employee: Employee, type: str, form: EventForm, order_form: OrderFieldsForm | None, values: Mapping[str, str]
) -> EventPage:
    """The page after a submit, as the view's POST branch builds it: the bound form with its errors, the hidden
    `prev_effective` (the form's date when it is real, else the last real date posted), the summary and `reload`."""
    today = timezone.localdate()
    effective: date | None = form.cleaned_data.get("effective")
    if effective is not None:
        prev_effective = effective.isoformat()
    else:
        previous_valid = _parse_day(values.get("prev_effective"))
        prev_effective = previous_valid.isoformat() if previous_valid else ""
    _text_date_box(form)
    return _make_page(
        employee,
        type,
        form,
        order_form,
        summary=_event_summary(employee, form),
        effective=effective,
        today=today,
        prev_effective=prev_effective,
        reload=True,
    )


def submit(user: User, employee: Employee, type: str, values: Mapping[str, str]) -> EventOutcome:
    """The POST of the event form (`views.event_form`) without the request. Nothing is written unless both forms are
    valid and `events.record` accepts the change. A refused termination keeps the offboarding checklist it started:
    `gate.prepare` runs outside the record transaction, as in the view; `events.record` rolls back its own writes."""
    _require_record(user, type)
    with_salary = access.can_manage_salary(user) and type in SALARY_TYPES
    missing = events.start_placement_missing(employee)  # QC 1d: MACS-only employee with no department/position
    order_form: OrderFieldsForm | None = None
    if type in ORDER_TYPES and orders.event_asks_for_order(type):
        order_form = OrderFieldsForm(values, prefix="order")
    form = EventForm(type, values, with_salary=with_salary, start_missing=missing, user=user, employee=employee)
    form_ok = form.is_valid()
    # The order form is validated even when the event form is not: the view validates it while rendering, so the
    # errors shown are the same.
    order_ok = order_form is None or order_form.is_valid()
    if form_ok and order_ok:
        data = form.cleaned_data
        salary = data.get("salary") if with_salary else None
        current = salary_on(employee, data["effective"])
        if salary is not None and type != EventType.SALARY_CHANGE and current and current.base_salary == salary:
            salary = None  # the form is pre-filled with the current pay; untouched means no pay change
        order_kwargs: dict[str, Any] = (
            {
                "order_number": order_form.cleaned_data["number"],
                "order_date": order_form.cleaned_data["date"],
                "order_summary": order_form.cleaned_data["summary"],
                "order_issued_by": order_form.cleaned_data["issued_by"],
            }
            if order_form is not None
            else {}
        )
        try:
            if type == EventType.TERMINATION:
                from checklists.services import gate  # local: checklists imports employees

                fired = data.get("fired_reason")
                gate.prepare(
                    employee,
                    reason=str(fired.pk) if fired is not None else None,
                    anchor_day=data["effective"],
                    by=user,
                )
                order_kwargs["offboarding_override"] = data.get("offboarding_override", "")
            if type == EventType.REHIRE:
                order_kwargs["slot_override"] = data.get("slot_override", "")
            event = events.record(
                employee,
                type=type,
                effective=data["effective"],
                changes={f: data[f] for f in form.job_fields},
                salary=salary,
                reason=data.get("reason", ""),
                fired_reason=data.get("fired_reason"),
                pension=bool(data.get("pension")),
                note=data["note"],
                by=user,
                expected_return=data.get("expected_return"),
                start_department=data.get("start_department"),
                start_position=data.get("start_position"),
                **order_kwargs,
            )
        except EventError as error:
            _attach_errors(error.errors, form, order_form)
        else:
            page = _bound_page(employee, type, form, order_form, values)
            return EventOutcome(ok=True, page=page, order=HrOrder.objects.filter(event=event).first())
    page = _bound_page(employee, type, form, order_form, values)
    return EventOutcome(ok=False, page=page, order=None)


def _check_cancel(user: User, employee: Employee, event_id: int) -> Event:
    """The event may be cancelled by this user, and is still scheduled or waiting (views.event_cancel's guards)."""
    event = employee.events.filter(pk=event_id).first()
    if event is None:
        raise Http404
    if not access.can_cancel(user, event):
        raise PermissionDenied
    if event.status(timezone.localdate()) not in ("scheduled", "awaiting_signature"):
        raise Http404
    return event


def _is_signed(order: HrOrder | None) -> bool:
    return order is not None and order.state == OrderState.SIGNED


def _cancel_hint(event: Event, order: HrOrder | None) -> str:
    hint = "Өөрчлөлт цуцлагдсан гэж түүхэнд үлдэнэ."
    if order is not None:
        hint = "Өөрчлөлт болон түүний тушаал цуцлагдсан гэж түүхэнд үлдэнэ."
    if event.applied_at is not None:  # events.cancel undoes the job and salary rows of an applied change
        hint += " Өөрчлөлт аль хэдийн бүртгэгдсэн бол ажилтны албан тушаал, цалин өмнөх утгад буцна."
    if order is not None and _is_signed(order):
        hint += f" Цуцлах дугаар нь № {order.number} тушаалыг хүчингүй болгосон ШИНЭ тушаалын дугаар."
    return hint


def cancel_page(user: User, employee: Employee, event_id: int) -> CancelPage:
    """The GET of the cancel pop-up (`views.event_cancel`)."""
    event = _check_cancel(user, employee, event_id)
    order = HrOrder.objects.filter(event=event).first()
    return CancelPage(
        title=f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})",
        hint=_cancel_hint(event, order),
        form=CancelEventForm(signed=_is_signed(order)),
        event=event,
    )


def submit_cancel(
    user: User, employee: Employee, event_id: int, values: Mapping[str, str]
) -> tuple[bool, CancelEventForm]:
    """The POST of the cancel pop-up. Returns (ok, form); a refusal leaves the form bound with its errors."""
    event = _check_cancel(user, employee, event_id)
    order = HrOrder.objects.filter(event=event).first()
    form = CancelEventForm(values, signed=_is_signed(order))
    if not form.is_valid():
        return False, form
    try:
        events.cancel(
            event,
            reason=form.cleaned_data["reason"],
            by=user,
            cancel_order_no=form.cleaned_data.get("cancel_order_no", ""),
        )
    except EventError as error:
        for name, message in error.errors.items():
            form.add_error(name if name in form.fields else None, message)
        return False, form
    return True, form

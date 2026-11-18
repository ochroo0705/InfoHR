"""The employee page's read rules, shared by the Django page (`employees.views.detail_context`) and the API
(`app/api/employee.py`). `detail_facts` is what the page shows about one employee for one user on one day: no request
and no session here. The view adds the request-bound keys (the forms and the one-shot order warning)."""

from datetime import date
from types import SimpleNamespace
from typing import Any

from accounts.models import User
from django.db.models import F, QuerySet
from leave import access as leave_access
from leave.services import ledger as leave_ledger
from macs.models import Absence, Command

from employees import access, history_range, sections
from employees.forms import EmployeeForm
from employees.listing import current_salary, row_for
from employees.models import ActivityEntry, ChangeType, Employee, Event, EventType, HrOrder, ext_of
from employees.services import events, orders, personal_rows, records, setup
from employees.services import personal_writes as pw

ACTIVITY_BATCH = 50  # log entries per batch in the «Түүх» drawer; older ones load as the drawer scrolls


def _is_scheduled(event: Event | None, today: date) -> bool:
    """A change that can still be cancelled: scheduled, or waiting for its signed order (any date)."""
    return event is not None and event.status(today) in ("scheduled", "awaiting_signature")


def needs_setup(employee: Employee) -> bool:
    """Whether the employee's setup checklist (Бүрдүүлэлт) is still open: the items may be ticked."""
    ext = ext_of(employee)
    return ext is not None and ext.setup_required


def _mark_scheduled(rows: Any, user: User, today: date) -> list[Any]:
    """Flag history rows of a not-yet-effective event, and whether this user may cancel it."""
    result = list(rows)
    for row in result:
        row.scheduled = row.period.lower > today
        row.locked = _is_scheduled(row.event, today)
        row.cancellable = row.locked and access.can_cancel(user, row.event)
        row.label = row.event.get_type_display() if row.event is not None else row.get_change_type_display()
    return result


def _next_event(employee: Employee, can_salary: bool, today: date) -> Event | None:
    """The next change still to come: applied ones and waiting ones (awaiting their signed order) dated after today."""
    qs = employee.events.filter(cancelled_at__isnull=True, effective__gt=today)
    if not can_salary:  # a scheduled pay change must not leak to people who cannot see pay
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    return qs.order_by("effective").first()


def _awaiting_rows(employee: Employee, user: User, can_salary: bool) -> list[Any]:
    """The Work tab's «Гарын үсэг хүлээж буй өөрчлөлт» block: changes waiting for their signed order, newest first.
    Each row has `label`, `event`, its `order` (or None) and `cancellable` (the user may cancel it)."""
    qs = employee.events.filter(applied_at__isnull=True, cancelled_at__isnull=True).order_by("-created_at", "-pk")
    if not can_salary:  # a waiting pay change must not leak to people who cannot see pay
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    events_list = list(qs)
    orders_by_event = {o.event_id: o for o in HrOrder.objects.filter(event_id__in=[e.pk for e in events_list])}
    return [
        SimpleNamespace(
            event=ev,
            label=ev.get_type_display(),
            order=orders_by_event.get(ev.pk),
            cancellable=access.can_cancel(user, ev),
        )
        for ev in events_list
    ]


def _checklist_section(user: User, employee: Employee, today: date) -> dict[str, object]:
    """Context of the employee page's checklist panels (`checklist_visible` False when the user sees none of them)."""
    from checklists.views import section_context  # local: checklists imports employees

    return section_context(user, employee, today)


def _leave_section(user: User, employee: Employee, today: date) -> dict[str, object]:
    """Context of the employee page's leave block: grant periods read live. Viewing never writes grants."""
    if not leave_access.can_view(user):
        return {"leave_visible": False}
    periods, nowhere = leave_ledger.periods(employee, today)
    return {
        "leave_visible": True,
        "leave_configured": leave_ledger.annual_configured(),
        "leave_periods": periods,
        "leave_nowhere": nowhere,
        "old_absences": list(
            Absence.objects.filter(employee_id=employee.pk).select_related("absence_type").order_by("-from_date", "-pk")
        ),
        "can_record_leave": leave_access.can_record(user),
        "can_manage_leave_settings": leave_access.can_manage_settings(user),
    }


def order_rows(employee: Employee) -> list[dict[str, Any]]:
    """Our orders (newest first) plus MACS's own command rows (read-only, state «MACS»)."""
    # An order without a date (waiting for its number) is the newest: NULLs first, as PostgreSQL sorts them
    # by default. Firebird sorts NULL last on DESC, which would move the hire order and change which row claims it.
    newest_first = (F("date").desc(nulls_first=True), "-pk")
    ours = list(employee.hr_orders.select_related("event").order_by(*newest_first))
    taken = {o.command_id for o in ours if o.command_id}
    legacy = [c for c in Command.objects.filter(employee_id=employee.pk).order_by(*newest_first) if c.pk not in taken]
    links = orders.cancellation_links(ours)
    rows: list[dict[str, Any]] = [{"order": o, "legacy": None, **links[o.pk]} for o in ours]
    rows += [{"order": None, "legacy": c} for c in legacy]
    return rows


def _awaiting(order: HrOrder | None) -> bool:
    event = order.event if order is not None else None
    return event is not None and event.applied_at is None and event.cancelled_at is None


def change_rows(jobs: list[Any], order_list: list[dict[str, Any]]) -> tuple[list[Any], list[dict[str, Any]]]:
    """The Work tab's one list: each history row carries its order (`row.order`, `row.order_row` with the cancel
    links), and a cancelled change that had an order stays as a struck-through row. Returns (rows newest first,
    the order rows no change claims: MACS commands and the like)."""
    by_event = {r["order"].event_id: r for r in order_list if r["order"] and r["order"].event_id}
    hire = next((r for r in order_list if r["order"] and r["order"].is_hire), None)
    hire_job = next((j for j in reversed(jobs) if j.change_type == ChangeType.HIRE), None)  # `jobs` is newest first
    claimed: set[int] = set()
    for job in jobs:
        link = by_event.get(job.event_id) if job.event_id else (hire if job is hire_job else None)
        job.order_row, job.order = link, link["order"] if link else None
        job.is_cancelled = False
        if link:
            claimed.add(link["order"].pk)
    rows: list[Any] = list(jobs)
    for link in order_list:
        order = link["order"]
        if order and order.pk not in claimed and order.event and order.event.cancelled_at:
            rows.append(
                SimpleNamespace(
                    is_cancelled=True,
                    event=order.event,
                    order=order,
                    order_row=link,
                    label=order.event.get_type_display(),
                    effective=order.event.effective,
                )  # fmt: skip
            )
            claimed.add(order.pk)
    rows.sort(key=lambda r: r.effective if r.is_cancelled else r.period.lower, reverse=True)
    # An order whose change still waits is shown in the «Гарын үсэг хүлээж буй өөрчлөлт» block, not here.
    return rows, [
        r for r in order_list if (not r["order"] or r["order"].pk not in claimed) and not _awaiting(r["order"])
    ]


def _personal_lists(employee: Employee) -> dict[str, list[personal_rows.PersonalRow]]:
    return {kind: personal_rows.rows(kind, employee) for kind in pw.KINDS}


def _section_context(
    employee: Employee,
    section: str,
    names: tuple[str, ...],
    form: EmployeeForm | None,
    editing: bool = False,
    can_manage: bool = False,
    with_lists: bool = True,
    user: User | None = None,
) -> dict[str, object]:
    """Context of a section template: its bound fields, or the stored form when the save succeeded (read mode)."""
    if form is None:
        form = EmployeeForm(employee=employee, user=user)
    rows = sections.read_rows(employee, section, records.birth_place_text(employee))
    return {
        "employee": employee,
        "section": section,
        "name": section,
        "title": sections.TITLES[section],
        "form": form,
        "fields": [form[name] for name in names],
        "editing": editing,
        "form_errors": sections.outside_errors(form, names) if editing else [],
        "rows": rows,
        "can_manage": can_manage,
        "personal": _personal_lists(employee) if with_lists and section in ("contact", "education") else {},
    }


def _personal_sections(employee: Employee, can_manage: bool, user: User) -> dict[str, dict[str, object]]:
    """Read-mode context of the four field sections of the personal tab, from one form instance."""
    form = EmployeeForm(employee=employee, user=user)
    return {
        name: _section_context(employee, name, names, form, False, can_manage, user=user)
        for name, names in sections.SECTIONS.items()
    }


def _section_counts(personal: dict[str, list[personal_rows.PersonalRow]], employee: Employee) -> dict[str, object]:
    """The grey numbers of the personal tab menu: rows per list, addresses for «Холбоо барих, хаяг», and
    filled/total for «Бусад мэдээлэл»."""
    counts: dict[str, object] = {kind: len(rows) for kind, rows in personal.items() if kind != "address"}
    counts["address"] = len(personal.get("address", []))
    filled, total = sections.other_progress(employee)
    counts["other"] = f"{filled}/{total}"
    return counts


def activity_context(activity: QuerySet[ActivityEntry]) -> dict[str, object]:
    """The activity log as the page shows it: the drawer's newest entries, the Түүх count, the header's latest line."""
    count = activity.count()
    return {
        "activity": activity.select_related("by")[:ACTIVITY_BATCH],
        "activity_count": count,
        "activity_next_query": f"offset={ACTIVITY_BATCH}" if count > ACTIVITY_BATCH else "",
        "latest_activity": activity.select_related("by").first(),
    }


def detail_facts(user: User, employee: Employee, today: date) -> dict[str, object]:
    """What the employee page shows about this employee for this user on this day (no request, no session)."""
    can_salary = access.can_view_salary(user)
    can_manage = access.can_manage(user)
    can_view_personal = access.can_view_personal(user, employee)
    personal = _personal_lists(employee) if can_view_personal else {}
    activity = access.visible_activity(user, employee)
    ext = ext_of(employee)
    show_setup = ext is not None and ext.setup_required and can_manage
    setup_items = setup.status(employee, user) if show_setup else None
    row = row_for(employee, today)
    jobs = _mark_scheduled(
        employee.job_records.select_related("position", "department", "manager", "event").order_by(
            *history_range.ORDER_DESC
        ),
        user,
        today,
    )
    order_list = order_rows(employee)
    for entry in order_list:  # scan_ok: may this user open the row's signed scan (access.can_open_order_scan)
        entry["scan_ok"] = entry["order"] is None or access.can_open_order_scan(user, entry["order"])
    changes, other_orders = change_rows(jobs, order_list)
    menu = [
        (t.value, events.PLACEMENT_LABEL if t == EventType.TRANSFER else t.label)
        for t in EventType
        if t in events.AVAILABLE.get(row.state, ())
        and access.can_record_event(user, t.value)
        and t not in events.PLACEMENT_TYPES[1:]  # one item opens all three, see event_form
    ]
    return {
        "employee": employee,
        "birth_place": records.birth_place_text(employee),
        "setup": setup_items,
        "setup_done": sum(i.done for i in setup_items) if setup_items else 0,
        "setup_complete": setup.complete_for(employee, user) if show_setup else False,
        "row": row,
        "jobs": changes,
        "waiting": _awaiting_rows(employee, user, can_salary),
        "salary": current_salary(employee, today) if can_salary else None,
        "salaries": (
            _mark_scheduled(
                employee.salary_records.select_related("event").order_by(*history_range.ORDER_DESC), user, today
            )
            if can_salary
            else []
        ),
        "orders": other_orders,
        "event_menu": menu,
        "event_allowed": {value for value, _ in menu},
        "next_event": _next_event(employee, can_salary, today),
        "leave_until": events.leave_until(employee, today) if row.state == "long_leave" else None,
        **activity_context(activity),
        "can_manage": can_manage,
        **_leave_section(user, employee, today),
        **_checklist_section(user, employee, today),
        "can_view_salary": can_salary,
        "can_manage_salary": access.can_manage_salary(user),
        "can_view_personal": can_view_personal,
        "personal": personal,
        "personal_sections": _personal_sections(employee, can_manage, user) if can_view_personal else {},
        "section_counts": _section_counts(personal, employee) if can_view_personal else {},
        "today": today,
    }

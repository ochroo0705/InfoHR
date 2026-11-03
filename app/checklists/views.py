"""Checklist views: the employee page panel, and the POST-only tick, untick and start.

A user who may not see or do something gets 404, so the answer never says that a task or checklist exists.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Case, When
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from employees import access as employee_access
from employees.models import Employee

from checklists import access
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask
from checklists.services import lifecycle, owners


@dataclass(frozen=True)
class TaskRow:
    task: ChecklistTask
    owner_label: str
    overdue: bool
    can_tick: bool
    can_untick: bool


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)  # noqa: S101
    return request.user


def today() -> date:
    return timezone.localdate()


def _static_label(task: ChecklistTask) -> str:
    if task.group is not None:
        return task.group.name
    if task.manager:
        return owners.RULE_LABELS[owners.RULE_MANAGER]
    return owners.ADMIN_FALLBACK_LABEL  # the role was deleted: the task falls to Admin


def _rows(user: User, checklist: Checklist, day: date) -> list[TaskRow]:
    tasks = list(checklist.tasks.select_related("group", "done_by", "checklist__employee"))
    open_tasks = [task for task in tasks if task.done_at is None]
    resolved = owners.owners_many(open_tasks, day) if checklist.state == ChecklistState.OPEN else {}
    tickable = owners.can_tick_many(user, open_tasks, resolved)  # one batch for the panel: no per-row queries
    may_untick = access.can_untick(user) and checklist.event_id is None
    rows: list[TaskRow] = []
    for task in tasks:
        label = _static_label(task)
        if task.pk in resolved and resolved[task.pk].rule == owners.RULE_ADMIN:
            label = owners.ADMIN_FALLBACK_LABEL
        rows.append(
            TaskRow(
                task=task,
                owner_label=label,
                overdue=task.done_at is None and task.due_on < day,
                can_tick=tickable.get(task.pk, False),
                can_untick=may_untick and task.done_at is not None,
            )
        )
    return rows


_PANELS: dict[str, dict[str, str]] = {
    ChecklistKind.ONBOARDING: {"heading": "Ажилд орох жагсаалт", "date_caption": "эхлэх огноо"},
    ChecklistKind.OFFBOARDING: {"heading": "Ажлаас гарах жагсаалт", "date_caption": "сүүлийн ажлын өдөр"},
}


def _panel(
    user: User, kind: str, checklist: Checklist | None, employee: Employee, day: date
) -> dict[str, object] | None:
    """One panel's context, or None when the user sees nothing of it."""
    wording = _PANELS[kind]
    if checklist is None:
        # Only offboarding is started by hand (onboarding starts itself at the hire).
        if kind == ChecklistKind.OFFBOARDING and access.can_start(user):
            if lifecycle.template_for(ChecklistKind.OFFBOARDING, None) is not None:
                return {"kind": kind, **wording, "checklist": None, "can_start": True, "today": day}
        return None
    if not access.can_view(user, checklist, day):
        return None
    rows = _rows(user, checklist, day)
    return {
        "kind": kind,
        **wording,
        "checklist": checklist,
        "rows": rows,
        "total": len(rows),
        "done": sum(1 for row in rows if row.task.done_at is not None),
        "can_start": False,
        "can_cancel": checklist.state == ChecklistState.OPEN and checklist.event_id is None and access.can_cancel(user),
        "today": day,
    }


def section_context(user: User, employee: Employee, day: date) -> dict[str, object]:
    """Context of the employee page's checklist panels: `checklist_panels`, one per kind the user may see.

    Per kind the panel shows the open checklist, else the latest finished one (cancelled ones are hidden). Offboarding
    with none shows a start button to a user who may record a termination, when a template applies; onboarding never
    does. `checklist_visible` is False when there is no panel.
    """
    # One query for every kind: per kind the open checklist first, else the newest finished one.
    chosen: dict[str, Checklist] = {}
    for checklist in (
        Checklist.objects.filter(employee=employee)
        .exclude(state=ChecklistState.CANCELLED)
        .order_by(Case(When(state=ChecklistState.OPEN, then=0), default=1), "-created_at", "-pk")
    ):
        chosen.setdefault(checklist.kind, checklist)
    panels = [
        panel
        for kind in (ChecklistKind.ONBOARDING, ChecklistKind.OFFBOARDING)
        if (panel := _panel(user, kind, chosen.get(kind), employee, day)) is not None
    ]
    return {"checklist_visible": bool(panels), "checklist_panels": panels}


def _back(request: HttpRequest, user: User, employee: Employee) -> HttpResponse:
    """Where a POST returns to: a local `next` address, else the employee's Work tab, else «Миний хуудас»."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=False):
        return redirect(target)
    if access.can_see_employee(user, employee):
        return redirect(reverse("employees:detail", args=[employee.pk]) + "#work")
    return redirect("me")


def _task_for(pk: int) -> ChecklistTask:
    return get_object_or_404(ChecklistTask.objects.select_related("checklist__employee"), pk=pk)


@login_required
@require_POST
def tick(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    task = _task_for(pk)
    if not owners.can_tick(user, task, today()):
        raise Http404
    try:
        lifecycle.tick(task, by=user)
    except lifecycle.ChecklistError as error:
        return HttpResponse(error.message, status=409)
    return _back(request, user, task.checklist.employee)


@login_required
@require_POST
def untick(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    task = _task_for(pk)
    employee = task.checklist.employee
    if not access.can_untick(user) or not access.can_see_employee(user, employee):
        raise Http404
    if not access.can_view(user, task.checklist, today()):
        raise Http404
    try:
        lifecycle.untick(task, by=user)
    except lifecycle.ChecklistError as error:
        return HttpResponse(error.message, status=409)
    return _back(request, user, employee)


@login_required
@require_POST
def cancel(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    checklist = get_object_or_404(Checklist.objects.select_related("employee"), pk=pk)
    if not access.can_cancel(user) or not access.can_view(user, checklist, today()):
        raise Http404
    try:
        lifecycle.cancel(checklist, by=user)
    except lifecycle.ChecklistError as error:
        return HttpResponse(error.message, status=409)
    return _back(request, user, checklist.employee)


@login_required
def mine(request: HttpRequest) -> HttpResponse:
    """The user's own open tasks. Works without an employee record (an Admin has none), unlike «Миний хуудас»."""
    user = _user(request)
    day = today()
    rows = (
        [{"task": task, "overdue": task.due_on < day} for task in owners.my_tasks(user, day)]
        if owners.may_have_tasks(user, day)
        else []
    )
    return render(request, "checklists/mine.html", {"tasks": rows})


@login_required
@require_POST
def start(request: HttpRequest, employee_id: int) -> HttpResponse:
    user = _user(request)
    employee = get_object_or_404(employee_access.visible_employees(user), pk=employee_id)
    if not access.can_start(user):
        raise Http404
    try:
        anchor_day = date.fromisoformat(request.POST.get("anchor_day", ""))
    except ValueError:
        return HttpResponseBadRequest("Сүүлийн ажлын өдрийг оруулна уу.")
    if lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=None, anchor_day=anchor_day, by=user) is None:
        return HttpResponseBadRequest("Ажлаас гарах жагсаалтын загвар байхгүй байна.")
    return _back(request, user, employee)

"""Leave request lifecycle: submit, approve, reject, withdraw (spec 5.3, 5.4).

A request lives in `leave.LeaveRequest`. Only the final approval writes a `leave_assign` row, through
`records.record`, inside the same transaction as the status change, so a refused write leaves the request waiting.
Every action is logged on the employee's activity log and in `LeaveRequestAction`.
"""

from datetime import date

from accounts.models import User
from django.db import transaction
from django.db.models import Q, QuerySet
from employees.models import (
    LEAVE_REQUEST_APPROVED,
    LEAVE_REQUEST_REJECTED,
    LEAVE_REQUEST_STEP_APPROVED,
    LEAVE_REQUEST_WITHDRAWN,
    LEAVE_REQUESTED,
    ActivityEntry,
    ActivityKind,
    Employee,
    EmployeeExt,
)
from macs.models import LeaveTypeRow

from leave.models import (
    ActionKind,
    LeaveRequest,
    LeaveRequestAction,
    LeaveSettings,
    LeaveTypeExt,
    RequestStatus,
    Step,
)
from leave.services import records
from leave.services.approvers import can_act
from leave.services.fmt import fmt_days
from leave.services.records import Check, Draft, LeaveError

NO_STEPS = "Чөлөөний хүсэлтийн батлах шат тохируулаагүй байна."
TYPE_NOT_REQUESTABLE = "Энэ төрлийн чөлөөг ажилтан хүсэлт гаргах боломжгүй."
OVERLAP_WAITING = "Энэ хугацаанд хүлээгдэж буй хүсэлт байна."
NOT_APPROVER = "Танд энэ хүсэлтийг батлах эрх алга."
NOT_REQUESTER = "Зөвхөн өөрийн хүсэлтийг буцаах боломжтой."
DECIDED = "Энэ хүсэлт шийдэгдсэн байна."
STEP_MOVED = "Энэ хүсэлт өөр шатанд шилжсэн байна. Хуудсыг шинэчилнэ үү."
REASON_REQUIRED = "Татгалзсан шалтгаан бичнэ үү."
TOO_LONG = "Тайлбар 200 тэмдэгтээс урт байж болохгүй."
MAX_TEXT = 200  # the note, reason and override columns are 200 characters


def _date(day: date) -> str:
    return day.strftime("%Y-%m-%d")


def _text(leave_type: LeaveTypeRow, start: date, end: date, days: int) -> str:
    """Same wording as records._text, so request lines read like the recorded leave lines."""
    return f"{leave_type} {_date(start)}–{_date(end)} ({fmt_days(days)} ажлын өдөр)"


def _short(text: str) -> str:
    """The text itself, refused when it does not fit the 200-character column."""
    if len(text) > MAX_TEXT:
        raise LeaveError(TOO_LONG)
    return text


def _approval_tag(step: int, override: bool) -> str:
    """Step number and, for an HR override, the word that says so: " (1-р шат) (эрхээр)"."""
    return f" ({step}-р шат)" + (" (эрхээр)" if override else "")


def _log(employee: Employee, by: User, message: str) -> None:
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)


def _lock(employee: Employee) -> None:
    """Hold the employee row so two submits for one person run one at a time (the overlap check needs that)."""
    Employee.objects.select_for_update().get(pk=employee.pk)


def requestable_types() -> QuerySet[LeaveTypeRow]:
    """Active leave types that staff may request. A type without saved settings counts as active and requestable."""
    switched_off = LeaveTypeExt.objects.filter(Q(is_active=False) | Q(staff_may_request=False)).values("pk")
    return LeaveTypeRow.objects.exclude(pk__in=switched_off)


def preview(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date, today: date) -> Check:
    """What the request form shows: HR's checks plus a block on overlap with another waiting request."""
    c = records.check(Draft(employee=employee, leave_type=leave_type, start_date=start, end_date=end), today)
    overlaps = LeaveRequest.objects.filter(
        employee=employee, status=RequestStatus.WAITING, start_date__lte=end, end_date__gte=start
    ).exists()
    if overlaps:
        c.errors.append(OVERLAP_WAITING)
    return c


@transaction.atomic
def submit(
    employee: Employee,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    note: str,
    by: User,
    today: date,
) -> LeaveRequest:
    """Create a waiting request. The steps are copied from the settings now, so later setting changes do not move it."""
    _lock(employee)
    steps = LeaveSettings.get().steps()
    if not steps:
        raise LeaveError(NO_STEPS)
    if not requestable_types().filter(pk=leave_type.pk).exists():
        raise LeaveError(TYPE_NOT_REQUESTABLE)
    c = preview(employee, leave_type, start, end, today)
    if c.errors:
        raise LeaveError(c.errors[0])
    first = steps[0]
    second = steps[1] if len(steps) > 1 else Step(None, False)
    req = LeaveRequest.objects.create(
        employee=employee,
        leave_type=leave_type,
        start_date=start,
        end_date=end,
        working_days=c.working_days,
        note=_short(note.strip()),
        status=RequestStatus.WAITING,
        current_step=1,
        step1_group_id=first.group_id,
        step1_manager=first.manager,
        step2_group_id=second.group_id,
        step2_manager=second.manager,
        step_count=len(steps),
        created_by=by,
    )
    LeaveRequestAction.objects.create(request=req, step=0, action=ActionKind.SUBMITTED, by=by)
    _log(employee, by, f"{LEAVE_REQUESTED}: {_text(leave_type, start, end, c.working_days)}")
    return req


def _locked_waiting(req: LeaveRequest) -> LeaveRequest:
    """The request row, locked, refused when it is no longer waiting."""
    locked = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if locked.status != RequestStatus.WAITING:
        raise LeaveError(DECIDED)
    return locked


@transaction.atomic
def approve(
    req: LeaveRequest, by: User, today: date, override_reason: str = "", expected_step: int | None = None
) -> LeaveRequest:
    """Approve the current step. The last step writes the leave (records.record) and makes the request approved.

    `expected_step` is the step the approver's screen was opened at; when the request has moved on since, the approval
    is refused so one click cannot approve two steps. A LeaveError from the leave write rolls back the whole approval,
    including its log lines.
    """
    locked = _locked_waiting(req)
    if expected_step is not None and expected_step != locked.current_step:
        raise LeaveError(STEP_MOVED)
    may, override = can_act(by, locked, today)
    if not may:
        raise LeaveError(NOT_APPROVER)
    step = locked.current_step
    reason = _short(override_reason.strip())
    LeaveRequestAction.objects.create(
        request=locked, step=step, action=ActionKind.APPROVED, by=by, override=override, reason=reason
    )
    text = _text(locked.leave_type, locked.start_date, locked.end_date, locked.working_days)
    if step < locked.step_count:
        locked.current_step = step + 1
        locked.save()
        _log(locked.employee, by, f"{LEAVE_REQUEST_STEP_APPROVED}: {text}{_approval_tag(step, override)}")
        return locked

    _log(locked.employee, by, f"{LEAVE_REQUEST_APPROVED}: {text}{_approval_tag(step, override)}")
    draft = Draft(
        employee=locked.employee,
        leave_type=locked.leave_type,
        start_date=locked.start_date,
        end_date=locked.end_date,
        note=locked.note,
        override_reason=reason,
    )
    assign = records.record(draft, by, today)
    locked.assign_id = assign.pk
    locked.status = RequestStatus.APPROVED
    locked.save()
    return locked


@transaction.atomic
def reject(req: LeaveRequest, by: User, reason: str, today: date) -> LeaveRequest:
    """Reject at the current step. The reason is required; no leave row is written."""
    locked = _locked_waiting(req)
    may, override = can_act(by, locked, today)
    if not may:
        raise LeaveError(NOT_APPROVER)
    reason = reason.strip()
    if not reason:
        raise LeaveError(REASON_REQUIRED)
    reason = _short(reason)
    LeaveRequestAction.objects.create(
        request=locked, step=locked.current_step, action=ActionKind.REJECTED, by=by, override=override, reason=reason
    )
    locked.status = RequestStatus.REJECTED
    locked.reason = reason
    locked.save()
    text = _text(locked.leave_type, locked.start_date, locked.end_date, locked.working_days)
    _log(locked.employee, by, f"{LEAVE_REQUEST_REJECTED}: {text}. {reason}")
    return locked


@transaction.atomic
def withdraw(req: LeaveRequest, by: User, today: date) -> LeaveRequest:
    """The employee takes back their own waiting request. `today` is accepted to match the other actions."""
    locked = _locked_waiting(req)
    if not EmployeeExt.objects.filter(employee_id=locked.employee_id, user=by).exists():
        raise LeaveError(NOT_REQUESTER)
    LeaveRequestAction.objects.create(request=locked, step=locked.current_step, action=ActionKind.WITHDRAWN, by=by)
    locked.status = RequestStatus.WITHDRAWN
    locked.save()
    text = _text(locked.leave_type, locked.start_date, locked.end_date, locked.working_days)
    _log(locked.employee, by, f"{LEAVE_REQUEST_WITHDRAWN}: {text}")
    return locked

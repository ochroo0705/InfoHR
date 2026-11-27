"""The offboarding checklist for the people picked on a report, request-free: the form's choices, the reading of the
posted reason and anchor day, the start of a checklist for each picked person, and the counts of what happened. The
Django view and the React checklist API both call these, so a rule has one home. Nothing here reads a request or
checks the user's right to start a checklist: the caller checks that first, as the view did."""

import logging
import re
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from checklists import access as checklist_access
from checklists.forms import template_match_choices
from checklists.models import ChecklistKind, ChecklistTemplate
from checklists.services import lifecycle
from employees import listing
from macs.models import Employee

from reports.selection import Picked

logger = logging.getLogger(__name__)

KIND = ChecklistKind.OFFBOARDING.value  # the only kind the pop-up starts; onboarding starts itself at the hire
ANCHOR_MIN = date(1990, 1, 1)  # the earliest anchor day a checklist may take
ANCHOR_MAX = date(2100, 12, 31)
DATE_TEXT_LENGTH = 10  # YYYY-MM-DD, the only date text read
DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # ASCII digits only; week dates and other forms are refused
OUTCOME_LABELS = {
    "started": "Эхэлсэн",
    "already_open": "Нээлттэй байсан",
    "no_template": "Загвар алга",
    "not_allowed": "Харах эрх алга",
    "left": "Ажлаас гарсан",
    "error": "Алдаа гарлаа",
}
MSG_KIND = "Энд зөвхөн «Ажлаас гарах» жагсаалт эхлүүлнэ."
MSG_DATE = "Огноог 2026-11-07 хэлбэрээр оруулна уу."
MSG_RANGE = f"Огноо {ANCHOR_MIN.isoformat()}-ээс {ANCHOR_MAX.isoformat()} хооронд байх ёстой."
MSG_REASON = "Шалтгаан буруу байна. Жагсаалтаас сонгоно уу."


@dataclass(frozen=True)
class ChecklistForm:
    """What the pop-up shows before anything is started."""

    reasons: list[tuple[str, str]]  # (value, name) of the reasons some active template lists
    template_missing: bool  # no active offboarding template exists
    anchor_min: str  # ISO date
    anchor_max: str  # ISO date
    today: str  # ISO date: the anchor day the form starts on


@dataclass(frozen=True)
class Values:
    """The checklist fields as the user left them. The date is kept as typed, for showing again."""

    reason: str
    anchor_day: str


@dataclass(frozen=True)
class Outcome:
    """What happened for one picked person. `employee` is None only when the person could not be read back."""

    pk: int
    employee: Employee | None
    outcome: str


@dataclass(frozen=True)
class ChecklistResult:
    """The counts and the per-person rows of a start. `rows` are (code or id text, full name, outcome label)."""

    counts: dict[str, int]  # every key of OUTCOME_LABELS
    rows: list[tuple[str, str, str]]
    dropped: int  # posted ids the user may not act on


def _reason_choices(kind: str) -> list[tuple[str, str]]:
    """The reasons that some active template of `kind` lists, with their names (value = the text a template stores)."""
    listed: set[str] = set()
    for template in ChecklistTemplate.objects.filter(kind=kind, active=True):
        listed.update(str(reason) for reason in template.reasons or [])
    return [(value, label) for value, label in template_match_choices(kind) if value in listed]


def form_model(today: date) -> ChecklistForm:
    """The pop-up's choices for today: the offboarding reasons some active template lists, and whether no active
    offboarding template exists at all."""
    return ChecklistForm(
        reasons=_reason_choices(KIND),
        template_missing=not ChecklistTemplate.objects.filter(kind=KIND, active=True).exists(),
        anchor_min=ANCHOR_MIN.isoformat(),
        anchor_max=ANCHOR_MAX.isoformat(),
        today=today.isoformat(),
    )


def _anchor_day(text: str) -> date:
    """A calendar day written as YYYY-MM-DD with ASCII digits. Raises ValueError for any other text."""
    if DATE_TEXT.fullmatch(text) is None:
        raise ValueError(text)
    return date.fromisoformat(text)


def read_values(reason: str, anchor_day: str) -> tuple[Values, date | None, list[str]]:
    """The posted reason and anchor day, checked. Returns the values, the anchor day (None when not valid) and the
    errors. The kind is not read here: the caller refuses any kind other than KIND before it calls this."""
    errors: list[str] = []
    if reason and reason not in {value for value, _ in _reason_choices(KIND)}:
        errors.append(MSG_REASON)
    anchor: date | None = None
    try:
        anchor = _anchor_day(anchor_day)
    except ValueError:
        errors.append(MSG_DATE)
    else:
        if not ANCHOR_MIN <= anchor <= ANCHOR_MAX:
            errors.append(MSG_RANGE)
            anchor = None
    return Values(reason=reason, anchor_day=anchor_day[:DATE_TEXT_LENGTH]), anchor, errors


def _outcome(user: User, employee: Employee, values: Values, anchor_day: date, today: date) -> str:
    """The outcome for one person. Checked in this order: a person who has left gets no checklist even if one is
    open; an open checklist of the kind is left as it is (its day and task dates never move); else one is started."""
    if not checklist_access.can_see_employee(user, employee):
        return "not_allowed"
    if listing.row_for(employee, today).state == "left":
        return "left"
    if lifecycle.open_checklist(employee, KIND) is not None:
        return "already_open"
    started = lifecycle.start(employee, KIND, reason=values.reason or None, anchor_day=anchor_day, by=user)
    return "no_template" if started is None else "started"


def start_each(user: User, picked: Picked, values: Values, anchor_day: date, today: date) -> list[Outcome]:
    """Check and start each picked person, one after another. A refusal or an unexpected error for one person is
    that person's outcome and never stops the others. The start itself writes the activity entry and the log.
    Every picked id gets one outcome, so the counts add up to the picked count."""
    employees = Employee.objects.in_bulk(picked.ids)
    outcomes: list[Outcome] = []
    for pk in picked.ids:
        employee = employees.get(pk)
        if employee is None:
            outcomes.append(Outcome(pk, None, "not_allowed"))  # picked, but not readable now: never silently dropped
            continue
        try:
            outcome = _outcome(user, employee, values, anchor_day, today)
        except Exception:  # one person's failure is reported on their line; the rest still run
            logger.exception("Checklist start failed for employee %s", pk)
            outcome = "error"
        outcomes.append(Outcome(pk, employee, outcome))
    return outcomes


def result_of(outcomes: list[Outcome], dropped: int) -> ChecklistResult:
    """The counts of each outcome and one row per picked person, in the order they were started."""
    counts = {name: sum(1 for item in outcomes if item.outcome == name) for name in OUTCOME_LABELS}
    rows = [
        (
            (item.employee.code if item.employee else None) or str(item.pk),
            item.employee.full_name if item.employee else "",
            OUTCOME_LABELS[item.outcome],
        )
        for item in outcomes
    ]
    return ChecklistResult(counts=counts, rows=rows, dropped=dropped)

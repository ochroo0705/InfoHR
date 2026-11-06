"""Shared test helpers for the assistant: hiring one employee with a fresh register number, and putting that employee
into the states the employee entries need (long leave, left, a scheduled change)."""

import difflib
import itertools
import re
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

from accounts.models import User
from checklists.models import ChecklistTemplate
from django.utils import timezone
from employees.models import Employee, EventType
from employees.services import events, history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import FiredReason
from recruitment.models import Candidate, Vacancy
from recruitment.services import pipeline

from assistant.entries import HelpEntry
from assistant.evalcheck import expected_pairs
from assistant.evalset import ActionCase, TableCase
from assistant.plan import Part, Plan
from assistant.providers import Choice

_REGISTERS = itertools.count(1)

# A Mongolian letter next to a label means the label is part of a longer word («Ажил» inside «Ажилтнууд»).
_CYRILLIC = "А-Яа-яЁёӨөҮү"


def on_screen(label: str, body: str) -> bool:
    """True when the label is visible text in the body as a whole word (not inside a longer Mongolian word).
    Tags and attributes are removed first, so an aria-label or title does not count as the button's text."""
    text = re.sub(r"<[^>]+>", " ", body)
    return re.search(rf"(?<![{_CYRILLIC}]){re.escape(label)}(?![{_CYRILLIC}])", text) is not None


def open_vacancy(actor: User, *, manager: Employee | None = None) -> Vacancy:
    """An open vacancy for the Нягтлан position in Санхүү (the position and department `hire_one` uses)."""
    return Vacancy.objects.create(
        title="Нягтлан",
        position=macs_writes.save_position("Нягтлан"),
        department=macs_writes.save_department("Санхүү"),
        hiring_manager=manager,
        created_by=actor,
    )


def new_candidate(actor: User, vacancy: Vacancy) -> Candidate:
    """A candidate in the first stage of the vacancy."""
    return pipeline.add_candidate(vacancy, by=actor, surname="Дорж", given_name="Бат")


def hire_one(actor: User, *, salary: Decimal | None = Decimal("2500000"), department: str = "Санхүү") -> Employee:
    """A hired employee (onboarding not done, no login) with a register number no earlier call used. `salary=None`
    hires without a salary row, so the salary tab offers «Цалин тогтоох»."""
    n = next(_REGISTERS)
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department(department),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(hire_values(f"УБ{n:08d}"), {}, start=date(2026, 1, 5), job=job, salary=salary, by=actor)


def on_long_leave(actor: User, person: Employee) -> None:
    """An unpaid long leave from 2026-02-01: the person is in the long_leave state today."""
    events.record(
        person,
        type=EventType.LEAVE_START,
        effective=date(2026, 2, 1),
        changes={},
        salary=None,
        reason="unpaid",
        note="",
        by=actor,
    )


def left(actor: User, person: Employee) -> None:
    """Terminated on 2026-03-01: the person is in the left state today. The offboarding checklist templates are
    switched off first, as the employees event tests do, so the termination is not held by the gate."""
    ChecklistTemplate.objects.update(active=False)
    reason = FiredReason.objects.get_or_create(name="Өөрийн хүсэлтээр")[0]
    events.record(
        person,
        type=EventType.TERMINATION,
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=reason,
    )


def scheduled_transfer(actor: User, person: Employee) -> None:
    """A position change 30 days from today: a scheduled change, which the Ажил tab offers to cancel."""
    position = macs_writes.save_position("Ахлах нягтлан")
    events.record(
        person,
        type=EventType.TRANSFER,
        effective=timezone.localdate() + timedelta(days=30),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )


def scheduled_salary_change(actor: User, person: Employee) -> None:
    """A salary change 45 days from today: a scheduled salary change, which the salary tab offers to cancel."""
    events.record(
        person,
        type=EventType.SALARY_CHANGE,
        effective=timezone.localdate() + timedelta(days=45),
        changes={},
        salary=Decimal("2700000"),
        reason="",
        note="",
        by=actor,
    )


def plan_from_choice(choice: Choice) -> Plan:
    """A plan that only answers with a help entry: what a fake provider's choose() says, as the plan shape."""
    return Plan(
        tool="entry" if choice.entry else "none",
        entry=choice.entry,
        also=choice.also,
        lead=choice.lead,
        parts=(),
        unmapped=(),
        want="list",
        chart_kind="",
        chart_by="",
    )


def fake_plan(
    provider: Any,
    question: str,
    entries: Sequence[HelpEntry],
    refusals: Any = (),
    table_examples: Any = (),
    field_hints: Any = (),
) -> Plan:
    """The plan() of a fake provider: its `table` attribute (a Plan) when it has one, else its choose() as a plan.
    `table_examples` and `field_hints` are accepted as plan() takes them; the fakes do not read them."""
    table = getattr(provider, "table", None)
    if isinstance(table, Plan):
        return table
    return plan_from_choice(provider.choose(question, entries, refusals))


# The lookup rows the draft table cases name (evalset.TABLE_CASES), so that their names resolve in a test database.
EVAL_DEPARTMENTS = ("Санхүү", "IT", "Худалдан авалт (Төв)", "Худалдан авалт (Баруун)")
EVAL_POSITIONS = ("Програмист",)


def seed_eval_rows() -> None:
    """Creates the department and position rows the draft table cases name. Call once per test."""
    for name in EVAL_DEPARTMENTS:
        macs_writes.save_department(name)
    for name in EVAL_POSITIONS:
        macs_writes.save_position(name)


# Extra parts a fake gives for a draft case, beyond its expected query: what a model might add (a salary the role may
# not use, a word that names no row, an ambiguous phrase).
_EXTRA_PARTS: dict[str, tuple[Part, ...]] = {
    "цалин 2 саяас дээш хүмүүс": (Part(param="salary_from", value="2000000"),),
    "худалдан авалтын хүмүүс": (Part(param="department", value="худалдан авалтын"),),
    "хөгжлийн бэрхшээлтэй эмэгтэйчүүд": (Part(param="disability", value="yes"),),
}


def table_plan_for(case: TableCase, today: date) -> Plan:
    """A perfect staff-table plan for a draft case: its expected query as parts, plus the case's extra parts. A
    follow-up case leaves out the filters its earlier query already holds (the code keeps those). A chart case asks
    for its chart."""
    before = dict(parse_qsl(case.previous))
    parts = tuple(
        Part(param=param, value=value)
        for param, value, _ in expected_pairs(case.expected, today)
        if before.get(param) != value
    )
    kind, _, by = case.chart.partition(":")
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=(*parts, *_EXTRA_PARTS.get(case.question, ())),
        unmapped=(),
        want="chart" if case.chart else "list",
        chart_kind=kind,
        chart_by=by,
    )


def action_plan_for(case: ActionCase) -> Plan:
    """A perfect plan for an action case: its tool and field. A leave case gets no dates or type here (a fake that
    needs them builds its own plan)."""
    return Plan(
        tool=case.tool,
        entry="",
        also="",
        lead="",
        parts=(),
        unmapped=(),
        want="list",
        chart_kind="",
        chart_by="",
        field=case.field,
    )


def drop_narrowing(monkeypatch: Any) -> None:
    """Passes every help entry to the plan call, as the fakes need the whole role list to know the role. The narrowing
    itself is tested on its own (test_eval_table.py)."""
    from assistant.management.commands import assistant_eval

    monkeypatch.setattr(assistant_eval, "narrow_entries", lambda question, entries, limit=15: list(entries))


def too_close_pairs(questions: Iterable[str], examples: Iterable[str], threshold: float = 0.8) -> list[tuple[str, str]]:
    """The (question, example) pairs at least `threshold` alike: a test sentence that copies an example."""
    pool = list(examples)
    return [(q, x) for q in questions for x in pool if difflib.SequenceMatcher(None, q, x).ratio() >= threshold]

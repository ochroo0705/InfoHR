from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.utils import timezone

from employees import access
from employees.models import ActivityEntry, Department, Employee, Event, JobRecord, Position, SalaryRecord
from employees.services import events, history
from employees.services.events import EventError

from .test_access import user_in

PAST = date(2026, 3, 1)


def future() -> date:
    return timezone.localdate() + timedelta(days=30)


def rec(emp: Employee, actor: User, type: str, effective: date, **kw: Any) -> Event:
    args: dict[str, Any] = {"changes": {}, "salary": None, "reason": "", "note": "", "by": actor}
    args.update(kw)
    return events.record(emp, type=type, effective=effective, **args)


def errors_of(emp: Employee, actor: User, type: str, effective: date, **kw: Any) -> dict[str, str]:
    with pytest.raises(EventError) as exc:
        rec(emp, actor, type, effective, **kw)
    return exc.value.errors


def job_at(emp: Employee, day: date) -> JobRecord:
    job = history.job_on(emp, day)
    assert job is not None
    return job


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


@pytest.mark.parametrize("when", ["today", "past", "future"])
def test_promotion_any_date_with_salary(hired: Employee, actor: User, lead: Position, when: str) -> None:
    day = {"today": timezone.localdate(), "past": PAST, "future": future()}[when]
    ev = rec(hired, actor, "promotion", day, changes={"position": lead}, salary=Decimal("3000000"))
    assert job_at(hired, day).position == lead and job_at(hired, day).event == ev
    salary = history.salary_on(hired, day)
    assert salary is not None and salary.base_salary == Decimal("3000000.00") and salary.event == ev
    assert ev.status(timezone.localdate()) == ("scheduled" if when == "future" else "effective")
    msgs = ActivityEntry.objects.filter(employee=hired, message__startswith="Дэвшүүлсэн")
    assert msgs.count() == 2
    assert (" (өнгөрсөн огноогоор)" in msgs[0].message) == (when == "past")
    job_entry = msgs.get(sensitive=False)
    assert job_entry.changes == [{"field": "Албан тушаал", "old": "Нягтлан", "new": "Ахлах нягтлан"}]
    sal_entry = msgs.get(sensitive=True)
    assert sal_entry.changes == [{"field": "Үндсэн цалин", "old": "2500000.00", "new": "3000000"}]
    assert "3000000" not in job_entry.message


def test_status_is_derived_from_date(hired: Employee, actor: User, lead: Position) -> None:
    ev = rec(hired, actor, "promotion", date(2026, 6, 1), changes={"position": lead})
    assert ev.status(date(2026, 5, 31)) == "scheduled"
    assert ev.status(date(2026, 6, 1)) == "effective"


def test_transfer_and_note_not_in_log(hired: Employee, actor: User) -> None:
    dept = Department.objects.create(name="Хүний нөөц")
    rec(hired, actor, "transfer", PAST, changes={"department": dept}, note="нууц тайлбар")
    entry = ActivityEntry.objects.get(employee=hired, message__startswith="Шилжүүлсэн")
    assert "нууц" not in entry.message and entry.message.startswith("Шилжүүлсэн · 2026-03-01-нээс")
    assert job_at(hired, PAST).note == "нууц тайлбар"


def test_transfer_needs_a_difference(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    errs = errors_of(hired, actor, "transfer", PAST, changes={"department": job_values["department"]})
    assert "__all__" in errs


def test_promotion_needs_position_change(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    dept = Department.objects.create(name="Хүний нөөц")
    assert "position" in errors_of(hired, actor, "promotion", PAST, changes={"department": dept})


def test_demotion_needs_reason(hired: Employee, actor: User, lead: Position) -> None:
    assert "reason" in errors_of(hired, actor, "demotion", PAST, changes={"position": lead})
    rec(hired, actor, "demotion", PAST, changes={"position": lead}, reason="Гүйцэтгэл")
    entry = ActivityEntry.objects.get(employee=hired, message__startswith="Бууруулсан")
    assert entry.message.endswith(". Гүйцэтгэл")


def test_disallowed_field_refused(hired: Employee, actor: User, lead: Position) -> None:
    assert "status" in errors_of(hired, actor, "promotion", PAST, changes={"position": lead, "status": "left"})


def test_salary_change(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "salary_change", PAST, salary=Decimal("2800000"))
    assert not ev.job_records.exists() and ev.salary_records.count() == 1
    (entry,) = ActivityEntry.objects.filter(employee=hired, message__startswith="Цалин өөрчилсөн")
    assert entry.sensitive


def test_salary_change_rules(hired: Employee, actor: User) -> None:
    assert "salary" in errors_of(hired, actor, "salary_change", PAST)
    assert "salary" in errors_of(hired, actor, "salary_change", PAST, salary=Decimal("2500000"))


def test_salary_refused_for_other_types(hired: Employee, actor: User) -> None:
    assert "salary" in errors_of(hired, actor, "termination", PAST, reason="death", salary=Decimal("1"))


def test_contract(hired: Employee, actor: User) -> None:
    ch = {"contract_type": "fixed_term", "contract_start": date(2026, 6, 1), "contract_end": date(2027, 6, 1)}
    rec(hired, actor, "contract", future(), changes=ch)
    assert job_at(hired, future()).contract_end == date(2027, 6, 1)
    bad = {"contract_start": date(2026, 6, 1), "contract_end": date(2026, 5, 1)}
    assert "contract_end" in errors_of(hired, actor, "contract", PAST, changes=bad)
    assert "__all__" in errors_of(hired, actor, "contract", PAST, changes={"contract_type": "open_ended"})


def test_leave_cycle(hired: Employee, actor: User) -> None:
    assert "reason" in errors_of(hired, actor, "leave_start", PAST, reason="bogus")
    assert "__all__" in errors_of(hired, actor, "leave_return", PAST)
    rec(hired, actor, "leave_start", PAST, reason="maternity")
    assert job_at(hired, PAST).status == "long_leave"
    assert "__all__" in errors_of(hired, actor, "leave_start", date(2026, 4, 1), reason="unpaid")
    rec(hired, actor, "leave_return", date(2026, 5, 1))
    assert job_at(hired, date(2026, 5, 1)).status == "active"
    entry = ActivityEntry.objects.get(employee=hired, message__startswith="Урт чөлөө эхэлсэн")
    assert entry.message.endswith(". Жирэмсний амралт")


def test_termination_and_rehire(hired: Employee, actor: User, lead: Position) -> None:
    assert "reason" in errors_of(hired, actor, "termination", PAST, reason="")
    assert "__all__" in errors_of(hired, actor, "rehire", PAST)
    rec(hired, actor, "termination", PAST, reason="resignation")
    assert job_at(hired, PAST).status == "left"
    assert "__all__" in errors_of(hired, actor, "termination", date(2026, 4, 1), reason="death")
    rec(hired, actor, "rehire", date(2026, 5, 1), changes={"position": lead}, salary=Decimal("3100000"))
    job = job_at(hired, date(2026, 5, 1))
    assert job.status == "active" and job.position == lead and job.change_type == "rehire"


def test_no_history_on_date_refused(hired: Employee, actor: User, lead: Position) -> None:
    assert "effective" in errors_of(hired, actor, "promotion", date(2025, 1, 1), changes={"position": lead})


def test_failure_leaves_no_event(hired: Employee, actor: User, lead: Position) -> None:
    rec(hired, actor, "promotion", PAST, changes={"position": lead})
    before = Event.objects.count()
    other = Position.objects.create(name="Захирал")
    errors_of(hired, actor, "promotion", PAST, changes={"position": other})  # period already starts there
    assert Event.objects.count() == before


def test_cancel_scheduled_merges_back(hired: Employee, actor: User, lead: Position) -> None:
    ev = rec(hired, actor, "promotion", future(), changes={"position": lead}, salary=Decimal("3000000"))
    events.cancel(ev, reason="Буруу бүртгэл", by=actor)
    ev.refresh_from_db()
    assert ev.status(timezone.localdate()) == "cancelled" and ev.cancelled_by == actor
    (job,) = JobRecord.objects.filter(employee=hired)
    (sal,) = SalaryRecord.objects.filter(employee=hired)
    assert job.period.upper is None and sal.period.upper is None and sal.base_salary == Decimal("2500000.00")
    entries = ActivityEntry.objects.filter(employee=hired, message__startswith="Цуцалсан")
    assert entries.count() == 2
    assert not entries.get(sensitive=False).changes
    assert "3000000" not in str(entries.get(sensitive=False).__dict__)
    assert entries.get(sensitive=True).changes[0]["old"] == "3000000.00"


def test_cancel_salary_only_writes_only_sensitive_entry(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "salary_change", future(), salary=Decimal("2900000"))
    events.cancel(ev, reason="x", by=actor)
    (entry,) = ActivityEntry.objects.filter(employee=hired, message__startswith="Цуцалсан")
    assert entry.sensitive


def test_cancel_refusals(hired: Employee, actor: User, lead: Position) -> None:
    done = rec(hired, actor, "promotion", PAST, changes={"position": lead})
    assert "__all__" in _cancel_errors(done, actor, "reason")
    ev = rec(hired, actor, "transfer", future(), changes={"department": Department.objects.create(name="Х")})
    assert "reason" in _cancel_errors(ev, actor, "  ")
    events.cancel(ev, reason="ok", by=actor)
    assert "__all__" in _cancel_errors(ev, actor, "again")


def _cancel_errors(ev: Event, actor: User, reason: str) -> dict[str, str]:
    with pytest.raises(EventError) as exc:
        events.cancel(ev, reason=reason, by=actor)
    return exc.value.errors


def test_can_record_event_matrix(db: None) -> None:
    hr, acc, admin = user_in("HR", "hr"), user_in("Accountant", "acc"), user_in("Admin", "adm")
    assert access.can_record_event(hr, "transfer") and not access.can_record_event(hr, "salary_change")
    assert not access.can_record_event(acc, "transfer") and access.can_record_event(acc, "salary_change")
    assert access.can_record_event(admin, "transfer") and access.can_record_event(admin, "salary_change")


def test_can_cancel_matrix(hired: Employee, actor: User, lead: Position) -> None:
    job_only = rec(hired, actor, "promotion", future(), changes={"position": lead})
    salary_only = rec(hired, actor, "salary_change", future() + timedelta(days=1), salary=Decimal("2900000"))
    dept = Department.objects.create(name="Х")
    mixed = rec(
        hired, actor, "transfer", future() + timedelta(days=2), changes={"department": dept}, salary=Decimal("3000000")
    )
    hr, acc, admin = user_in("HR", "hr"), user_in("Accountant", "acc"), user_in("Admin", "adm")
    assert [access.can_cancel(u, e) for u in (hr, acc, admin) for e in (job_only, salary_only, mixed)] == [
        True,
        False,
        False,
        False,
        True,
        False,
        True,
        True,
        True,
    ]


PREP = date(2026, 2, 1)


def _kwargs(type: str, lead: Position) -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {
        "transfer": {"changes": {"department": Department.objects.get_or_create(name="Х")[0]}},
        "promotion": {"changes": {"position": lead}},
        "demotion": {"changes": {"position": lead}, "reason": "Гүйцэтгэл"},
        "salary_change": {"salary": Decimal("2800000")},
        "contract": {"changes": {"contract_type": "fixed_term", "contract_end": date(2030, 1, 1)}},
        "leave_start": {"reason": "unpaid"},
        "leave_return": {},
        "termination": {"reason": "resignation"},
        "rehire": {"changes": {"position": lead}, "salary": Decimal("3100000")},
    }
    return table[type]


@pytest.mark.parametrize("when", ["today", "past", "future"])
@pytest.mark.parametrize(
    "type",
    [
        "transfer",
        "promotion",
        "demotion",
        "salary_change",
        "contract",
        "leave_start",
        "leave_return",
        "termination",
        "rehire",
    ],
)
def test_every_type_every_date(hired: Employee, actor: User, lead: Position, type: str, when: str) -> None:
    if type == "leave_return":
        rec(hired, actor, "leave_start", PREP, reason="unpaid")
    if type == "rehire":
        rec(hired, actor, "termination", PREP, reason="resignation")
    today = timezone.localdate()
    day = {"today": today, "past": PAST, "future": future()}[when]
    ev = rec(hired, actor, type, day, **_kwargs(type, lead))
    assert ev.status(today) == ("scheduled" if when == "future" else "effective")
    for r in ev.job_records.all():
        assert r.period.lower == day and r.period.upper is None
    for s in ev.salary_records.all():
        assert s.period.lower == day and s.period.upper is None
    assert ev.job_records.exists() != (type == "salary_change")
    assert ev.salary_records.exists() == (type in ("salary_change", "rehire"))
    if type != "salary_change":
        previous = history.job_on(hired, day - timedelta(days=1))
        assert previous is not None and previous.period.upper == day


def test_rehire_checks_contract_dates(hired: Employee, actor: User) -> None:
    rec(hired, actor, "termination", PREP, reason="resignation")
    bad = {"contract_start": date(2026, 6, 1), "contract_end": date(2026, 5, 1)}
    assert "contract_end" in errors_of(hired, actor, "rehire", PAST, changes=bad)


def test_status_messages_are_combined(hired: Employee, actor: User) -> None:
    rec(hired, actor, "termination", PREP, reason="resignation")
    errs = errors_of(hired, actor, "termination", PAST, reason="bogus")
    assert "reason" in errs and "__all__" in errs
    errs = errors_of(hired, actor, "transfer", PAST)
    assert "__all__" in errs


def test_salary_failure_rolls_back_job_part(
    hired: Employee, actor: User, lead: Position, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise history.HistoryError("boom")

    monkeypatch.setattr(history, "change_salary", boom)
    counts = (
        Event.objects.count(),
        JobRecord.objects.count(),
        SalaryRecord.objects.count(),
        ActivityEntry.objects.count(),
    )
    assert errors_of(hired, actor, "promotion", PAST, changes={"position": lead}, salary=Decimal("3")) == {
        "__all__": "boom"
    }
    assert counts == (
        Event.objects.count(),
        JobRecord.objects.count(),
        SalaryRecord.objects.count(),
        ActivityEntry.objects.count(),
    )
    assert JobRecord.objects.get(employee=hired).period.upper is None


def test_invalid_termination_reason(hired: Employee, actor: User) -> None:
    assert "reason" in errors_of(hired, actor, "termination", PAST, reason="bogus")


def test_demotion_unchanged_position_refused(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    errs = errors_of(hired, actor, "demotion", PAST, changes={"position": job_values["position"]}, reason="x")
    assert "position" in errs


def test_salary_cancel_message_has_no_amount(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "salary_change", future(), salary=Decimal("2912345"))
    events.cancel(ev, reason="x", by=actor)
    entries = ActivityEntry.objects.filter(employee=hired, message__startswith="Цуцалсан")
    assert [e.sensitive for e in entries] == [True] and "2912345" not in entries[0].message


def test_salary_on_other_type_leaves_nothing(hired: Employee, actor: User) -> None:
    counts = (
        Event.objects.count(),
        JobRecord.objects.count(),
        SalaryRecord.objects.count(),
        ActivityEntry.objects.count(),
    )
    assert "salary" in errors_of(hired, actor, "leave_start", PAST, reason="unpaid", salary=Decimal("1"))
    assert counts == (
        Event.objects.count(),
        JobRecord.objects.count(),
        SalaryRecord.objects.count(),
        ActivityEntry.objects.count(),
    )


def _days(n: int) -> date:
    return timezone.localdate() + timedelta(days=n)


def test_cancel_refused_while_later_row_exists(hired: Employee, actor: User, lead: Position) -> None:
    dept = Department.objects.create(name="Х")
    transfer = rec(hired, actor, "transfer", _days(10), changes={"department": dept})
    promo = rec(hired, actor, "promotion", _days(20), changes={"position": lead})
    errs = _cancel_errors(transfer, actor, "x")
    assert "__all__" in errs
    assert JobRecord.objects.filter(employee=hired).count() == 3
    events.cancel(promo, reason="x", by=actor)
    events.cancel(transfer, reason="x", by=actor)
    (job,) = JobRecord.objects.filter(employee=hired)
    assert job.period.upper is None and job.department != dept


def test_cancel_termination_refused_when_rehire_scheduled(hired: Employee, actor: User, lead: Position) -> None:
    term = rec(hired, actor, "termination", _days(10), reason="resignation")
    rec(hired, actor, "rehire", _days(20), changes={"position": lead})
    assert "__all__" in _cancel_errors(term, actor, "x")
    assert JobRecord.objects.filter(employee=hired).count() == 3


def test_record_before_later_job_row_refused(hired: Employee, actor: User, lead: Position) -> None:
    rec(hired, actor, "promotion", _days(60), changes={"position": lead})
    dept = Department.objects.create(name="Х")
    before = Event.objects.count()
    assert "__all__" in errors_of(hired, actor, "transfer", _days(10), changes={"department": dept})
    assert Event.objects.count() == before


def test_termination_before_later_job_row_refused(hired: Employee, actor: User) -> None:
    dept = Department.objects.create(name="Х")
    rec(hired, actor, "transfer", _days(60), changes={"department": dept})
    assert "__all__" in errors_of(hired, actor, "termination", _days(10), reason="resignation")


def test_termination_ignores_later_salary_row(hired: Employee, actor: User) -> None:
    rec(hired, actor, "salary_change", _days(60), salary=Decimal("2900000"))
    rec(hired, actor, "termination", _days(10), reason="resignation")


def test_salary_event_before_later_salary_row_refused(hired: Employee, actor: User) -> None:
    rec(hired, actor, "salary_change", _days(60), salary=Decimal("2900000"))
    assert "__all__" in errors_of(hired, actor, "salary_change", _days(10), salary=Decimal("2700000"))


def test_backdated_event_without_later_rows_allowed(hired: Employee, actor: User, lead: Position) -> None:
    rec(hired, actor, "promotion", PAST, changes={"position": lead})


def test_leave_start_stores_expected_return_and_logs_it(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "leave_start", PAST, reason="childcare", expected_return=PAST + timedelta(days=300))
    assert ev.expected_return == PAST + timedelta(days=300)
    assert events.leave_until(hired, PAST + timedelta(days=1)) == ev.expected_return
    assert f"{ev.expected_return:%Y-%m-%d} хүртэл" in ActivityEntry.objects.filter(employee=hired).latest("id").message


def test_expected_return_rules(hired: Employee, actor: User, lead: Position) -> None:
    assert "expected_return" in errors_of(hired, actor, "leave_start", PAST, reason="unpaid", expected_return=PAST)
    errs = errors_of(hired, actor, "promotion", PAST, changes={"position": lead}, expected_return=future())
    assert "expected_return" in errs
    rec(hired, actor, "leave_start", PAST, reason="unpaid")  # optional
    assert events.leave_until(hired, PAST + timedelta(days=1)) is None

from datetime import date

from django.utils import timezone

from employees.models import Employee, Event, EventType

PAST = date(2026, 3, 1)
FUTURE = date(2030, 1, 1)


def make_event(emp: Employee, effective: date, **kw: object) -> Event:
    return Event.objects.create(employee=emp, type=EventType.PROMOTION, effective=effective, **kw)


def test_status_awaiting_signature_when_not_applied(hired: Employee) -> None:
    ev = make_event(hired, PAST)
    assert ev.applied_at is None
    assert ev.status(timezone.localdate()) == "awaiting_signature"


def test_status_applied_past_is_effective(hired: Employee) -> None:
    ev = make_event(hired, PAST, applied_at=timezone.now())
    assert ev.status(timezone.localdate()) == "effective"


def test_status_applied_future_is_scheduled(hired: Employee) -> None:
    ev = make_event(hired, FUTURE, applied_at=timezone.now())
    assert ev.status(timezone.localdate()) == "scheduled"


def test_cancelled_beats_awaiting(hired: Employee) -> None:
    ev = make_event(hired, FUTURE, cancelled_at=timezone.now())
    assert ev.applied_at is None
    assert ev.status(timezone.localdate()) == "cancelled"


def test_applied_queryset_excludes_waiting(hired: Employee) -> None:
    applied = make_event(hired, PAST, applied_at=timezone.now())
    make_event(hired, PAST)
    assert list(hired.events.applied()) == [applied]
    assert list(Event.objects.applied().filter(employee=hired)) == [applied]

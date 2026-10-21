import logging
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from employees import daily_sync
from employees.daily_sync import DailySyncMiddleware
from employees.models import DailySync

TODAY = date(2026, 10, 16)
TOMORROW = date(2026, 10, 17)


@pytest.fixture(autouse=True)
def fresh_process_cache() -> None:
    """The middleware keeps the last synced day in a module variable; each test starts without it."""
    daily_sync._synced_day = None
    daily_sync._failed_at = None


@pytest.fixture
def clock(monkeypatch: Any) -> dict[str, date]:
    state = {"today": TODAY}
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: state["today"])
    return state


@pytest.fixture
def sync_calls(monkeypatch: Any) -> list[date]:
    calls: list[date] = []

    def fake_sync(today: date) -> int:
        calls.append(today)
        return 0

    monkeypatch.setattr(daily_sync, "sync_all_employees", fake_sync)
    return calls


def _middleware() -> DailySyncMiddleware:
    return DailySyncMiddleware(lambda request: HttpResponse("ok"))


def _request(user: Any, path: str = "/employees/") -> HttpRequest:
    request = RequestFactory().get(path)
    request.user = user
    return request


@pytest.mark.django_db
def test_first_request_of_day_runs_sync_once_and_records_date(
    actor: User, clock: dict[str, date], sync_calls: list[date]
) -> None:
    response = _middleware()(_request(actor))

    assert response.status_code == 200
    assert sync_calls == [TODAY]
    assert DailySync.objects.get(pk=1).day == TODAY


@pytest.mark.django_db
def test_second_request_same_day_does_not_sync(actor: User, clock: dict[str, date], sync_calls: list[date]) -> None:
    middleware = _middleware()
    middleware(_request(actor))
    middleware(_request(actor))

    assert sync_calls == [TODAY]


@pytest.mark.django_db
def test_request_after_day_change_syncs_again(actor: User, clock: dict[str, date], sync_calls: list[date]) -> None:
    middleware = _middleware()
    middleware(_request(actor))
    clock["today"] = TOMORROW
    middleware(_request(actor))

    assert sync_calls == [TODAY, TOMORROW]
    assert DailySync.objects.get(pk=1).day == TOMORROW


@pytest.mark.django_db
def test_already_recorded_today_by_another_process_is_a_noop(
    actor: User, clock: dict[str, date], sync_calls: list[date], django_assert_num_queries: Any
) -> None:
    DailySync.objects.create(pk=1, day=TODAY)
    middleware = _middleware()

    middleware(_request(actor))
    assert sync_calls == []
    # Later requests in this process use the cached day and do no queries at all.
    with django_assert_num_queries(0):
        middleware(_request(actor))
    assert sync_calls == []


@pytest.mark.django_db
def test_command_runs_sync_and_records_date(clock: dict[str, date], sync_calls: list[date]) -> None:
    call_command("sync_current_jobs")

    assert sync_calls == [TODAY]
    assert DailySync.objects.get(pk=1).day == TODAY


@pytest.mark.django_db
def test_command_runs_even_when_request_already_ran_today(
    actor: User, clock: dict[str, date], sync_calls: list[date]
) -> None:
    _middleware()(_request(actor))
    call_command("sync_current_jobs")

    assert sync_calls == [TODAY, TODAY]


@pytest.mark.django_db
def test_failed_sync_keeps_request_200_logs_and_does_not_record(
    actor: User, clock: dict[str, date], monkeypatch: Any, caplog: Any
) -> None:
    def broken(today: date) -> int:
        raise RuntimeError("MACS unavailable")

    monkeypatch.setattr(daily_sync, "sync_all_employees", broken)

    with caplog.at_level(logging.ERROR, logger="employees.daily_sync"):
        response = _middleware()(_request(actor))

    assert response.status_code == 200
    assert not DailySync.objects.filter(pk=1, day=TODAY).exists()
    assert any("daily sync" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.django_db
def test_failed_sync_is_retried_on_next_request(
    actor: User, clock: dict[str, date], monkeypatch: Any, sync_calls: list[date]
) -> None:
    attempts: list[date] = []

    def flaky(today: date) -> int:
        attempts.append(today)
        if len(attempts) == 1:
            raise RuntimeError("MACS unavailable")
        sync_calls.append(today)
        return 0

    from datetime import datetime, timedelta

    now = {"t": datetime(2026, 10, 16, 9, 0, tzinfo=timezone.get_current_timezone())}
    monkeypatch.setattr(timezone, "now", lambda: now["t"])
    monkeypatch.setattr(daily_sync, "sync_all_employees", flaky)
    _middleware()(_request(actor))
    _middleware()(_request(actor))  # within 10 minutes of the failure: not retried
    assert attempts == [TODAY]
    now["t"] += timedelta(minutes=11)
    _middleware()(_request(actor))

    assert attempts == [TODAY, TODAY]
    assert sync_calls == [TODAY]
    assert DailySync.objects.get(pk=1).day == TODAY


@pytest.mark.django_db
def test_anonymous_request_does_not_run_sync(clock: dict[str, date], sync_calls: list[date]) -> None:
    from django.contrib.auth.models import AnonymousUser

    response = _middleware()(_request(AnonymousUser()))

    assert response.status_code == 200
    assert sync_calls == []
    assert not DailySync.objects.exists()


@pytest.mark.django_db
def test_static_file_request_does_not_run_sync(actor: User, clock: dict[str, date], sync_calls: list[date]) -> None:
    _middleware()(_request(actor, path="/static/app.css"))

    assert sync_calls == []

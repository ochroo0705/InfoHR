"""Daily MACS sync: copies today's job and salary onto every production employee row, so changes
dated in the future reach production on their day. It also adds the current year's automatic leave grant
(leave.services.ledger.ensure_grants) when that switch is on.

Two callers, one code path (run_daily_sync -> sync_all_employees):
- `manage.py sync_current_jobs`, meant to be scheduled daily, always runs;
- DailySyncMiddleware, the first request of a new calendar day, as a safety net when the schedule
  did not run. It runs only for signed-in users and never breaks the request.

The last synced day lives in the `employees_dailysync` table (one row), not in memory, because
several processes may serve requests. A module variable caches it per process so most requests
do no queries at all.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from employees.models import DailySync, Employee
from employees.services import macs_writes

logger = logging.getLogger(__name__)

SINGLETON_PK = 1
# Per process: the day this process has already seen recorded in the database.
_synced_day: date | None = None
# Per process: when the last request-time sync failed. A failing sync is retried at most every RETRY_AFTER,
# not on every request (e.g. migration not applied yet, or one bad row).
_failed_at: datetime | None = None
RETRY_AFTER = timedelta(minutes=10)


def sync_all_employees(today: date) -> int:
    """Run sync_current for every production employee, then add this year's automatic leave grant where the
    switch is on and nothing covers the year (never from a page view). Returns how many rows changed."""
    from leave.services import ledger  # leave imports employees: keep this import local

    changed = 0
    for employee in Employee.objects.filter(ext__isnull=False):
        if macs_writes.sync_current(employee, today):
            changed += 1
        ledger.ensure_grants(employee, today)
    return changed


def run_daily_sync(today: date, *, force: bool = False) -> int | None:
    """Sync and record `today`. Exactly once per day unless `force`.

    The row lock serialises concurrent callers: the second one waits, then re-reads the date and
    skips. The date is recorded in the same transaction as the sync, so a failure rolls back both
    and the sync is retried later. Returns the changed count, or None when skipped.
    """
    global _synced_day
    DailySync.objects.get_or_create(pk=SINGLETON_PK)
    with transaction.atomic():
        row = DailySync.objects.select_for_update().get(pk=SINGLETON_PK)
        if row.day == today and not force:
            _synced_day = today
            return None
        changed = sync_all_employees(today)
        row.day = today
        row.save(update_fields=["day"])
    _synced_day = today
    return changed


def _needs_sync(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    if request.path.startswith(settings.STATIC_URL):
        return False
    if _failed_at is not None and timezone.now() - _failed_at < RETRY_AFTER:
        return False
    return _synced_day != timezone.localdate()


class DailySyncMiddleware:
    """Runs the daily sync on the first signed-in request of a new day. Errors are logged, never raised."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        global _failed_at
        if _needs_sync(request):
            try:
                run_daily_sync(timezone.localdate())
                _failed_at = None
            except Exception:
                _failed_at = timezone.now()
                logger.exception("Daily sync failed; the request continues and the sync is retried in 10 minutes")
        return self.get_response(request)

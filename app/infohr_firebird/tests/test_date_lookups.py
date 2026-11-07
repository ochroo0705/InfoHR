"""Date and datetime lookups on the Firebird clone give the PostgreSQL answers (fix O).

On Firebird dialect 1 the type DATE is a TIMESTAMP, so CAST(x AS DATE) keeps the time part. Every __date
filter, TruncDate and TruncWeek built on it then missed rows later in the day. The rows here are stored as
Ulaanbaatar wall-clock time (USE_TZ is on, the backend stores local time). The expected answers are the
local-day answers PostgreSQL gives: a row at 00:30 on 2026-03-10 in Ulaanbaatar is 2026-03-09 in UTC and must
still count as 2026-03-10.

Each test runs its ORM code in a subprocess in Firebird mode against the module clone (``migrated_clone``),
the same way test_orm_after_plan2.py does.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

DATE_CODE = """
import datetime as dt
import json
import uuid
from zoneinfo import ZoneInfo
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db.models.functions import TruncDate, TruncDay, TruncMonth, TruncQuarter, TruncWeek
User = get_user_model()
UB = ZoneInfo("Asia/Ulaanbaatar")
tag = uuid.uuid4().hex[:6]
ROWS = {
    "a": dt.datetime(2026, 3, 8, 23, 59, 59, tzinfo=UB),
    "b": dt.datetime(2026, 3, 9, 23, 59, 59, tzinfo=UB),
    "c": dt.datetime(2026, 3, 10, 0, 0, 0, tzinfo=UB),
    "d": dt.datetime(2026, 3, 10, 0, 30, 0, tzinfo=UB),
    "e": dt.datetime(2026, 3, 10, 12, 0, 0, tzinfo=UB),
    "f": dt.datetime(2026, 3, 10, 23, 59, 59, tzinfo=UB),
    "g": dt.datetime(2026, 3, 11, 0, 0, 0, tzinfo=UB),
    "h": dt.datetime(2026, 4, 1, 0, 0, 0, tzinfo=UB),
}
for label, when in ROWS.items():
    User.objects.create(username=f"dl{tag}_{label}")
    User.objects.filter(username=f"dl{tag}_{label}").update(last_login=when)
mine = User.objects.filter(username__startswith=f"dl{tag}_")


def labels(queryset):
    return sorted(user.username.rsplit("_", 1)[1] for user in queryset)


def probe(build):
    try:
        return build()
    except Exception as exc:
        return "ERROR " + str(exc).strip().splitlines()[0]


out = {
    "date_eq_10": probe(lambda: labels(mine.filter(last_login__date=dt.date(2026, 3, 10)))),
    "date_eq_09": probe(lambda: labels(mine.filter(last_login__date=dt.date(2026, 3, 9)))),
    "date_range_10": probe(lambda: labels(mine.filter(
        last_login__date__gte=dt.date(2026, 3, 10), last_login__date__lte=dt.date(2026, 3, 10)))),
    "date_range_09_10": probe(lambda: labels(mine.filter(
        last_login__date__gte=dt.date(2026, 3, 9), last_login__date__lt=dt.date(2026, 3, 11)))),
    "trunc_date_eq_10": probe(lambda: labels(mine.annotate(d=TruncDate("last_login")).filter(
        d=dt.date(2026, 3, 10)))),
    "trunc_date_values": probe(lambda: dict(sorted(
        (user.username.rsplit("_", 1)[1], str(user.d))
        for user in mine.annotate(d=TruncDate("last_login"))))),
    "trunc_week_values": probe(lambda: dict(sorted(
        (user.username.rsplit("_", 1)[1], user.w.date().isoformat())
        for user in mine.annotate(w=TruncWeek("last_login"))))),
    "trunc_quarter_values": probe(lambda: dict(sorted(
        (user.username.rsplit("_", 1)[1], user.q.date().isoformat())
        for user in mine.annotate(q=TruncQuarter("last_login"))))),
    "year_2026": probe(lambda: labels(mine.filter(last_login__year=2026))),
    "year_2025": probe(lambda: labels(mine.filter(last_login__year=2025))),
    "month_3": probe(lambda: labels(mine.filter(last_login__month=3))),
    "day_10": probe(lambda: labels(mine.filter(last_login__day=10))),
    "day_9": probe(lambda: labels(mine.filter(last_login__day=9))),
    "week_day_3": probe(lambda: labels(mine.filter(last_login__week_day=3))),
    "week_10": probe(lambda: labels(mine.filter(last_login__week=10))),
    "week_11": probe(lambda: labels(mine.filter(last_login__week=11))),
    "quarter_1": probe(lambda: labels(mine.filter(last_login__quarter=1))),
    "quarter_2": probe(lambda: labels(mine.filter(last_login__quarter=2))),
    "trunc_month_3": probe(lambda: labels(mine.annotate(m=TruncMonth("last_login")).filter(
        m=dt.datetime(2026, 3, 1, 0, 0, 0, tzinfo=UB)))),
    "trunc_week_mon_09": probe(lambda: labels(mine.annotate(w=TruncWeek("last_login")).filter(
        w=dt.datetime(2026, 3, 9, 0, 0, 0, tzinfo=UB)))),
    "trunc_day_mar_10": probe(lambda: labels(mine.annotate(d=TruncDay("last_login")).filter(
        d=dt.datetime(2026, 3, 10, 0, 0, 0, tzinfo=UB)))),
}
print("RESULT " + json.dumps(out))
"""

# The PostgreSQL answers for the rows above (labels a..h, see DATE_CODE). The local day decides, never UTC.
EXPECTED: dict[str, Any] = {
    "date_eq_10": ["c", "d", "e", "f"],
    "date_eq_09": ["b"],
    "date_range_10": ["c", "d", "e", "f"],
    "date_range_09_10": ["b", "c", "d", "e", "f"],
    "trunc_date_eq_10": ["c", "d", "e", "f"],
    "trunc_date_values": {
        "a": "2026-03-08",
        "b": "2026-03-09",
        "c": "2026-03-10",
        "d": "2026-03-10",
        "e": "2026-03-10",
        "f": "2026-03-10",
        "g": "2026-03-11",
        "h": "2026-04-01",
    },
    "year_2026": ["a", "b", "c", "d", "e", "f", "g", "h"],
    "year_2025": [],
    "month_3": ["a", "b", "c", "d", "e", "f", "g"],
    "day_10": ["c", "d", "e", "f"],
    "day_9": ["b"],
    "week_day_3": ["c", "d", "e", "f"],  # 2026-03-10 is a Tuesday (Django week_day 3)
    "week_10": ["a"],  # 2026-03-08 is a Sunday, ISO week 10
    "week_11": ["b", "c", "d", "e", "f", "g"],
    "quarter_1": ["a", "b", "c", "d", "e", "f", "g"],
    "quarter_2": ["h"],
    "trunc_month_3": ["a", "b", "c", "d", "e", "f", "g"],
    "trunc_week_mon_09": ["b", "c", "d", "e", "f", "g"],
    "trunc_day_mar_10": ["c", "d", "e", "f"],
    "trunc_week_values": {
        "a": "2026-03-02",  # 2026-03-08 is a Sunday: its Monday is 2026-03-02
        "b": "2026-03-09",
        "c": "2026-03-09",
        "d": "2026-03-09",
        "e": "2026-03-09",
        "f": "2026-03-09",
        "g": "2026-03-09",
        "h": "2026-03-30",
    },
    "trunc_quarter_values": {
        "a": "2026-01-01",
        "b": "2026-01-01",
        "c": "2026-01-01",
        "d": "2026-01-01",
        "e": "2026-01-01",
        "f": "2026-01-01",
        "g": "2026-01-01",
        "h": "2026-04-01",
    },
}


@pytest.fixture(scope="module")
def date_probe(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(DATE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_date_lookup_matches_local_day(date_probe: dict[str, Any], key: str) -> None:
    assert date_probe[key] == EXPECTED[key], key

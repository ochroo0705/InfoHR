"""Time the main pages and count their SQL queries (scale check, scoping log RK-008).

Run on the seeded scale database (see seed_scale_demo.py), from the repo root:
    MSYS_NO_PATHCONV=1 DJANGO_DB_NAME=info_hr_demo_scale DJANGO_DEBUG=false python scripts/scale_check.py
Prints one line per page, slowest first: milliseconds, queries, status, size, URL.
A query count close to the number of employees means one query per person (an N+1 pattern).
"""

# ruff: noqa: E402  (Django must be set up before the app imports)

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from accounts.models import User
from django.conf import settings
from django.db import connection
from django.test import Client
from employees.models import EmployeeExt
from reports.registry import REPORTS

settings.ALLOWED_HOSTS = ["*"]

FIXED = [
    "/employees/today/",
    "/employees/",
    "/employees/?view=table",
    "/employees/palette/?q=ба",
    "/employees/orders/",
    "/leave/",
    "/leave/calendar/",
    "/leave/balances/",
    "/leave/requests/",
    "/me/",
]


def timed(client: Client, url: str) -> tuple[float, int, int, int]:
    queries = 0

    def count(execute, sql, params, many, context):  # type: ignore[no-untyped-def]
        nonlocal queries
        queries += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count):
        start = time.perf_counter()
        response = client.get(url, follow=True)
        seconds = time.perf_counter() - start
    return seconds, queries, response.status_code, len(response.content) // 1024


def main() -> None:
    client = Client()
    client.force_login(User.objects.get(username="admin"))
    client.get("/employees/today/")  # warm up: the first request of a day runs the daily sync
    # /me/ is the My page: it needs a login linked to an employee record (the admin has none).
    linked = EmployeeExt.objects.filter(user__isnull=False, user__is_active=True).select_related("user").first()
    me_client = Client()
    if linked is not None and linked.user is not None:
        me_client.force_login(linked.user)
    urls = FIXED + [f"/reports/{key}/" for key in REPORTS]
    rows = [(*timed(me_client if url == "/me/" else client, url), url) for url in urls]
    for seconds, queries, status, kb, url in sorted(rows, reverse=True):
        print(f"{seconds * 1000:7.0f} ms {queries:5d} q {status} {kb:5d} KB {url}")


main()

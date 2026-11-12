"""Performance audit: time every read-only page, per role, and count its SQL queries.

Run on a seeded scale database (never on a real one). From the repo root:

    DEMO_DB=info_hr_perf python scripts/demo.py reset
    DJANGO_DB_NAME=info_hr_perf DJANGO_DEBUG=true python app/manage.py seed_scale_demo 300
    MSYS_NO_PATHCONV=1 DJANGO_DB_NAME=info_hr_perf DJANGO_DEBUG=false python scripts/perf_audit.py [--roles admin,hr] [--runs 3]

For each (role, URL): the median of N runs in milliseconds, SQL query count, the largest number of times ONE
query shape repeated (a high number means one query per row, an N+1), status and size. Worst first.
Only GET requests are made, so nothing is written (the first request of the day runs the daily sync).
Times from a dev machine are relative; query counts and the ranking carry over to production.
"""

# ruff: noqa: E402  (Django must be set up before the app imports)

import argparse
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from accounts.models import User
from django.conf import settings
from django.db import connection
from django.test import Client

settings.ALLOWED_HOSTS = ["*"]

ROLES = ["admin", "hr", "director", "accountant", "bold"]
SHAPE = re.compile(r"\b\d+\b|'[^']*'|%s|\$\d+")


def first_id(model_path: str, **filters: object) -> int | None:
    app, name = model_path.split(".")
    from django.apps import apps

    obj = apps.get_model(app, name).objects.filter(**filters).order_by("pk").first()
    return obj.pk if obj else None


def sample_ids() -> dict[str, int | None]:
    """A busy employee (most orders) and one record of each kind, so detail pages have something to show."""
    from django.apps import apps
    from django.db.models import Count

    ids: dict[str, int | None] = {}
    order_model = apps.get_model("employees", "HrOrder")
    emp_field = next(f.name for f in order_model._meta.fields if f.is_relation and f.related_model.__name__ == "Employee")
    busy = order_model.objects.values(emp_field).annotate(n=Count("pk")).order_by("-n").first()
    ids["emp"] = busy[emp_field] if busy else first_id("employees.EmployeeExt")
    ids["emp_plain"] = first_id("employees.EmployeeExt")
    order = order_model.objects.filter(**{emp_field: ids["emp"]}).order_by("pk").first()
    ids["order"] = order.pk if order else None
    ids["leave_req"] = first_id("leave.LeaveRequest")
    ids["leave"] = first_id("leave.LeaveExt")
    ids["leave_type"] = first_id("leave.LeaveTypeExt")
    ids["vacancy"] = first_id("recruitment.Vacancy")
    ids["candidate"] = first_id("recruitment.Candidate")
    return ids


def build_urls(ids: dict[str, int | None]) -> list[str]:
    from employees import sections
    from lists.registry import LISTS
    from reports.registry import REPORTS

    urls = [
        "/",
        "/me/",
        "/employees/today/",
        "/employees/today/away/",
        "/employees/today/upcoming/",
        "/employees/",
        "/employees/?view=table",
        "/employees/palette/?q=ба",
        "/employees/orders/",
        "/employees/orders/print/",
        "/employees/slots/",
        "/employees/self-forms/",
        "/employees/new/",
        "/employees/import/",
        "/employees/check-register/",
        "/leave/",
        "/leave/calendar/",
        "/leave/balances/",
        "/leave/requests/",
        "/leave/requests/new/",
        "/leave/new/",
        "/leave/holidays/",
        "/leave/settings/",
        "/checklists/mine/",
        "/recruitment/",
        "/recruitment/vacancies/add/",
        "/lists/",
        "/logs/",
        "/logs/system/",
        "/assistant/",
        "/admin/",
    ]
    e, o = ids["emp"], ids["order"]
    if e:
        urls += [f"/employees/{e}/", f"/employees/{e}/activity/"]
        urls += [f"/employees/{e}/section/{s}/" for s in sections.SECTIONS]
        urls += [f"/employees/{e}/personal/{k}/list/" for k in sections.INLINE_LISTS]
        if o:
            urls += [f"/employees/{e}/order/{o}/detail/", f"/employees/{e}/order/{o}/history/"]
    if ids["emp_plain"] and ids["emp_plain"] != e:
        urls.append(f"/employees/{ids['emp_plain']}/")
    if ids["leave_req"]:
        urls.append(f"/leave/requests/{ids['leave_req']}/")
    if ids["leave"]:
        urls.append(f"/leave/{ids['leave']}/edit/")
    if ids["leave_type"]:
        urls.append(f"/leave/settings/type/{ids['leave_type']}/")
    if ids["vacancy"]:
        urls += [f"/recruitment/vacancies/{ids['vacancy']}/", f"/recruitment/vacancies/{ids['vacancy']}/edit/"]
    if ids["candidate"]:
        urls.append(f"/recruitment/candidates/{ids['candidate']}/")
    urls += [f"/lists/{slug}/" for slug in LISTS]
    for key in REPORTS:
        urls += [f"/reports/{key}/", f"/reports/{key}/print/", f"/reports/{key}/excel/"]
    return urls


def timed(client: Client, url: str) -> tuple[float, int, int, int, int]:
    shapes: Counter[str] = Counter()

    def count(execute, sql, params, many, context):  # type: ignore[no-untyped-def]
        shapes[SHAPE.sub("?", sql)[:400]] += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count):
        start = time.perf_counter()
        response = client.get(url, follow=True, HTTP_HOST="localhost")
        seconds = time.perf_counter() - start
    return seconds, sum(shapes.values()), max(shapes.values(), default=0), response.status_code, len(response.content) // 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", default=",".join(ROLES))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--top", type=int, default=40, help="rows to print per role (0 = all)")
    args = parser.parse_args()

    if not settings.DATABASES["default"]["NAME"].startswith("info_hr_perf") and "info_hr_demo" not in str(
        settings.DATABASES["default"]["NAME"]
    ):
        sys.exit("Refusing to run: point DJANGO_DB_NAME at a scratch database (info_hr_perf*).")

    ids = sample_ids()
    urls = build_urls(ids)
    print(f"database {settings.DATABASES['default']['NAME']}, {len(urls)} URLs, ids {ids}")
    for role in args.roles.split(","):
        user = User.objects.filter(username=role).first()
        if user is None:
            print(f"\n== {role}: no such user, skipped")
            continue
        client = Client()
        client.force_login(user)
        client.get("/employees/today/")  # warm up: the first request of a day runs the daily sync
        rows = []
        for url in urls:
            runs = [timed(client, url) for _ in range(args.runs)]
            median = statistics.median(r[0] for r in runs)
            _, queries, repeat, status, kb = runs[-1]
            rows.append((median, queries, repeat, status, kb, url))
        rows.sort(reverse=True)
        print(f"\n== {role}: slowest first (median of {args.runs}); rep = most repeats of one query shape")
        print("     ms     q   rep  st    KB  url")
        for ms, q, rep, status, kb, url in rows[: args.top or None]:
            print(f"{ms * 1000:7.0f} {q:5d} {rep:5d} {status:4d} {kb:5d}  {url}")
        n1 = [r for r in rows if r[2] >= 25]
        print(f"-- {len(n1)} page(s) repeat one query shape 25+ times (possible N+1)")


main()

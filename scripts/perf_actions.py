"""Performance audit, part 2: time the ACTIONS (file downloads, bulk actions, saves, live checks).

Run on a seeded scratch database only (see perf_audit.py for how to build one):

    MSYS_NO_PATHCONV=1 DJANGO_DB_NAME=info_hr_perf DJANGO_DEBUG=false python scripts/perf_actions.py

Every write runs inside a transaction that is rolled back, so the data stays as it was (generated files and
the export log may still be written). The help assistant (`/assistant/ask/`) is NOT called: it may reach a real
provider. Prints: milliseconds, SQL queries, status, size, label. Slowest first.
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
from django.db import connection, transaction
from django.test import Client
from employees.models import HrOrder

settings.ALLOWED_HOSTS = ["*"]


def run(client: Client, label: str, method: str, url: str, data: dict | None = None) -> tuple:
    queries = 0

    def count(execute, sql, params, many, context):  # type: ignore[no-untyped-def]
        nonlocal queries
        queries += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count), transaction.atomic():
        start = time.perf_counter()
        try:
            response = getattr(client, method)(url, data or {}, HTTP_HOST="localhost", secure=True)
            status, size = response.status_code, len(getattr(response, "content", b"") or b"") // 1024
            if getattr(response, "streaming", False):
                size = len(b"".join(response.streaming_content)) // 1024
        except Exception as error:  # noqa: BLE001  (an audit must keep going)
            status, size = -1, 0
            label += f"  !! {type(error).__name__}: {str(error)[:80]}"
        seconds = time.perf_counter() - start
        transaction.set_rollback(True)
    return seconds, queries, status, size, label


def main() -> None:
    admin = User.objects.get(username="admin")
    client = Client()
    client.force_login(admin)
    client.get("/employees/today/", secure=True)  # warm up (daily sync)
    rows = []

    orders = list(HrOrder.objects.order_by("pk")[:150])
    order = orders[0]
    emp = order.employee_id if hasattr(order, "employee_id") else None
    if emp:
        for kind in ("document", "document/pdf"):
            rows.append(run(client, f"order {kind} (one order)", "get", f"/employees/{emp}/order/{order.pk}/{kind}/"))
    ids = [o.pk for o in orders]
    for n in (10, 50, 100):
        rows.append(run(client, f"print {n} selected orders (PDF)", "post", "/employees/orders/print/selected/", {"ids": ids[:n]}))

    for key in ("staff-list", "leave-balance"):
        for action in ("excel", "csv", "print", "copy"):
            rows.append(
                run(client, f"{key}: selected {action} (all people)", "post", f"/reports/{key}/selected/{action}/",
                    {"all": "1", "query": ""})
            )
        for action in ("excel", "print"):
            rows.append(run(client, f"{key}: whole-report {action}", "get", f"/reports/{key}/{action}/"))

    rows.append(run(client, "palette search (typing)", "get", "/employees/palette/?q=ба"))
    rows.append(run(client, "palette search (2 letters)", "get", "/employees/palette/?q=Б"))
    if emp:
        rows.append(run(client, "add a note to an employee", "post", f"/employees/{emp}/note/", {"text": "perf check"}))
    rows.append(run(client, "orders printout (register)", "get", "/employees/orders/print/"))
    rows.append(run(client, "logs export (system)", "get", "/logs/system/export/"))
    rows.append(run(client, "logs export (employee)", "get", "/logs/export/"))
    rows.append(run(client, "staff import template", "get", "/employees/import/template.xlsx"))

    print(f"database {settings.DATABASES['default']['NAME']}, employees {HrOrder.objects.count()} orders")
    print("     ms     q  st    KB  action")
    for seconds, queries, status, kb, label in sorted(rows, reverse=True):
        print(f"{seconds * 1000:7.0f} {queries:5d} {status:4d} {kb:5d}  {label}")


main()

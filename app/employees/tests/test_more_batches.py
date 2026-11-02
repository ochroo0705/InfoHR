"""The order register and the «Түүх» activity drawer load in batches (config/batching.py)."""

from datetime import date
from typing import Any
from urllib.parse import parse_qs

import pytest
from accounts.models import User
from config import batching
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from macs.models import Command, Employee

from employees import views
from employees.models import ActivityEntry, ActivityKind, HrOrder
from employees.services import order_register

from .test_order_register import make_order
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


ORDERS = 8
BATCH = 3
HTMX = {"HX-Request": "true"}


def _next_query(body: str, url: str) -> dict[str, list[str]]:
    marker = f'hx-get="{url}?'
    if marker not in body:
        return {}
    return parse_qs(body.split(marker)[1].split('"')[0].replace("&amp;", "&"))


@pytest.fixture
def orders(hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    for n in range(ORDERS):
        make_order(hired, f"{100 + n}", date(2026, 3, 1 + n))


def _numbers(body: str) -> list[str]:
    return [f"Тушаал {100 + n}" for n in range(ORDERS) if f"Тушаал {100 + n}" in body]


def test_register_loads_in_batches_and_the_print_view_shows_everything(
    hr: Client, orders: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", BATCH)
    first = hr.get("/employees/orders/").content.decode()
    assert len(_numbers(first)) == BATCH
    seen, query = len(_numbers(first)), _next_query(first, "/employees/orders/")
    assert query["offset"] == [str(BATCH)]
    while query:
        body = hr.get(f"/employees/orders/?offset={query['offset'][0]}", headers=HTMX).content.decode()
        assert "<html" not in body and "<table" not in body  # rows only, appended to the existing table
        seen += len(_numbers(body))
        query = _next_query(body, "/employees/orders/")
    assert seen == ORDERS
    printed = hr.get("/employees/orders/print/").content.decode()
    assert len(_numbers(printed)) == ORDERS  # the print view is never batched


def test_register_empty_text_only_on_the_first_batch(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    assert "Тушаал олдсонгүй" in hr.get("/employees/orders/").content.decode()
    assert "Тушаал олдсонгүй" not in hr.get("/employees/orders/?offset=999", headers=HTMX).content.decode()


@pytest.fixture
def log(hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(views, "ACTIVITY_BATCH", BATCH)
    before = ActivityEntry.objects.filter(employee=hired).count()
    for n in range(8):
        ActivityEntry.objects.create(employee=hired, by=actor, kind=ActivityKind.NOTE, message=f"Тэмдэглэл-{n}-")
    return before + 8


def _notes(body: str) -> int:
    return sum(f"Тэмдэглэл-{n}-" in body for n in range(8))


def test_activity_drawer_shows_the_newest_batch_then_loads_older_entries(hr: Client, hired: Employee, log: int) -> None:
    page = hr.get(f"/employees/{hired.pk}/").content.decode()
    assert f"/employees/{hired.pk}/activity/?offset={BATCH}" in page
    assert _notes(page) == BATCH and "Тэмдэглэл-7-" in page  # newest first
    seen = _notes(page)
    offset: int | None = BATCH
    while offset is not None:
        body = hr.get(f"/employees/{hired.pk}/activity/", {"offset": offset}).content.decode()
        assert "<html" not in body and "Cache" not in body
        seen += _notes(body)
        query = _next_query(body, f"/employees/{hired.pk}/activity/")
        offset = int(query["offset"][0]) if query else None
    assert seen == 8


def test_activity_next_batch_does_not_repeat_a_day_heading(hr: Client, hired: Employee, log: int) -> None:
    # every entry was made today: the second batch continues the same day, so it adds no heading
    body = hr.get(f"/employees/{hired.pk}/activity/", {"offset": BATCH}).content.decode()
    assert "<h3" not in body and "<ol" in body


def test_activity_more_respects_who_may_see_the_employee(client: Client, hired: Employee) -> None:
    assert client.get(f"/employees/{hired.pk}/activity/").status_code in (302, 403, 404)


def _filters(**more: Any) -> dict[str, Any]:
    return {"year": None, "order_type": None, "department_id": None, "state": None, **more}


def test_register_batches_merge_both_sources_like_the_full_list(hr: Client, hired: Employee) -> None:
    """Info HR orders and MACS orders interleave by date; walking the batches gives exactly the full list."""
    HrOrder.objects.filter(employee=hired).delete()
    for n in range(5):
        make_order(hired, f"{200 + n}", date(2026, 3, 2 * n + 1))
        Command.objects.create(employee_id=hired.pk, number=f"L{n}", date=date(2026, 3, 2 * n + 2), summary="x")
    Command.objects.create(employee_id=hired.pk, number="L-same", date=date(2026, 3, 1), summary="x")  # tie with 200
    user = User.objects.get(username="hr1")
    full = [r.number for r in order_register.register_rows(user, **_filters())]
    assert len(full) == 11 and full[:2] == ["L4", "204"]
    for size in (1, 2, 3, 4, 11, 20):
        walked: list[str] = []
        offset, more = 0, True
        while more:
            rows, more = order_register.register_page(user, **_filters(), offset=offset, size=size)
            assert len(rows) <= size
            walked += [r.number for r in rows]
            offset += size
        assert walked == full, size


def test_register_page_filters_in_the_database_like_the_full_list(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "301", date(2025, 1, 5))
    make_order(hired, "302", date(2026, 1, 5))
    Command.objects.create(employee_id=hired.pk, number="L-301", date=date(2026, 2, 2), summary="x")
    user = User.objects.get(username="hr1")
    for extra in (
        {"year": 2026},
        {"state": "legacy"},
        {"q": "301"},
        {"q": hired.code or "", "year": 2025},
        {"q": "zz"},
    ):
        full = [r.number for r in order_register.register_rows(user, **_filters(**extra))]
        page, more = order_register.register_page(user, **_filters(**extra), offset=0, size=50)
        assert [r.number for r in page] == full and not more, extra


def test_register_page_reads_only_a_batch_from_the_database(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    for n in range(20):
        make_order(hired, f"{400 + n}", date(2026, 3, 1 + n))
        Command.objects.create(employee_id=hired.pk, number=f"M{n}", date=date(2026, 4, 1 + n), summary="x")
    user = User.objects.get(username="hr1")
    with CaptureQueriesContext(connection) as queries:
        rows, more = order_register.register_page(user, **_filters(), offset=0, size=3)
    assert len(rows) == 3 and more
    assert all(
        "LIMIT 4" in q["sql"] for q in queries.captured_queries if '"hrorder"' in q["sql"] or '"command"' in q["sql"]
    )
    assert any('"command"' in q["sql"] for q in queries.captured_queries)

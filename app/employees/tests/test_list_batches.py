"""The employee list shows one batch of people and loads the next when its last element scrolls into view."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone

from employees import views
from employees.services import history, macs_writes

pytestmark = pytest.mark.django_db

PEOPLE = 8
BATCH = 3
HTMX = {"HX-Request": "true"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Client:
    monkeypatch.setattr(views, "LIST_BATCH", BATCH)
    admin = User.objects.create_superuser("batch_admin", password="x-long-pass-123")  # noqa: S106
    department = macs_writes.save_department("Хэлтэс")
    position = macs_writes.save_position("Мэргэжилтэн")
    start = timezone.localdate() - timedelta(days=500)
    for i in range(PEOPLE):
        job: dict[str, Any] = {
            "position": position,
            "department": department,
            "employee_type": "full_time",
            "status": "active",
            "contract_type": "open_ended",
        }
        values = {
            "family_name": "Батын",
            "given_name": f"Ажилтан{i}",
            "register_no": f"УБ{90000000 + i}",
            "birth_date": date(1990, 1, 1 + i),
            "gender": "M",
            "first_hire_date": start,
            "work_conditions": 1,
        }
        history.hire(values, {}, start=start, job=job, salary=Decimal("2500000"), by=admin)
    c = Client()
    c.force_login(admin)
    return c


def _names(body: str) -> list[str]:
    return [f"Ажилтан{i}" for i in range(PEOPLE) if f"Ажилтан{i}" in body]


def _next_query(body: str) -> dict[str, list[str]]:
    marker = 'hx-get="/employees/?'
    if marker not in body:
        return {}
    return parse_qs(body.split(marker)[1].split('"')[0].replace("&amp;", "&"))


def _next_offset(body: str) -> int | None:
    query = _next_query(body)
    return int(query["offset"][0]) if query else None


def test_first_page_shows_one_batch_and_the_loader(client: Client) -> None:
    body = client.get("/employees/").content.decode()
    assert len(_names(body)) == BATCH
    assert _next_offset(body) == BATCH
    assert "data-more-batch" in body


def test_batches_cover_everyone_once_without_a_gap(client: Client) -> None:
    seen = _names(client.get("/employees/", headers=HTMX).content.decode())
    body, offset = "", BATCH
    next_offset: int | None = offset
    while next_offset is not None:
        body = client.get(f"/employees/?offset={next_offset}", headers=HTMX).content.decode()
        seen += _names(body)
        next_offset = _next_offset(body)
    assert sorted(seen) == sorted(f"Ажилтан{i}" for i in range(PEOPLE))
    assert "data-more-batch" not in body  # the last batch has no loader


def test_next_batch_keeps_the_filters_and_the_view(client: Client) -> None:
    body = client.get("/employees/?view=table&q=Ажилтан", headers=HTMX).content.decode()
    query = _next_query(body)
    assert query["view"] == ["table"] and query["q"] == ["Ажилтан"] and query["offset"] == [str(BATCH)]
    more = client.get(f"/employees/?view=table&q=Ажилтан&offset={BATCH}", headers=HTMX).content.decode()
    assert "<tr" in more and "<html" not in more  # table rows only, no page around them


def test_batch_is_a_fragment_that_continues_the_grid(client: Client) -> None:
    more = client.get(f"/employees/?offset={BATCH}", headers=HTMX).content.decode()
    assert "<html" not in more and 'class="grid' not in more  # cards only, appended to the existing grid
    assert len(_names(more)) == BATCH


def test_offset_is_ignored_without_htmx_and_bad_values_mean_the_first_batch(client: Client) -> None:
    plain = client.get(f"/employees/?offset={BATCH}").content.decode()
    assert (
        "<html" in plain
        and len(_names(plain)) == BATCH
        and _names(plain)[0] == _names(client.get("/employees/").content.decode())[0]
    )
    for bad in ("-5", "abc", ""):
        assert len(_names(client.get(f"/employees/?offset={bad}", headers=HTMX).content.decode())) == BATCH
    assert (
        _names(client.get("/employees/?offset=999", headers=HTMX).content.decode()) == []
    )  # past the end: nothing, no loader


def test_grouped_list_is_not_batched(client: Client) -> None:
    body = client.get("/employees/?group=1").content.decode()
    assert len(_names(body)) == PEOPLE and "data-more-batch" not in body

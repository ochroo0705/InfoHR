"""Printing many orders in the background: the job folder, its status, who may read it."""

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from employees.models import Employee, HrOrder, OrderState, OrderType
from employees.services import order_docs, print_jobs

from .test_order_docs import _need_pdf_font, hire_order, hr  # noqa: F401  (hr is a fixture)
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _inline_jobs(settings: Any, tmp_path: Path) -> None:
    settings.PRINT_JOBS_INLINE = True
    settings.PRINT_JOBS_ROOT = tmp_path / "jobs"


def _start(client: Client, *ids: object) -> Any:
    return client.post(reverse("employees:orders_print_start"), {"ids": list(ids)})


def test_start_builds_a_pdf_the_starter_can_fetch(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    body = _start(hr, order.pk).json()
    assert body["status"].endswith("/status/") and body["file"].endswith("/file/")
    assert hr.get(body["status"]).json() == {"state": "ready", "count": 1, "message": ""}
    file = hr.get(body["file"])
    assert file.status_code == 200 and file["Content-Type"] == order_docs.PDF_TYPE
    assert b"".join(file.streaming_content).startswith(b"%PDF-")


def test_each_printed_order_is_logged(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    before = SystemLogEntry.objects.filter(action="download_order").count()
    _start(hr, order.pk)
    assert SystemLogEntry.objects.filter(action="download_order").count() == before + 1


def test_nothing_to_print_fails_the_job(hr: Client, hired: Employee) -> None:  # noqa: F811
    order = hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    body = _start(hr, order.pk).json()
    assert hr.get(body["status"]).json()["state"] == "failed"
    assert hr.get(body["file"]).status_code == 404
    assert _start(hr, "abc", "-1").status_code == 400
    assert hr.post(reverse("employees:orders_print_start")).status_code == 400


def test_a_crash_while_building_fails_the_job(
    hr: Client,
    hired: Employee,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    order = hire_order(hired)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("no font")

    monkeypatch.setattr(order_docs, "render_pdf_many", boom)
    body = _start(hr, order.pk).json()
    assert hr.get(body["status"]).json() == {"state": "failed", "count": 1, "message": print_jobs.FAILED}


def test_only_the_starter_with_the_right_can_use_a_job(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    body = _start(hr, order.pk).json()
    accountant = Client()
    login_as(accountant, "Accountant", "acc1")
    assert accountant.get(body["status"]).status_code == 403
    assert accountant.get(body["file"]).status_code == 403
    assert _start(accountant, order.pk).status_code == 403
    assert Client().get(body["status"]).status_code == 302  # not signed in
    assert hr.get(reverse("employees:orders_print_status", args=["x" * 20])).status_code == 404
    assert hr.get(reverse("employees:orders_print_file", args=["..%2F..%2Fx" + "y" * 20])).status_code == 404


def test_another_manager_cannot_read_the_job(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    body = _start(hr, order.pk).json()
    folder = Path(print_jobs._root()) / body["status"].split("/")[-3]
    data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    data["user"] = data["user"] + 1000  # as if another user had started it
    (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")
    assert hr.get(body["status"]).status_code == 404 and hr.get(body["file"]).status_code == 404


def test_a_job_stuck_running_turns_to_failed(hr: Client, hired: Employee) -> None:  # noqa: F811
    order = hire_order(hired)
    body = _start(hr, order.pk).json()
    folder = Path(print_jobs._root()) / body["status"].split("/")[-3]
    data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    data.update(state="running", created=time.time() - print_jobs.STALE_AFTER - 5)
    (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")
    info = hr.get(body["status"]).json()
    assert info["state"] == "failed" and info["message"] == print_jobs.RESTARTED


def test_old_job_folders_are_removed_on_the_next_start(hr: Client, hired: Employee) -> None:  # noqa: F811
    old = Path(print_jobs._root()) / ("o" * 24)
    old.mkdir(parents=True)
    (old / "result.pdf").write_bytes(b"%PDF-")
    long_ago = time.time() - print_jobs.KEEP_FOR - 60
    os.utime(old, (long_ago, long_ago))
    _start(hr, hire_order(hired).pk)
    assert not old.exists()


def _hr_user() -> User:
    user = User.objects.create_user("hr_print", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return user


def test_parse_ids_drops_non_decimal_and_long_values() -> None:
    values = ["1", "abc", "-1", "9" * 10, "12", "12", "9" * 9]
    assert print_jobs.parse_ids(values) == [1, 12, 12, 999999999]


def test_render_now_orders_by_date_and_skips_cancelled_and_foreign(hired: Employee, actor: User) -> None:
    _need_pdf_font()
    late = hire_order(hired)
    HrOrder.objects.filter(pk=late.pk).update(date=date(2026, 2, 1))
    early = HrOrder.objects.create(employee=hired, is_hire=True, order_type=OrderType.HIRED, date=date(2026, 1, 1))
    cancelled = HrOrder.objects.create(
        employee=hired, is_hire=True, order_type=OrderType.HIRED, date=date(2025, 1, 1), state=OrderState.CANCELLED
    )
    data, used = print_jobs.render_now(_hr_user(), [late.pk, early.pk, cancelled.pk])
    assert data.startswith(b"%PDF-") and [o.pk for o in used] == [early.pk, late.pk]
    with pytest.raises(print_jobs.NothingToPrint):
        print_jobs.render_now(actor, [late.pk])  # a user who sees no employee of this order


def test_render_now_raises_nothing_to_print_when_empty(hired: Employee) -> None:
    user = _hr_user()
    for ids in ([], [999999]):
        with pytest.raises(print_jobs.NothingToPrint) as info:
            print_jobs.render_now(user, ids)
        assert str(info.value) == print_jobs.NOTHING


def test_render_now_caps_at_limit(hired: Employee, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    HrOrder.objects.bulk_create(
        [
            HrOrder(employee=hired, is_hire=True, order_type=OrderType.HIRED, date=date(2026, 1, 1))
            for _ in range(print_jobs.LIMIT + 1)
        ]
    )
    pks = list(HrOrder.objects.values_list("pk", flat=True))
    seen: list[list[HrOrder]] = []

    def fake(orders: list[HrOrder], user: User) -> tuple[bytes, list[HrOrder]]:
        seen.append(orders)
        return b"%PDF-", orders

    monkeypatch.setattr(order_docs, "render_pdf_many", fake)
    print_jobs.render_now(_hr_user(), pks)
    assert len(seen[0]) == print_jobs.LIMIT == print_jobs.ORDER_PRINT_LIMIT


def test_register_page_has_the_badge_and_the_threshold(hr: Client, hired: Employee) -> None:  # noqa: F811
    body = hr.get(reverse("employees:orders")).content.decode()
    assert 'id="print-job"' in body and reverse("employees:orders_print_start") in body
    assert f'data-background-from="{print_jobs.BACKGROUND_FROM}"' in body

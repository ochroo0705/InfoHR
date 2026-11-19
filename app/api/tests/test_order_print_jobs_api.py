"""The print-selected route and the background print jobs of the order register API (the same rules as the Django
views orders_print_selected/start/status/file)."""

import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts import roles
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from employees.models import Employee, HrOrder
from employees.services import history, macs_writes, order_docs, print_jobs
from employees.tests.conftest import hire_values
from employees.tests.test_order_docs import _need_pdf_font

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
SELECTED = "/api/v1/orders/print/selected"
START = "/api/v1/orders/print/start"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOTHING = {"field_errors": {}, "form_errors": [print_jobs.NOTHING]}
FILE_NAME = "tushaal-songoson.pdf"


@pytest.fixture(autouse=True)
def _inline_jobs(settings: Any, tmp_path: Path) -> None:
    settings.PRINT_JOBS_INLINE = True
    settings.PRINT_JOBS_ROOT = tmp_path / "jobs"


def _user(name: str, group: str | None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def hr() -> User:
    return _user("print_jobs_hr", roles.HR)


@pytest.fixture
def job_values() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr: User, job_values: dict[str, Any]) -> Employee:
    """An employee hired with a hire order (number 1), as the employees conftest does."""
    return history.hire(
        hire_values("УБ99112293"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=hr,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _form_post(client: Client, path: str, ids: list[object], token: str | None = None) -> Any:
    data: dict[str, Any] = {"ids": [str(i) for i in ids]}
    if token is not None:
        data["csrfmiddlewaretoken"] = token
    return client.post(path, urlencode(data, doseq=True), content_type="application/x-www-form-urlencoded")


def _start(client: Client, *ids: object) -> Any:
    return _form_post(client, START, list(ids))


def _folder_of(body: dict[str, Any]) -> Path:
    return Path(print_jobs._root()) / body["token"]


def _rewrite(folder: Path, **changes: Any) -> None:
    data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    data.update(changes)
    (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")


def _export_count() -> int:
    return SystemLogEntry.objects.filter(action="download_order").count()


def test_selected_returns_pdf_and_logs_each_order(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    before = _export_count()
    response = _form_post(_client(hr), SELECTED, [order.pk])
    assert response.status_code == 200
    assert response["Content-Type"] == order_docs.PDF_TYPE
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response["Content-Disposition"] and FILE_NAME in response["Content-Disposition"]
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    assert _export_count() == before + 1


def test_selected_400_when_nothing_printable(hr: User, hired: Employee) -> None:
    client = _client(hr)
    response = _form_post(client, SELECTED, [999999])
    assert response.status_code == 400 and response.json() == NOTHING
    response = client.post(SELECTED, {})
    assert response.status_code == 400 and response.json() == NOTHING


def test_selected_403_without_manage(hired: Employee) -> None:
    accountant = _user("print_jobs_acc", roles.ACCOUNTANT)
    response = _form_post(_client(accountant), SELECTED, [1])
    assert response.status_code == 403 and response.json() == FORBIDDEN


def test_selected_requires_csrf_token_in_form(hr: User, hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    client = Client(enforce_csrf_checks=True)
    client.force_login(hr)
    assert _form_post(client, SELECTED, [order.pk]).status_code == 403
    token = client.get("/api/v1/auth/csrf").json()["token"]
    assert _form_post(client, SELECTED, [order.pk], token).status_code == 200


def test_start_returns_api_paths_and_token(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    body = _start(_client(hr), order.pk).json()
    assert set(body) == {"token", "status", "file"}
    assert body["status"] == f"/api/v1/orders/print/{body['token']}/status"
    assert body["file"] == f"/api/v1/orders/print/{body['token']}/file"
    assert _client(hr).get(body["status"]).json() == {"state": "ready", "count": 1, "message": ""}


def test_start_without_ids_is_400(hr: User, hired: Employee) -> None:
    response = _client(hr).post(START, {})
    assert response.status_code == 400 and response.json() == NOTHING


def test_start_403_without_manage(hired: Employee) -> None:
    accountant = _user("print_jobs_acc2", roles.ACCOUNTANT)
    response = _start(_client(accountant), 1)
    assert response.status_code == 403 and response.json() == FORBIDDEN


def test_status_running_ready_failed(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    client = _client(hr)
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    ready = _start(client, order.pk).json()
    assert client.get(ready["status"]).json() == {"state": "ready", "count": 1, "message": ""}

    running = _start(client, order.pk).json()
    _rewrite(_folder_of(running), state="running", created=time.time())
    assert client.get(running["status"]).json() == {"state": "running", "count": 1, "message": ""}

    HrOrder.objects.filter(pk=order.pk).update(state="cancelled")
    failed = _start(client, order.pk).json()
    assert client.get(failed["status"]).json() == {"state": "failed", "count": 1, "message": print_jobs.NOTHING}


def test_status_404_for_other_users_job_and_bad_token(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    body = _start(_client(hr), order.pk).json()
    other = _client(_user("print_jobs_hr2", roles.HR))
    assert other.get(body["status"]).status_code == 404
    assert _client(hr).get("/api/v1/orders/print/not-a-token/status").status_code == 404
    assert _client(hr).get("/api/v1/orders/print/" + "x" * 20 + "/status").status_code == 404


def test_file_404_until_ready_and_for_other_user(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    client = _client(hr)
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    body = _start(client, order.pk).json()
    _rewrite(_folder_of(body), state="running", created=time.time())
    assert client.get(body["file"]).status_code == 404  # not ready yet
    _rewrite(_folder_of(body), state="ready", count=1)
    assert _client(_user("print_jobs_hr3", roles.HR)).get(body["file"]).status_code == 404  # not theirs
    assert client.get("/api/v1/orders/print/" + "y" * 20 + "/file").status_code == 404


def test_file_streams_pdf_when_ready(hr: User, hired: Employee) -> None:
    _need_pdf_font()
    client = _client(hr)
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    body = _start(client, order.pk).json()
    response = client.get(body["file"])
    assert response.status_code == 200
    assert response["Content-Type"] == order_docs.PDF_TYPE
    assert response["X-Content-Type-Options"] == "nosniff"
    assert FILE_NAME in response["Content-Disposition"]
    assert b"".join(response.streaming_content).startswith(b"%PDF-")


def test_print_job_routes_require_login(db: None) -> None:
    client = Client()
    assert _form_post(client, SELECTED, [1]).json() == NOT_LOGGED_IN
    assert _start(client, 1).json() == NOT_LOGGED_IN
    assert client.get("/api/v1/orders/print/" + "z" * 20 + "/status").json() == NOT_LOGGED_IN
    assert client.get("/api/v1/orders/print/" + "z" * 20 + "/file").json() == NOT_LOGGED_IN

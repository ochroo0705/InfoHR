"""The order file routes: GET .../orders/{order_id}/file (the signed scan), .../document and .../document/pdf (the Word
and PDF drafts), .../signing-image, and the own saved signature GET /api/v1/me/signature and POST
/api/v1/me/signature/delete. The bytes and headers match the Django views; the rights, the 404s and the export log
are the same as the views' (the rules live in employees.services.order_files)."""

import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import Employee, HrOrder, OrderSigning, OrderState
from employees.services import history, macs_writes, order_docs, order_signing
from employees.services.order_files import order_label
from employees.tests.conftest import hire_values
from PIL import Image

from api import order_files as api_order_files

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NOT_FOUND = "Хуудас олдсонгүй"
FORBIDDEN = "Хандах эрх байхгүй."
PDF = b"%PDF-1.4\n%test\n"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), (20, 20, 20, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("order_files_api_hr", roles.HR)


@pytest.fixture
def accountant(db: None) -> User:
    return _user("order_files_api_accountant", roles.ACCOUNTANT)


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05 by an order numbered 1."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def other(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A second employee, hired by order 2, for the foreign-order checks."""
    return history.hire(
        hire_values("УБ99112244"),
        {},
        start=date(2026, 1, 6),
        job=job_values,
        salary=Decimal("2000000"),
        by=hr_user,
        order_number="2",
        order_date=date(2026, 1, 6),
    )


@pytest.fixture
def order_root(settings: Any) -> Path:
    """Where order files are written: the temporary folder conftest sets for every test (never app/private)."""
    return Path(settings.ORDER_FILES_ROOT)


@pytest.fixture
def exports(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The export log calls the routes make, as (action, label). The real log is not read here."""
    calls: list[tuple[str, str]] = []

    def record(request: Any, action: str, what: str, **_: Any) -> None:
        calls.append((action, what))

    monkeypatch.setattr(api_order_files, "record_export", record)
    return calls


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _url(employee: Employee, order: HrOrder, tail: str) -> str:
    return f"/api/v1/employees/{employee.pk}/orders/{order.pk}/{tail}"


def _hire_order(employee: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=employee, is_hire=True)


def _with_scan(order: HrOrder, content: bytes = PDF, name: str = "scan.pdf") -> HrOrder:
    order.file.save(name, ContentFile(content), save=True)
    order.refresh_from_db()
    return order


def _with_signing(order: HrOrder) -> None:
    signing = OrderSigning.objects.create(
        order=order,
        signer_name="Тест Гарын үсэг",
        signed_at=timezone.now(),
        method=OrderSigning.Method.DRAWN,
        pdf_sha256="0" * 64,
    )
    signing.image.save("sig.png", ContentFile(_png()), save=True)


def _body(response: Any) -> bytes:
    if response.streaming:
        return b"".join(response.streaming_content)
    return bytes(response.content)


def _stub_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_docs, "render_order", lambda order, user: b"docx-bytes")
    monkeypatch.setattr(order_docs, "render_pdf", lambda order, user: b"pdf-bytes")


def test_anonymous_file_routes_answer_401(hired: Employee) -> None:
    order = _hire_order(hired)
    anonymous = Client()  # never logged in

    responses = [
        anonymous.get(_url(hired, order, "file")),
        anonymous.get(_url(hired, order, "document")),
        anonymous.get(_url(hired, order, "document/pdf")),
        anonymous.get(_url(hired, order, "signing-image")),
        anonymous.get("/api/v1/me/signature"),
        anonymous.post("/api/v1/me/signature/delete"),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == NOT_LOGGED_IN


def test_file_returns_same_bytes_and_headers_as_django_view(
    hired: Employee, accountant: User, order_root: Path
) -> None:
    order = _with_scan(_hire_order(hired))
    client = _client(accountant)

    api = client.get(_url(hired, order, "file"))
    django = client.get(reverse("employees:order_file", args=[hired.pk, order.pk]))

    assert api.status_code == django.status_code == 200
    assert _body(api) == _body(django) == PDF
    for header in ("Content-Type", "Content-Disposition", "Cache-Control", "X-Content-Type-Options"):
        assert api[header] == django[header]
    assert api["Content-Disposition"] == f'inline; filename="order-{order.pk}.pdf"'
    assert api["Cache-Control"] == "private, no-store"
    assert api["X-Content-Type-Options"] == "nosniff"


def test_file_logs_export_with_prefix(hired: Employee, accountant: User, order_root: Path, exports: list) -> None:
    order = _with_scan(_hire_order(hired))

    response = _client(accountant).get(_url(hired, order, "file"))

    assert response.status_code == 200
    assert exports == [("download_order", "Гарын үсэгтэй файл: " + order_label(order, hired))]


def test_file_403_hire_order_without_scan_right(
    hired: Employee, hr_user: User, order_root: Path, exports: list
) -> None:
    order = _with_scan(_hire_order(hired))  # HR may manage orders but not see the salary scan of a hire order

    response = _client(hr_user).get(_url(hired, order, "file"))

    assert response.status_code == 403
    assert response.json() == {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
    assert exports == []


def test_file_404_foreign_employee_and_foreign_order(
    hired: Employee, other: Employee, accountant: User, order_root: Path
) -> None:
    client = _client(accountant)
    own_order = _with_scan(_hire_order(hired))
    foreign_order = _with_scan(_hire_order(other), name="other.pdf")

    assert client.get(_url(hired, foreign_order, "file")).status_code == 404  # an order of another employee
    assert client.get(_url(other, own_order, "file")).status_code == 404  # the order is not the employee's
    assert client.get(f"/api/v1/employees/999999/orders/{own_order.pk}/file").status_code == 404


def test_document_docx_and_pdf_attachment_names(
    hired: Employee, hr_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_docs(monkeypatch)
    order = _hire_order(hired)
    client = _client(hr_user)

    word = client.get(_url(hired, order, "document"))
    pdf = client.get(_url(hired, order, "document/pdf"))

    assert word.status_code == 200 and _body(word) == b"docx-bytes"
    assert word["Content-Type"] == order_docs.DOCX_TYPE
    assert word["Content-Disposition"] == f'attachment; filename="tushaal-{order.number}.docx"'
    assert pdf.status_code == 200 and _body(pdf) == b"pdf-bytes"
    assert pdf["Content-Type"] == order_docs.PDF_TYPE
    assert pdf["Content-Disposition"] == f'attachment; filename="tushaal-{order.number}.pdf"'


def test_document_logs_export_once(
    hired: Employee, hr_user: User, monkeypatch: pytest.MonkeyPatch, exports: list
) -> None:
    _stub_docs(monkeypatch)
    order = _hire_order(hired)

    _client(hr_user).get(_url(hired, order, "document"))
    _client(hr_user).get(_url(hired, order, "document/pdf"))

    assert exports == [
        ("download_order", order_label(order, hired)),
        ("download_order", order_label(order, hired)),
    ]


def test_document_404_cancelled_and_403_without_manage(
    hired: Employee, hr_user: User, accountant: User, monkeypatch: pytest.MonkeyPatch, exports: list
) -> None:
    _stub_docs(monkeypatch)
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)

    assert _client(hr_user).get(_url(hired, order, "document")).status_code == 404
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.REGISTERED)
    denied = _client(accountant).get(_url(hired, order, "document"))
    assert denied.status_code == 403
    assert denied.json() == {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
    assert exports == []


def test_signing_image_any_visible_user_and_no_log(
    hired: Employee, hr_user: User, accountant: User, order_root: Path, exports: list
) -> None:
    order = _hire_order(hired)
    _with_signing(order)
    png = OrderSigning.objects.get(order=order).image.read()

    for user in (accountant, hr_user):  # any user who may see the employee
        response = _client(user).get(_url(hired, order, "signing-image"))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert _body(response) == png
    assert exports == []  # the signing picture is not logged


def test_my_signature_only_own_and_404_when_none(hr_user: User, accountant: User) -> None:
    assert _client(hr_user).get("/api/v1/me/signature").status_code == 404  # none saved yet
    order_signing.save_signature(hr_user, _png())

    response = _client(hr_user).get("/api/v1/me/signature")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "private, no-store"
    assert _body(response) == order_signing.saved_signature_png(hr_user)

    stranger = _client(accountant).get("/api/v1/me/signature")  # only the requester's own row
    assert stranger.status_code == 404
    assert stranger.json()["form_errors"] == [NOT_FOUND]


def test_my_signature_delete_removes_row_and_is_post_only(hr_user: User) -> None:
    order_signing.save_signature(hr_user, _png())
    client = _client(hr_user)

    assert client.get("/api/v1/me/signature/delete").status_code == 405
    response = client.post("/api/v1/me/signature/delete")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "HX-Refresh" not in response
    assert order_signing.saved_signature_png(hr_user) is None
    assert client.get("/api/v1/me/signature").status_code == 404


def test_file_routes_json_is_valid_for_error_bodies(hired: Employee, hr_user: User) -> None:
    """A 404 from a file route is the API's own error shape, not a Django page."""
    response = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/orders/999999/document")
    assert response.status_code == 404
    assert json.loads(response.content) == {"field_errors": {}, "form_errors": [NOT_FOUND]}

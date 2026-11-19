"""The order pop-up routes: GET/POST .../orders/{order_id}/edit (the number, date and text), GET/POST .../upload (the
signed scan) and GET .../history (the order's activity). A refusal answers 200 with ok false and writes nothing; a
missing right is 403 (code "forbidden"); an employee or order outside the user's scope, a signed or cancelled order
(for edit) are 404."""

import base64
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from employees.models import Employee, HrOrder, OrderSigning, OrderState
from employees.services import events, history, macs_writes, order_docs, order_popups, order_signing, orders
from employees.tests.conftest import hire_values
from employees.tests.helpers import next_order_number, record_signed
from employees.tests.test_order_docs import _need_pdf_font
from employees.views import ORDER_WARNING_KEY
from macs.models import Command
from PIL import Image

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NOT_FOUND = "Хуудас олдсонгүй"
FORBIDDEN = "Хандах эрх байхгүй."
UPLOAD_TITLE = "Гарын үсэгтэй файл хавсаргах"
EDIT_HINT = "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү."
PDF = b"%PDF-1.4\n%test\n"
TXT_REFUSED = "Зөвхөн PDF, JPG эсвэл PNG файл оруулна уу."
SIGNED_REFUSED = "Зөвхөн бүртгэсэн тушаалд гарын үсэгтэй файл хавсаргана."


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("orders_api_hr", roles.HR)


@pytest.fixture
def accountant(db: None) -> User:
    return _user("orders_api_accountant", roles.ACCOUNTANT)


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
    """Where order scans are written: the temporary folder conftest sets for every test (never app/private)."""
    return Path(settings.ORDER_FILES_ROOT)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _url(employee: Employee, order: HrOrder, tail: str) -> str:
    return f"/api/v1/employees/{employee.pk}/orders/{order.pk}/{tail}"


def _post_json(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _hire_order(employee: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=employee, is_hire=True)


def _edit_values(**extra: str) -> dict[str, str]:
    values = {"number": "31", "date": "2026-03-02", "summary": "Шилжүүлэв", "issued_by": "Б. Дорж"}
    values.update(extra)
    return values


NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}


def test_anonymous_order_routes_answer_401(hired: Employee) -> None:
    """The ten concrete order routes, with no login: django_auth refuses each before the handler runs."""
    order = _hire_order(hired)
    anonymous = Client()  # a fresh client, never logged in

    responses = [
        anonymous.get(_url(hired, order, "edit")),
        _post_json(anonymous, _url(hired, order, "edit"), {"values": _edit_values()}),
        anonymous.get(_url(hired, order, "upload")),
        anonymous.post(_url(hired, order, "upload"), {}),
        anonymous.get(_url(hired, order, "history")),
        anonymous.get(_url(hired, order, "detail")),
        anonymous.get(_url(hired, order, "cancel")),
        _post_json(anonymous, _url(hired, order, "cancel"), {"values": {"reason": "тест"}}),
        anonymous.get(_url(hired, order, "sign")),
        _post_json(anonymous, _url(hired, order, "sign"), {"mode": "saved"}),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == NOT_LOGGED_IN
    order.refresh_from_db()
    assert order.number == "1"  # nothing changed


# --- The edit pop-up ---


def test_edit_get_suggests_number(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(number="", date=date.today())
    order.refresh_from_db()

    response = _client(hr_user).get(_url(hired, order, "edit"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "Тушаал: Ажилд орсон"
    assert body["hint"] == EDIT_HINT and body["multipart"] is False
    fields = {field["name"]: field for field in body["fields"]}
    assert {"number", "date", "summary", "issued_by"} <= set(fields)  # unprefixed names
    assert fields["number"]["value"] == orders.suggest_number(date.today())
    assert fields["number"]["required"] is True


def test_edit_post_ok_registers(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _post_json(_client(hr_user), _url(hired, order, "edit"), {"values": _edit_values()})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    order.refresh_from_db()
    assert order.number == "31" and order.date == date(2026, 3, 2)


def test_edit_post_refused_field_errors_unprefixed(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _post_json(_client(hr_user), _url(hired, order, "edit"), {"values": _edit_values(number="")})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False
    assert "number" in body["field_errors"] and body["field_errors"]["number"]
    order.refresh_from_db()
    assert order.number == "1"  # nothing written


def test_edit_post_ok_sets_order_warning_on_macs_clash(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    Command.objects.create(employee_id=hired.pk, number="31", date=date(2026, 3, 2), order_type=1)
    client = _client(hr_user)

    response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    assert response.json()["ok"] is True
    assert "MACS-д" in client.session[ORDER_WARNING_KEY]


def test_edit_signed_order_404(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    client = _client(hr_user)

    get_response = client.get(_url(hired, order, "edit"))
    post_response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    assert get_response.status_code == 404
    assert get_response.json()["form_errors"] == [NOT_FOUND]
    assert post_response.status_code == 404
    order.refresh_from_db()
    assert order.number == "1"  # the signed order is not changed


def test_edit_without_manage_403(hired: Employee, accountant: User) -> None:
    order = _hire_order(hired)
    client = _client(accountant)

    get_response = client.get(_url(hired, order, "edit"))
    post_response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    for response in (get_response, post_response):
        assert response.status_code == 403
        assert response.json() == {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
    order.refresh_from_db()
    assert order.number == "1"


# --- The upload pop-up ---


def test_upload_get_is_multipart_with_file_field(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _client(hr_user).get(_url(hired, order, "upload"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == UPLOAD_TITLE and body["multipart"] is True
    assert [field["name"] for field in body["fields"]] == ["file"]


def test_upload_post_ok_attaches(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)
    scan = SimpleUploadedFile("order.pdf", PDF, content_type="application/pdf")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": scan})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert order.file.name and (order_root / order.file.name).read_bytes().startswith(b"%PDF-")


def test_upload_wrong_type_ok_false_with_message(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)
    note = SimpleUploadedFile("note.txt", b"hello text", content_type="text/plain")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": note})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": False, "field_errors": {"file": [TXT_REFUSED]}, "form_errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED and not order.file
    assert not any(order_root.rglob("*.txt"))


def test_upload_missing_file_ok_false(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)

    response = _client(hr_user).post(_url(hired, order, "upload"), {})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False and list(body["field_errors"]) == ["file"]
    assert body["field_errors"]["file"]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED and not order.file


def test_upload_to_signed_order_is_form_error(hired: Employee, hr_user: User, order_root: Path) -> None:
    """The pop-up does not check the state (GET shows it); the service refuses at the save, as a form message."""
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    scan = SimpleUploadedFile("order.pdf", PDF, content_type="application/pdf")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": scan})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": False, "field_errors": {}, "form_errors": [SIGNED_REFUSED]}
    order.refresh_from_db()
    assert not order.file and order.state == OrderState.SIGNED


# --- The history ---


def test_history_returns_entries_newest_first(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    client = _client(hr_user)
    _post_json(client, _url(hired, order, "edit"), {"values": _edit_values(number="2")})

    response = client.get(_url(hired, order, "history"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "Тушаалын түүх: Ажилд орсон · № 2"
    entries = body["entries"]
    assert len(entries) >= 2
    assert entries[0]["by"] == "orders_api_hr"
    assert {"field": "Дугаар", "old": "1", "new": "2"} in entries[0]["changes"]
    assert entries[0]["at"] >= entries[-1]["at"]
    assert len(entries[0]["at"]) == 16  # "Y-m-d H:i"


def test_history_visible_to_non_manager_who_sees_employee(hired: Employee, accountant: User) -> None:
    order = _hire_order(hired)

    response = _client(accountant).get(_url(hired, order, "history"))

    assert response.status_code == 200, response.content
    assert response.json()["entries"]


def test_order_of_other_employee_404(hired: Employee, other: Employee, hr_user: User) -> None:
    foreign = _hire_order(hired)  # belongs to `hired`, asked through `other`
    client = _client(hr_user)

    for tail in ("edit", "upload", "history"):
        response = client.get(f"/api/v1/employees/{other.pk}/orders/{foreign.pk}/{tail}")
        assert response.status_code == 404, tail
        assert response.json()["form_errors"] == [NOT_FOUND]


def test_employee_outside_scope_404(hired: Employee) -> None:
    order = _hire_order(hired)
    outsider = _user("orders_api_outsider", roles.EMPLOYEE)  # sees no employee but its own

    response = _client(outsider).get(_url(hired, order, "history"))

    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]


# --- The order detail (GET .../orders/{order_id}/detail) ---


def _detail_url(employee: Employee, order: HrOrder) -> str:
    return _url(employee, order, "detail")


def _future() -> date:
    return timezone.localdate() + timedelta(days=30)


def _promotion(employee: Employee, actor: User, effective: date, number: str) -> HrOrder:
    """A position change, recorded and signed at once; its order is numbered `number`."""
    position = macs_writes.save_position("Ахлах нягтлан")
    record_signed(
        employee,
        type="promotion",
        effective=effective,
        changes={"position": position},
        salary=None,
        reason="Гүйцэтгэл",
        note="Тест тайлбар",
        by=actor,
        order_number=number,
    )
    return HrOrder.objects.get(employee=employee, event__isnull=False)


def test_detail_hire_order_shape(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    orders.register(order, number="15", date=date(2026, 1, 5), summary="Ажилд авав", issued_by="Б. Дорж", by=hr_user)
    order.refresh_from_db()

    response = _client(hr_user).get(_detail_url(hired, order))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "Ажилд авсан"
    assert body["employee_pk"] == hired.pk
    assert body["employee_name"] == hired.full_name and body["employee_code"] == hired.code
    assert body["status_chip"] is None and body["awaiting_note"] == ""
    assert body["order_heading"] == "Тушаал № 15 / 2026"
    assert body["state_chip"]["tone"] == "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900"
    assert [row["label"] for row in body["order_rows"]] == ["Төрөл", "Огноо", "Агуулга", "Гаргасан"]
    assert body["order_rows"][2]["value"] == "Ажилд авав"
    # A hire has no change: the date row, then the department and position row (no arrows).
    assert [row["label"] for row in body["change_rows"]] == ["Хүчинтэй огноо", "Хэлтэс, албан тушаал"]
    assert body["change_rows"][1]["value"] == "Санхүү · Нягтлан"
    assert body["change_rows"][1]["before"] == "" and body["change_rows"][1]["after"] == ""
    assert [row["arrow"] for row in body["change_rows"]] == [False, False]
    # The HR user has no salary right, so a hire scan is hidden (OQ-080).
    assert body["scan"] == {"note": "Зөвхөн цалингийн эрхтэй хэрэглэгч харна", "url": ""}
    assert body["signing"] is None and body["cancel_rows"] == []
    assert body["entries"] and body["entries"][0]["by"] == "orders_api_hr"


def test_detail_change_order_rows_arrow_and_reason_rows(hired: Employee, hr_user: User) -> None:
    change = _promotion(hired, hr_user, _future(), "16")

    response = _client(hr_user).get(_detail_url(hired, change))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == f"{change.event.get_type_display()} · {_future():%Y-%m-%d}"
    assert body["status_chip"] == {
        "label": "Төлөвлөсөн",
        "tone": "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800",
    }
    rows = body["change_rows"]
    assert rows[0]["label"] == "Хүчинтэй огноо"
    assert rows[0]["value"] == f"{_future():%Y-%m-%d}" and rows[0]["before"] == rows[0]["after"] == ""
    arrow = next(row for row in rows if row["after"] == "Ахлах нягтлан")
    assert arrow["before"] == "Нягтлан" and arrow["value"] == "" and arrow["arrow"] is True
    assert [row["arrow"] for row in rows if row is not arrow] == [False] * (len(rows) - 1)
    assert {"label": "Шалтгаан", "value": "Гүйцэтгэл", "before": "", "after": "", "arrow": False} in rows
    assert {"label": "Тайлбар", "value": "Тест тайлбар", "before": "", "after": "", "arrow": False} in rows
    assert [row["label"] for row in rows][-2:] == ["Шалтгаан", "Тайлбар"]
    assert body["order_heading"].startswith("Тушаал № 16")


def test_detail_awaiting_signature_note_and_chip(hired: Employee, hr_user: User) -> None:
    position = macs_writes.save_position("Ахлах нягтлан")
    events.record(
        hired,
        type="promotion",
        effective=_future(),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=hr_user,
        order_number="41",
    )
    order = HrOrder.objects.get(employee=hired, event__isnull=False)

    response = _client(hr_user).get(_detail_url(hired, order))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status_chip"]["label"] == "Гарын үсэг хүлээж байна"
    assert "whitespace-nowrap" in body["status_chip"]["tone"] and "text-amber-900" in body["status_chip"]["tone"]
    assert body["awaiting_note"] == "Тушаал гарын үсэгтэй болмогц хүчин төгөлдөр болно"


def test_detail_cancelled_order_cancel_rows_link_other_order(hired: Employee, hr_user: User) -> None:
    hire = _hire_order(hired)
    orders.register(hire, number="15", date=date(2026, 1, 5), summary="", issued_by="", by=hr_user)
    change = _promotion(hired, hr_user, date(2026, 3, 1), "16")  # in the past: effective, so no status chip
    HrOrder.objects.filter(pk=hire.pk).update(state=OrderState.CANCELLED, cancel_reason="тест", cancel_order_no="16")
    hire.refresh_from_db()
    client = _client(hr_user)

    cancelled = client.get(_detail_url(hired, hire)).json()
    assert cancelled["state_chip"]["tone"] == "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
    assert cancelled["cancel_rows"] == [
        {
            "label": "Цуцалсан",
            "reason": "тест",
            "text_prefix": " · цуцлах тушаал: ",
            "order_pk": change.pk,
            "link_text": "№ 16",
            "suffix": "",
        }
    ]

    canceller = client.get(_detail_url(hired, change)).json()
    assert canceller["status_chip"] is None
    assert canceller["cancel_rows"] == [
        {
            "label": "Цуцалсан тушаал",
            "reason": "",
            "text_prefix": "",
            "order_pk": hire.pk,
            "link_text": "№ 15",
            "suffix": " тушаалыг цуцалсан",
        }
    ]


def test_detail_scan_note_for_user_without_salary_right(hired: Employee, hr_user: User, accountant: User) -> None:
    order = _hire_order(hired)

    hidden = _client(hr_user).get(_detail_url(hired, order)).json()["scan"]
    assert hidden == {"note": "Зөвхөн цалингийн эрхтэй хэрэглэгч харна", "url": ""}

    empty = _client(accountant).get(_detail_url(hired, order)).json()["scan"]
    assert empty == {"note": "хавсаргаагүй", "url": ""}

    HrOrder.objects.filter(pk=order.pk).update(file="orders/test/scan.pdf")
    attached = _client(accountant).get(_detail_url(hired, order)).json()["scan"]
    assert attached == {"note": "Файл харах", "url": _url(hired, order, "file")}


def test_detail_signing_block_has_image_url(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    signed_at = timezone.now()
    OrderSigning.objects.create(
        order=order,
        signer=hr_user,
        signer_name="Б. Дорж",
        signed_at=signed_at,
        method=OrderSigning.Method.DRAWN,
        image="signing/2026/test.png",
        pdf_sha256="0" * 64,
    )

    body = _client(hr_user).get(_detail_url(hired, order)).json()

    when = timezone.localtime(signed_at).strftime("%Y-%m-%d %H:%M")
    assert body["signing"] == {
        "text": f"Б. Дорж · {when} · Шинээр зурсан гарын үсэг",
        "image_url": _url(hired, order, "signing-image"),
    }


@pytest.mark.parametrize(
    ("state", "who", "word", "upload", "edit", "cancel"),
    [
        (OrderState.PENDING, "hr", True, False, True, False),
        (OrderState.REGISTERED, "hr", True, True, True, True),
        (OrderState.SIGNED, "hr", True, False, False, False),
        (OrderState.CANCELLED, "hr", False, False, False, False),
        (OrderState.PENDING, "readonly", False, False, False, False),
        (OrderState.REGISTERED, "readonly", False, False, False, False),
    ],
)
def test_detail_actions_by_state_and_right(
    hired: Employee,
    hr_user: User,
    accountant: User,
    state: str,
    who: str,
    word: bool,
    upload: bool,
    edit: bool,
    cancel: bool,
) -> None:
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=state)
    user = hr_user if who == "hr" else accountant

    actions = _client(user).get(_detail_url(hired, order)).json()["actions"]

    assert bool(actions["word_url"]) is word and bool(actions["pdf_url"]) is word
    if word:
        assert actions["word_url"] == _url(hired, order, "document")
        assert actions["pdf_url"] == _url(hired, order, "document/pdf")
    assert actions["upload"] is upload
    assert actions["edit"] is edit
    assert actions["cancel_order"] is cancel
    assert actions["cancel_event_id"] is None
    assert actions["sign"] is False  # HR has no sign switch, and a hire order shows a salary


def test_detail_cancel_event_id_for_open_change(hired: Employee, hr_user: User) -> None:
    change = _promotion(hired, hr_user, _future(), "16")

    actions = _client(hr_user).get(_detail_url(hired, change)).json()["actions"]

    assert actions["cancel_event_id"] == change.event_id
    assert actions["cancel_order"] is False  # a change is cancelled through its event, not as an order


def test_detail_404_foreign_employee_and_order(hired: Employee, other: Employee, hr_user: User) -> None:
    foreign = _hire_order(hired)  # belongs to `hired`, asked through `other`
    outsider = _user("orders_detail_outsider", roles.EMPLOYEE)

    responses = [
        _client(hr_user).get(f"/api/v1/employees/{other.pk}/orders/{foreign.pk}/detail"),
        _client(outsider).get(_detail_url(hired, foreign)),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["form_errors"] == [NOT_FOUND]


# --- order cancel and sign (Task 7) ----------------------------------------------------------------------------------

SIGN_TITLE = "Гарын үсэг зурах"
SAVED_MISSING = "Хадгалсан гарын үсэг алга. Шинээр зурна уу."
DRAW_ERROR = "Гарын үсгээ зурна уу."
TEMPLATE_ERROR = "Тушаалын загвар олдсонгүй эсвэл эвдэрсэн байна."
SAVED_SIGNATURE_URL = "/api/v1/me/signature"
DAY = date(2026, 3, 1)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), (20, 20, 20, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(_png()).decode()


def _signer(name: str) -> User:
    """An HR user holding the signing switch (HR itself does not hold it by default). HR has no salary right."""
    user = _user(name, roles.HR)
    user.user_permissions.add(Permission.objects.get(codename="sign_orders", content_type__app_label="accounts"))
    return User.objects.get(pk=user.pk)


def _registered_hire(employee: Employee, actor: User) -> HrOrder:
    """The hire order, registered (number 30) and still open: it can be cancelled or signed."""
    order = _hire_order(employee)
    orders.register(order, number="30", date=DAY, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def _registered_change(employee: Employee, actor: User) -> HrOrder:
    """A registered transfer order (number 21) with a change behind it."""
    event = events.record(
        employee,
        type="transfer",
        effective=DAY,
        changes={"department": macs_writes.save_department("Инженер")},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number=next_order_number(),
    )
    order = HrOrder.objects.get(event=event)
    orders.register(order, number="21", date=DAY, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def test_cancel_get_shape(hired: Employee, hr_user: User) -> None:
    order = _registered_hire(hired, hr_user)

    body = _client(hr_user).get(_url(hired, order, "cancel")).json()

    assert body["title"] == f"Тушаал цуцлах: {order.get_order_type_display()} № {order.number}"
    assert body["hint"] == order_popups.CANCEL_HINT
    assert body["submit_label"] == "Цуцлах"
    assert body["multipart"] is False
    assert [field["name"] for field in body["fields"]] == ["reason"]


def test_cancel_post_empty_reason_ok_false_field_error(hired: Employee, hr_user: User) -> None:
    order = _registered_hire(hired, hr_user)

    response = _post_json(_client(hr_user), _url(hired, order, "cancel"), {"values": {"reason": ""}})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "reason" in body["field_errors"]
    assert body["form_errors"] == []
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_cancel_post_cancels_and_invalidations_visible_in_work(hired: Employee, hr_user: User) -> None:
    order = _registered_hire(hired, hr_user)
    client = _client(hr_user)

    response = _post_json(client, _url(hired, order, "cancel"), {"values": {"reason": "тест"}})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.CANCELLED
    assert client.get(f"/api/v1/employees/{hired.pk}/work").status_code == 200
    detail = client.get(_detail_url(hired, order)).json()  # the pop-up the page reads after the cancel
    assert detail["state_chip"]["label"] == OrderState.CANCELLED.label
    assert detail["actions"]["cancel_order"] is False


def test_cancel_404_for_event_or_signed_order(hired: Employee, hr_user: User) -> None:
    change = _registered_change(hired, hr_user)
    hire = _registered_hire(hired, hr_user)
    HrOrder.objects.filter(pk=hire.pk).update(state=OrderState.SIGNED)
    client = _client(hr_user)

    responses = [
        client.get(_url(hired, change, "cancel")),
        _post_json(client, _url(hired, change, "cancel"), {"values": {"reason": "тест"}}),
        client.get(_url(hired, hire, "cancel")),
        _post_json(client, _url(hired, hire, "cancel"), {"values": {"reason": "тест"}}),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["form_errors"] == [NOT_FOUND]


def test_cancel_403_without_manage(hired: Employee, hr_user: User, accountant: User) -> None:
    order = _registered_hire(hired, hr_user)
    client = _client(accountant)

    assert client.get(_url(hired, order, "cancel")).status_code == 403
    response = _post_json(client, _url(hired, order, "cancel"), {"values": {"reason": "тест"}})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_sign_get_has_saved_flag_and_title(hired: Employee, hr_user: User) -> None:
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_signer")
    client = _client(signer)
    title = f"{SIGN_TITLE} · № 21"

    assert client.get(_url(hired, order, "sign")).json() == {"title": title, "has_saved": False, "saved_url": ""}
    order_signing.save_signature(signer, _png())
    assert client.get(_url(hired, order, "sign")).json() == {
        "title": title,
        "has_saved": True,
        "saved_url": SAVED_SIGNATURE_URL,
    }


def test_sign_get_403_when_hire_order_without_salary_right(hired: Employee, hr_user: User) -> None:
    order = _registered_hire(hired, hr_user)
    signer = _signer("orders_api_nosalary")

    response = _client(signer).get(_url(hired, order, "sign"))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_sign_post_saved_ok(hired: Employee, hr_user: User) -> None:
    _need_pdf_font()
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_saved")
    order_signing.save_signature(signer, _png())

    response = _post_json(_client(signer), _url(hired, order, "sign"), {"mode": "saved"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert OrderSigning.objects.get(order=order).method == OrderSigning.Method.SAVED


def test_sign_post_saved_deleted_meanwhile_ok_false_message(hired: Employee, hr_user: User) -> None:
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_gone")
    order_signing.save_signature(signer, _png())
    order_signing.delete_saved_signature(signer)  # deleted in another tab meanwhile

    response = _post_json(_client(signer), _url(hired, order, "sign"), {"mode": "saved"})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "errors": [SAVED_MISSING]}
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_sign_post_drawn_empty_ok_false(hired: Employee, hr_user: User) -> None:
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_empty")

    response = _post_json(_client(signer), _url(hired, order, "sign"), {"mode": "drawn", "signature": ""})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "errors": [DRAW_ERROR]}
    assert not OrderSigning.objects.filter(order=order).exists()


def test_sign_post_drawn_remember_saves(hired: Employee, hr_user: User) -> None:
    _need_pdf_font()
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_remember")

    response = _post_json(
        _client(signer),
        _url(hired, order, "sign"),
        {"mode": "drawn", "signature": _data_url(), "remember": True},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert OrderSigning.objects.get(order=order).method == OrderSigning.Method.DRAWN
    assert order_signing.saved_signature_png(signer) is not None


def test_sign_post_404_after_order_signed(hired: Employee, hr_user: User) -> None:
    _need_pdf_font()
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_twice")
    client = _client(signer)
    first = _post_json(client, _url(hired, order, "sign"), {"mode": "drawn", "signature": _data_url()})
    assert first.json() == {"ok": True, "errors": []}

    again = _post_json(client, _url(hired, order, "sign"), {"mode": "drawn", "signature": _data_url()})

    assert client.get(_url(hired, order, "sign")).status_code == 404
    assert again.status_code == 404
    assert again.json()["form_errors"] == [NOT_FOUND]
    assert OrderSigning.objects.filter(order=order).count() == 1


def test_sign_post_broken_template_ok_false(hired: Employee, hr_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _registered_change(hired, hr_user)
    signer = _signer("orders_api_broken")

    def broken(*_args: Any, **_kwargs: Any) -> bytes:
        raise order_docs.OrderDocError("missing")

    monkeypatch.setattr(order_docs, "render_signed_pdf", broken)
    response = _post_json(_client(signer), _url(hired, order, "sign"), {"mode": "drawn", "signature": _data_url()})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "errors": [TEMPLATE_ERROR]}
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_sign_get_and_post_403_without_sign_switch(hired: Employee, hr_user: User) -> None:
    """HR sees the order but does not hold the signing switch: both the pop-up and the signing answer 403."""
    order = _registered_change(hired, hr_user)
    client = _client(hr_user)

    get_response = client.get(_url(hired, order, "sign"))
    post_response = _post_json(client, _url(hired, order, "sign"), {"mode": "drawn", "signature": _data_url()})

    for response in (get_response, post_response):
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_sign_post_hire_without_salary_right_ok_false_writes_nothing(hired: Employee, hr_user: User) -> None:
    """A hire order shows the salary, so a signer without the salary right is refused by the service (200, ok false)."""
    order = _registered_hire(hired, hr_user)
    signer = _signer("orders_api_hire_nosalary_post")

    response = _post_json(_client(signer), _url(hired, order, "sign"), {"mode": "drawn", "signature": _data_url()})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "errors": [order_signing.SIGN_NEEDS_SALARY]}
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_cancel_and_sign_404_for_foreign_order(hired: Employee, other: Employee, hr_user: User) -> None:
    """A registered order of `hired`, asked through `other`: 404 on cancel and sign, before any right is checked."""
    foreign = _registered_hire(hired, hr_user)
    client = _client(hr_user)
    base = f"/api/v1/employees/{other.pk}/orders/{foreign.pk}"

    responses = [
        client.get(f"{base}/cancel"),
        _post_json(client, f"{base}/cancel", {"values": {"reason": "тест"}}),
        client.get(f"{base}/sign"),
        _post_json(client, f"{base}/sign", {"mode": "saved"}),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["form_errors"] == [NOT_FOUND]
    foreign.refresh_from_db()
    assert foreign.state == OrderState.REGISTERED


def test_cancel_and_sign_404_for_employee_outside_scope(hired: Employee, hr_user: User) -> None:
    """An employee who sees no one but themselves gets 404 on the cancel and sign routes of another employee."""
    order = _registered_hire(hired, hr_user)
    outsider = _user("orders_cancel_sign_outsider", roles.EMPLOYEE)
    client = _client(outsider)

    responses = [
        client.get(_url(hired, order, "cancel")),
        _post_json(client, _url(hired, order, "cancel"), {"values": {"reason": "тест"}}),
        client.get(_url(hired, order, "sign")),
        _post_json(client, _url(hired, order, "sign"), {"mode": "saved"}),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["form_errors"] == [NOT_FOUND]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED

"""The order panel: register on a change or hire, edit, upload the signed scan, view it, cancel."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from macs.models import Command

from employees.models import CompanySettings, Employee, EventType, HrOrder, OrderState
from employees.services import orders

from .conftest import link_login
from .test_event_views import promote_data, url
from .test_hire_personal import hire_post, place  # noqa: F401
from .test_views import login_as

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def order_of(emp: Employee) -> HrOrder:
    return HrOrder.objects.filter(employee=emp, event__isnull=False).get()


def registered_hire(emp: Employee, actor: User) -> HrOrder:
    order = HrOrder.objects.get(employee=emp, is_hire=True)
    return orders.register(order, number="15", date=date(2026, 1, 5), summary="Ажилд авав", issued_by="", by=actor)


def edit_url(emp: Employee, order: HrOrder, tail: str = "") -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/{tail}"


def test_event_form_with_number_registers(hr: Client, hired: Employee) -> None:
    data = promote_data(hired, **{"order-number": "77", "order-date": "2026-02-01", "order-summary": "Дэвшүүлэв"})
    assert hr.post(url(hired, "promotion"), data).status_code == 204
    order = order_of(hired)
    assert (order.state, order.number, order.summary) == (OrderState.REGISTERED, "77", "Дэвшүүлэв")


def test_event_form_without_number_is_pending(hr: Client, hired: Employee) -> None:
    assert hr.post(url(hired, "promotion"), promote_data(hired)).status_code == 204
    assert order_of(hired).state == OrderState.PENDING


def test_event_form_shows_order_fields_and_default_issuer(hr: Client, hired: Employee, settings: Any) -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={"director_name": "Д.Бат"})
    body = hr.get(url(hired, "promotion")).content.decode()
    assert 'name="order-number"' in body and 'value="Д.Бат"' in body
    assert 'name="order-number"' not in hr.get(url(hired, "leave_start")).content.decode()


def test_event_form_bad_order_number_shows_error(hr: Client, hired: Employee) -> None:
    data = promote_data(hired, **{"order-number": "77", "order-date": ""})
    response = hr.post(url(hired, "promotion"), data)
    assert response.status_code == 200 and "Дугаар болон огноог хамт" in response.content.decode()
    assert not HrOrder.objects.filter(event__isnull=False).exists()


def test_hire_form_creates_order(hr: Client, place: dict[str, Any]) -> None:  # noqa: F811
    data = hire_post(place, **{"order-number": "5", "order-date": "2026-01-05", "order-summary": "Ажилд авав"})
    assert hr.post("/employees/new/", data).status_code == 302
    order = HrOrder.objects.get(is_hire=True)
    assert (order.state, order.number) == (OrderState.REGISTERED, "5")
    assert Command.objects.filter(number="5").exists()


def test_hire_form_without_number_is_pending(hr: Client, place: dict[str, Any]) -> None:  # noqa: F811
    assert hr.post("/employees/new/", hire_post(place)).status_code == 302
    assert HrOrder.objects.get(is_hire=True).state == OrderState.PENDING


def test_edit_registered_order(hr: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    assert hr.get(edit_url(hired, order)).status_code == 200
    data = {"number": "16", "date": "2026-01-06", "summary": "Засав", "issued_by": "Б.Дорж"}
    assert hr.post(edit_url(hired, order), data).status_code == 204
    order.refresh_from_db()
    assert (order.number, order.summary, order.issued_by) == ("16", "Засав", "Б.Дорж")


def test_edit_pending_order_registers_it(hr: Client, hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    data = {"number": "3", "date": "2026-01-05", "summary": "", "issued_by": ""}
    assert hr.post(edit_url(hired, order), data).status_code == 204
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_edit_duplicate_number_shows_error(hr: Client, hired: Employee, actor: User) -> None:
    registered_hire(hired, actor)
    hr.post(url(hired, "promotion"), promote_data(hired))
    order = order_of(hired)
    data = {"number": "15", "date": "2026-01-20", "summary": "", "issued_by": ""}
    response = hr.post(edit_url(hired, order), data)
    assert response.status_code == 200 and "аль хэдийн ашиглагдсан" in response.content.decode()


def test_upload_signs_order(hr: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    scan = SimpleUploadedFile("scan.pdf", PDF, content_type="application/pdf")
    assert hr.post(edit_url(hired, order, "upload/"), {"file": scan}).status_code == 204
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED and order.file
    got = hr.get(edit_url(hired, order, "file/"))
    assert got.status_code == 200 and b"".join(got.streaming_content) == PDF  # type: ignore[attr-defined]
    assert got["Content-Type"] == "application/pdf" and got["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    ("name", "content"),
    [("a.pdf", b"not a pdf at all"), ("a.exe", b"MZ\x90\x00"), ("a.pdf", b"")],
)
def test_upload_rejects_wrong_content(hr: Client, hired: Employee, actor: User, name: str, content: bytes) -> None:
    order = registered_hire(hired, actor)
    response = hr.post(edit_url(hired, order, "upload/"), {"file": SimpleUploadedFile(name, content)})
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_upload_rejects_big_file(hr: Client, hired: Employee, actor: User, settings: Any) -> None:
    settings.ORDER_FILE_MAX_MB = 1
    order = registered_hire(hired, actor)
    big = SimpleUploadedFile("a.pdf", PDF + b"0" * (1024 * 1024))
    response = hr.post(edit_url(hired, order, "upload/"), {"file": big})
    assert response.status_code == 200 and "хэт том" in response.content.decode()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_upload_pending_order_refused(hr: Client, hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    response = hr.post(edit_url(hired, order, "upload/"), {"file": SimpleUploadedFile("a.pdf", PDF)})
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.state == OrderState.PENDING


def test_signed_order_cannot_be_edited(hr: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", PDF), by=actor)
    data = {"number": "99", "date": "2026-01-06", "summary": "", "issued_by": ""}
    assert hr.post(edit_url(hired, order), data).status_code == 404
    assert hr.get(edit_url(hired, order)).status_code == 404


def test_file_view_hidden_from_other_employees(client: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", PDF), by=actor)
    login_as(client, "Employee", "someone")  # linked to nobody
    assert client.get(edit_url(hired, order, "file/")).status_code == 404


def test_file_view_allowed_for_the_employee_and_missing_file_404(client: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    link_login(hired, login_as(client, "Employee", "me"))
    assert client.get(edit_url(hired, order, "file/")).status_code == 404  # nothing uploaded yet
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", PDF), by=actor)
    assert client.get(edit_url(hired, order, "file/")).status_code == 200


def test_viewer_cannot_edit(client: Client, hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    link_login(hired, login_as(client, "Employee", "me"))
    data = {"number": "99", "date": "2026-01-06", "summary": "", "issued_by": ""}
    assert client.get(edit_url(hired, order)).status_code == 403
    assert client.post(edit_url(hired, order), data).status_code == 403
    assert client.post(edit_url(hired, order, "upload/"), {}).status_code == 403


def test_employee_page_lists_orders(hr: Client, hired: Employee, actor: User) -> None:
    registered_hire(hired, actor)
    Command.objects.create(employee_id=hired.pk, number="A-9", date=date(2020, 5, 1), summary="Хуучин тушаал")
    body = hr.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ажилд авав" in body and "№ 15" in body
    assert "Хуучин тушаал" in body and "Хуучин програм" in body
    assert "A-9" in body


def test_employee_page_pending_order_says_number_pending(hr: Client, hired: Employee) -> None:
    assert "Дугаар оруулаагүй" in hr.get(f"/employees/{hired.pk}/").content.decode()


def test_history_row_shows_order_number(hr: Client, hired: Employee) -> None:
    hr.post(url(hired, "promotion"), promote_data(hired, **{"order-number": "77", "order-date": "2026-02-01"}))
    assert "№ 77" in hr.get(f"/employees/{hired.pk}/").content.decode()


def test_cancel_form_requires_number_for_signed(hr: Client, hired: Employee, actor: User) -> None:
    hr.post(url(hired, "promotion"), promote_data(hired, **{"order-number": "77", "order-date": "2026-02-01"}))
    event = hired.events.get(type=EventType.PROMOTION)
    order = order_of(hired)
    cancel = f"/employees/{hired.pk}/event/{event.pk}/cancel/"
    assert "cancel_order_no" not in hr.get(cancel).content.decode()  # registered, not signed: no number asked
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", PDF), by=actor)
    assert 'name="cancel_order_no"' in hr.get(cancel).content.decode()
    response = hr.post(cancel, {"reason": "Буруу"})
    assert response.status_code == 200 and "дугаар" in response.content.decode().lower()
    assert hr.post(cancel, {"reason": "Буруу", "cancel_order_no": "78"}).status_code == 204
    order.refresh_from_db()
    assert (order.state, order.cancel_order_no) == (OrderState.CANCELLED, "78")


def test_order_fields_length_error_is_mongolian() -> None:
    from employees.forms import OrderFieldsForm

    form = OrderFieldsForm(data={"number": "x" * 11, "summary": "y" * 51, "issued_by": "z" * 26})
    assert not form.is_valid()
    for name in ("number", "summary", "issued_by"):
        assert "тэмдэгт" in form.errors[name][0], form.errors[name]


def test_cancel_signed_missing_number_names_the_field() -> None:
    from employees.forms import CancelEventForm

    form = CancelEventForm(data={"reason": "алдаа"}, signed=True)
    assert not form.is_valid()
    assert "цуцлах шинэ тушаалын дугаар" in str(form.errors["cancel_order_no"][0]).lower()


def test_suggest_number_is_highest_plain_number_of_the_year_plus_one(hired: Employee, actor: User) -> None:
    assert orders.suggest_number(date(2026, 3, 1)) == "1"
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    assert orders.suggest_number(date(2026, 3, 1)) == "13"
    assert orders.suggest_number(date(2027, 3, 1)) == "1"  # numbers are counted per calendar year


def test_suggest_number_ignores_lettered_numbers_and_never_guesses_for_letters_only(
    hired: Employee, actor: User
) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    orders.register(order, number="А/54", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    assert orders.suggest_number(date(2026, 3, 1)) == ""


def test_order_edit_prefills_a_suggested_number_only_for_a_pending_order(
    hr: Client, hired: Employee, actor: User
) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    body = hr.get(edit_url(hired, order)).content.decode()
    assert 'value="1"' in body and "автоматаар санал болгосон" in body
    orders.register(order, number="7", date=date.today(), summary="", issued_by="", by=actor)
    body = hr.get(edit_url(hired, order)).content.decode()
    assert 'value="7"' in body and "автоматаар санал болгосон" not in body


def test_suggest_number_counts_old_program_orders(hired: Employee) -> None:
    Command.objects.create(employee_id=hired.pk, number="20", date=date(2026, 6, 1), summary="Хуучин")
    Command.objects.create(employee_id=hired.pk, number="99", date=date(2025, 6, 1), summary="Өмнөх жил")
    assert orders.suggest_number(date(2026, 7, 1)) == "21"


def test_order_suggest_endpoint_returns_number_and_date(hr: Client, hired: Employee, actor: User) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    data = hr.get("/employees/orders/suggest/", {"date": "2026-03-01"}).json()
    assert data == {"number": "13", "date": "2026-03-01"}  # a typed date picks the year and is echoed back
    data = hr.get("/employees/orders/suggest/", {"date": "2027-03-01"}).json()
    assert data["number"] == "1"
    assert hr.get("/employees/orders/suggest/").json()["date"] == date.today().isoformat()
    assert hr.get("/employees/orders/suggest/", {"date": "junk"}).json()["date"] == date.today().isoformat()


def test_order_suggest_endpoint_needs_a_login(client: Client) -> None:
    assert client.get("/employees/orders/suggest/").status_code == 302


def test_suggest_button_is_on_the_change_form_and_the_edit_pop_up(hr: Client, hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    for body in (
        hr.get(url(hired, "promotion")).content.decode(),
        hr.get(edit_url(hired, order)).content.decode(),
    ):
        assert body.count("data-order-suggest=") == 1 and "/employees/orders/suggest/" in body
    assert "data-order-suggest=" not in hr.get(url(hired, "leave_start")).content.decode()

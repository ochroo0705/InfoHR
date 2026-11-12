"""The on-screen signing pop-up and its four views (order-signing board, Task 7a): who may open it, what it shows,
what a POST writes, the saved signature pictures and the order pop-up's signing block."""

import base64
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.test import Client
from macs.models import Branch
from PIL import Image

from employees.models import Employee, HrOrder, OrderSigning, OrderState, OrderTemplate, SavedSignature
from employees.services import events, history, macs_writes, order_docs, order_signing, orders
from employees.services.order_signing import SIGN_NEEDS_SALARY, save_signature
from employees.tests.conftest import hire_values
from employees.tests.test_order_docs import _need_pdf_font
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
SIGN_TITLE = "Гарын үсэг зурах"
SAVED_BUTTON = "Баталгаажуулж гарын үсэг зурах"
REDRAW_BUTTON = "Өөр гарын үсэг зурах"
DRAW_ERROR = "Гарын үсгээ зурна уу."
SAVED_MISSING = "Хадгалсан гарын үсэг алга. Шинээр зурна уу."
TEMPLATE_ERROR = "Тушаалын загвар олдсонгүй эсвэл эвдэрсэн байна."
DELETE_QUESTION = "Хадгалсан гарын үсгийг устгах уу?"


def _png(color: tuple[int, int, int, int] = (20, 20, 20, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(_png()).decode()


def _grant_sign(user: User) -> User:
    user.user_permissions.add(Permission.objects.get(codename="sign_orders", content_type__app_label="accounts"))
    return User.objects.get(pk=user.pk)


def sign_url(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/sign/"


def image_url(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/signing-image/"


def _registered_transfer(emp: Employee, actor: User, number: str = "21", day: date = DAY) -> HrOrder:
    event = events.record(
        emp,
        type="transfer",
        effective=day,
        changes={"department": macs_writes.save_department("Инженер")},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = HrOrder.objects.get(event=event)
    orders.register(order, number=number, date=day, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def _client_for(role: str, name: str) -> tuple[Client, User]:
    client = Client()
    user = login_as(client, role, name)
    return client, user


@pytest.fixture
def signer_client(actor: User) -> tuple[Client, User]:
    """An HR user holding the signing switch (HR itself does not hold it by default)."""
    client, user = _client_for("HR", "hr_signer")
    return client, _grant_sign(user)


# --- who may open and sign ----------------------------------------------------------------------------------------


def test_user_without_the_switch_is_refused_and_signs_nothing(hired: Employee, actor: User) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = _client_for("HR", "hr_noswitch")
    assert client.get(sign_url(hired, order)).status_code == 403
    posted = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert posted.status_code == 403
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_pop_up_has_the_title_and_the_board_without_a_saved_signature(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    body = client.get(sign_url(hired, order)).content.decode()
    assert SIGN_TITLE in body
    assert "data-signature-pad" in body and "data-signature-form" in body
    assert 'name="mode" value="drawn"' in body
    assert SAVED_BUTTON not in body and REDRAW_BUTTON not in body
    assert 'data-sign-section="saved"' not in body
    assert "hidden" not in body.split('data-sign-section="draw"')[1].split(">")[0]  # the board is shown


def test_pop_up_with_a_saved_signature_shows_the_saved_controls(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, user = signer_client
    save_signature(user, _png())
    body = client.get(sign_url(hired, order)).content.decode()
    assert SAVED_BUTTON in body and REDRAW_BUTTON in body
    assert 'data-sign-section="saved"' in body
    assert 'name="mode" value="saved"' in body
    assert 'src="/employees/signature/image/"' in body
    assert "/employees/signature/delete/" in body
    draw_tag = body.split('data-sign-section="draw"')[1].split(">")[0]
    assert "hidden" in draw_tag  # the board waits behind «Өөр гарын үсэг зурах»


def test_drawn_post_signs_refreshes_and_can_remember(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, actor)
    client, user = signer_client
    response = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url(), "remember": "1"})
    assert response.status_code == 204
    assert response["HX-Refresh"] == "true"
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert OrderSigning.objects.get(order=order).method == OrderSigning.Method.DRAWN
    assert order_signing.saved_signature_png(user) is not None


def test_saved_post_without_a_saved_signature_rerenders_with_error(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    response = client.post(sign_url(hired, order), {"mode": "saved"})
    assert response.status_code == 200
    body = response.content.decode()
    assert SAVED_MISSING in body and SIGN_TITLE in body
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_empty_drawing_shows_the_draw_message_and_writes_nothing(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    response = client.post(sign_url(hired, order), {"mode": "drawn", "signature": ""})
    assert response.status_code == 200
    assert DRAW_ERROR in response.content.decode()
    assert not OrderSigning.objects.filter(order=order).exists()


def test_hire_order_without_the_salary_right_shows_the_refusal(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    orders.register(order, number="30", date=DAY, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    client, _ = signer_client  # HR: no salary right
    response = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert response.status_code == 200
    assert SIGN_NEEDS_SALARY in response.content.decode()
    assert not OrderSigning.objects.filter(order=order).exists()


def test_employee_outside_the_scope_is_404(hired: Employee, actor: User) -> None:
    order = _registered_transfer(hired, actor)
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    client, user = _client_for("HR", "hr_limited")
    _grant_sign(user)
    AccessScope.objects.create(user=user, limited=True, branch_ids=[north.pk])
    Employee.objects.filter(pk=hired.pk).update(branch_id=south.pk)
    assert client.get(sign_url(hired, order)).status_code == 404
    Employee.objects.filter(pk=hired.pk).update(branch_id=north.pk)
    assert client.get(sign_url(hired, order)).status_code == 200  # the control: inside the scope


# --- the signing picture of an order -------------------------------------------------------------------------------


def test_signing_image_is_served_to_users_who_see_the_employee(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    assert client.get(image_url(hired, order)).status_code == 404  # not signed yet
    client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    got = client.get(image_url(hired, order))
    assert got.status_code == 200
    assert got["Content-Type"] == "image/png"
    assert got["X-Content-Type-Options"] == "nosniff"
    assert b"".join(got.streaming_content).startswith(b"\x89PNG")  # type: ignore[attr-defined]
    stranger, _ = _client_for("Employee", "emp_stranger")  # sees only their own record
    assert stranger.get(image_url(hired, order)).status_code == 404


# --- the saved signature picture and its delete ----------------------------------------------------------------


def test_my_signature_image_is_for_the_owner_only(hired: Employee, actor: User) -> None:
    client, owner = _client_for("HR", "hr_owner")
    assert client.get("/employees/signature/image/").status_code == 404  # none saved yet
    save_signature(owner, _png())
    got = client.get("/employees/signature/image/")
    assert got.status_code == 200 and got["Content-Type"] == "image/png"
    assert got["X-Content-Type-Options"] == "nosniff"
    other, _ = _client_for("HR", "hr_other")
    assert other.get("/employees/signature/image/").status_code == 404
    assert Client().get("/employees/signature/image/").status_code == 302  # anonymous: to the login page


def test_my_signature_delete_removes_the_row_and_the_file(hired: Employee, actor: User) -> None:
    client, owner = _client_for("HR", "hr_deleter")
    save_signature(owner, _png())
    stored = SavedSignature.objects.get(user=owner).image.name
    assert Path(settings.ORDER_FILES_ROOT, stored).is_file()
    response = client.post("/employees/signature/delete/")
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert not SavedSignature.objects.filter(user=owner).exists()
    assert not Path(settings.ORDER_FILES_ROOT, stored).exists()
    assert client.get("/employees/signature/delete/").status_code == 405


def test_my_signature_delete_with_next_redirects_back_to_the_pop_up(hired: Employee, actor: User) -> None:
    order = _registered_transfer(hired, actor)
    client, owner = _client_for("HR", "hr_next")
    save_signature(owner, _png())
    target = sign_url(hired, order)
    response = client.post("/employees/signature/delete/", {"next": target})
    assert response.status_code == 302 and response["Location"] == target
    response = client.post("/employees/signature/delete/", {"next": "https://evil.example/x"})
    assert response.status_code == 204  # never redirected off the site


# --- the order pop-up's signing block ----------------------------------------------------------------------------


def test_order_pop_up_shows_the_sign_button_only_for_a_signer_on_a_registered_order(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    assert sign_url(hired, order) in client.get(f"/employees/{hired.pk}/order/{order.pk}/detail/").content.decode()
    plain, _ = _client_for("HR", "hr_plain")
    assert sign_url(hired, order) not in plain.get(f"/employees/{hired.pk}/order/{order.pk}/detail/").content.decode()
    pending = HrOrder.objects.get(employee=hired, is_hire=True)  # not registered yet
    assert pending.state == OrderState.PENDING
    body = client.get(f"/employees/{hired.pk}/order/{pending.pk}/detail/").content.decode()
    assert sign_url(hired, pending) not in body


def test_signed_order_pop_up_shows_signer_time_method_and_image(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    body = client.get(f"/employees/{hired.pk}/order/{order.pk}/detail/").content.decode()
    row = OrderSigning.objects.get(order=order)
    assert row.signer_name in body
    assert "Шинээр зурсан гарын үсэг" in body
    assert image_url(hired, order) in body
    assert sign_url(hired, order) not in body  # signed: no sign button any more
    assert Path(settings.ORDER_FILES_ROOT, row.image.name).is_file()


# --- CSRF and the remember tick -------------------------------------------------------------------------------------


def test_posts_without_a_csrf_token_are_refused_and_change_nothing(hired: Employee, actor: User) -> None:
    order = _registered_transfer(hired, actor)
    user = User.objects.create_user("hr_csrf", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    _grant_sign(user)
    save_signature(user, _png())
    client = Client(enforce_csrf_checks=True)
    client.force_login(User.objects.get(pk=user.pk))
    posted = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert posted.status_code == 403
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    deleted = client.post("/employees/signature/delete/")
    assert deleted.status_code == 403
    assert SavedSignature.objects.filter(user=user).exists()


def test_remember_tick_decides_whether_a_saved_signature_is_kept(hired: Employee, actor: User) -> None:
    _need_pdf_font()
    client, user = _client_for("HR", "hr_remember")
    _grant_sign(user)
    first = _registered_transfer(hired, actor, number="21", day=DAY)
    client.post(sign_url(hired, first), {"mode": "drawn", "signature": _data_url()})  # no remember field
    assert OrderSigning.objects.get(order=first).method == OrderSigning.Method.DRAWN
    assert not SavedSignature.objects.filter(user=user).exists()
    second = _registered_transfer(hired, actor, number="22", day=date(2026, 3, 2))
    client.post(sign_url(hired, second), {"mode": "drawn", "signature": _data_url(), "remember": "1"})
    assert SavedSignature.objects.filter(user=user).count() == 1


# --- review fix wave (2026-11-09): the canvas box, a missing file, a broken template, the salary rule on GET ---------


def _files_under(root: object) -> set[str]:
    base = Path(str(root))
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def test_canvas_keeps_the_three_to_one_box_of_its_picture(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    body = client.get(sign_url(hired, order)).content.decode()
    canvas = body.split("<canvas", 1)[1].split(">", 1)[0]
    assert "aspect-ratio: 3 / 1" in canvas
    assert "height: auto" in canvas
    assert "h-[200px]" not in canvas  # no fixed pixel height: the box follows the picture's proportions


def test_saved_row_without_its_file_behaves_as_no_saved_signature(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, user = signer_client
    save_signature(user, _png())
    Path(settings.ORDER_FILES_ROOT, SavedSignature.objects.get(user=user).image.name).unlink()
    body = client.get(sign_url(hired, order)).content.decode()
    assert SAVED_BUTTON not in body and 'data-sign-section="saved"' not in body
    assert 'name="mode" value="drawn"' in body  # the board is shown
    assert client.get("/employees/signature/image/").status_code == 404
    posted = client.post(sign_url(hired, order), {"mode": "saved"})
    assert posted.status_code == 200 and SAVED_MISSING in posted.content.decode()
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_missing_order_template_shows_the_error_and_leaves_no_file(
    hired: Employee, actor: User, signer_client: tuple[Client, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client

    def broken(*_args: object, **_kwargs: object) -> bytes:
        raise order_docs.OrderDocError("missing")

    monkeypatch.setattr(order_docs, "render_signed_pdf", broken)
    before = _files_under(settings.ORDER_FILES_ROOT)
    response = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert response.status_code == 200
    body = response.content.decode()
    assert TEMPLATE_ERROR in body and SIGN_TITLE in body
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    assert _files_under(settings.ORDER_FILES_ROOT) == before


def test_broken_order_template_file_shows_the_error_and_signs_nothing(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, _ = signer_client
    template = OrderTemplate.objects.create(order_type=int(order.order_type))
    template.file.save("broken.docx", ContentFile(b"this is not a Word file"), save=True)
    response = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert response.status_code == 200
    assert TEMPLATE_ERROR in response.content.decode()
    assert not OrderSigning.objects.filter(order=order).exists()


def test_hire_order_pop_up_is_403_without_the_salary_right(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    orders.register(order, number="30", date=DAY, summary="", issued_by="", by=actor)
    client, user = signer_client  # HR: no salary right
    assert client.get(sign_url(hired, order)).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename="view_salary", content_type__app_label="macs"))
    assert client.get(sign_url(hired, order)).status_code == 200  # the control: with the salary right


def test_order_of_another_employee_in_the_url_is_404_and_signs_nothing(
    hired: Employee, actor: User, job_values: dict[str, Any], signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    other = history.hire(hire_values("УБ99112244"), {}, start=DAY, job=job_values, salary=Decimal("2500000"), by=actor)
    client, user = signer_client
    assert client.get(sign_url(other, order)).status_code == 404
    posted = client.post(sign_url(other, order), {"mode": "drawn", "signature": _data_url()})
    assert posted.status_code == 404
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    _need_pdf_font()
    # now a signed picture exists
    order_signing.sign_order(order, by=user, png=_png(), method=OrderSigning.Method.DRAWN)
    assert client.get(image_url(hired, order)).status_code == 200  # the control: the right employee gets it
    assert client.get(image_url(other, order)).status_code == 404


def test_signing_post_for_an_employee_outside_the_scope_is_404_and_signs_nothing(hired: Employee, actor: User) -> None:
    order = _registered_transfer(hired, actor)
    north = Branch.objects.create(name="Хойд ханз")
    south = Branch.objects.create(name="Өмнөд ханз")
    client, user = _client_for("HR", "hr_scope_post")
    _grant_sign(user)
    AccessScope.objects.create(user=user, limited=True, branch_ids=[north.pk])
    Employee.objects.filter(pk=hired.pk).update(branch_id=south.pk)
    posted = client.post(sign_url(hired, order), {"mode": "drawn", "signature": _data_url()})
    assert posted.status_code == 404
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_removing_the_saved_signature_asks_first(
    hired: Employee, actor: User, signer_client: tuple[Client, User]
) -> None:
    order = _registered_transfer(hired, actor)
    client, user = signer_client
    save_signature(user, _png())
    body = client.get(sign_url(hired, order)).content.decode()
    assert DELETE_QUESTION in body
    confirm = body.split(DELETE_QUESTION, 1)[1].split("</span>", 1)[0]
    assert 'hx-post="/employees/signature/delete/"' in confirm
    assert SavedSignature.objects.filter(user=user).exists()  # the question alone deletes nothing

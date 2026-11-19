"""The request-free signing functions (order-signing board, step 3d-2): what the pop-up needs (signing_state) and what a
signing attempt returns as user-readable errors (submit_sign). The Django views and the API both call these."""

import base64
import io
import itertools
from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404
from django.utils import timezone
from PIL import Image

from employees.models import Employee, HrOrder, OrderSigning, OrderState, OrderTemplate, OrderType, SavedSignature
from employees.services import events, macs_writes, order_signing, orders
from employees.services.order_signing import (
    METHOD_ERROR,
    SAVED_MISSING,
    SIGN_NEEDS_SALARY,
    TEMPLATE_BROKEN,
    SignState,
    save_signature,
    signing_state,
    submit_sign,
)
from employees.signature_image import DRAW_ERROR
from employees.tests.test_order_docs import _need_pdf_font

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
_numbers = itertools.count(1)


def _png(color: tuple[int, int, int, int] = (20, 20, 20, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(_png()).decode()


def _grant(user: User, codename: str, app_label: str = "accounts") -> None:
    user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app_label))


def _fresh(user: User) -> User:
    return User.objects.get(pk=user.pk)  # permission cache is per instance: reload after granting


@pytest.fixture
def signer(actor: User) -> User:
    _grant(actor, "sign_orders")
    return _fresh(actor)


def _registered_transfer(emp: Employee, actor: User) -> HrOrder:
    # An order needs its number when it is created (D-083): each test change gets a unique one.
    event = events.record(
        emp,
        type="transfer",
        effective=DAY,
        changes={"department": macs_writes.save_department("Инженер")},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number=f"Т/{next(_numbers)}",
        order_date=DAY,
    )
    order = HrOrder.objects.get(event=event)
    if order.state == OrderState.PENDING:
        today = timezone.localdate()
        orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def _hire_order(emp: Employee, actor: User) -> HrOrder:
    order = orders.create_for_change(
        employee=emp,
        event=None,
        is_hire=True,
        order_type=OrderType.HIRED,
        number="Э/9",
        date=timezone.localdate(),
        summary="",
        issued_by="",
        by=actor,
    )
    return order


# --- signing_state -----------------------------------------------------------------------------------------------


def test_signing_state_has_saved_flag(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    state = signing_state(signer, order)
    assert state == SignState(number=order.number, has_saved=False)
    save_signature(signer, _png())
    assert signing_state(_fresh(signer), order).has_saved is True


def test_signing_state_403_when_salary_right_missing(signer: User, hired: Employee) -> None:
    order = _hire_order(hired, signer)  # the signer holds no macs.view_salary, and a hire order shows a salary
    with pytest.raises(PermissionDenied):
        signing_state(signer, order)


def test_signing_state_403_without_the_switch(actor: User, hired: Employee) -> None:
    order = _registered_transfer(hired, actor)
    with pytest.raises(PermissionDenied):
        signing_state(actor, order)


def test_signing_state_404_for_signed_order(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    order_signing.sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    order.refresh_from_db()
    with pytest.raises(Http404):
        signing_state(signer, order)


# --- submit_sign -------------------------------------------------------------------------------------------------


def test_submit_sign_saved_signature_signs(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    save_signature(signer, _png())
    assert submit_sign(signer, order, "saved", "", False) == []
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    row = OrderSigning.objects.get(order=order)
    assert row.method == OrderSigning.Method.SAVED


def test_submit_sign_saved_missing_returns_saved_missing_and_writes_nothing(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    assert submit_sign(signer, order, "saved", "", False) == [SAVED_MISSING]
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_submit_sign_drawn_empty_returns_draw_error(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    assert submit_sign(signer, order, "drawn", "", False) == [DRAW_ERROR]
    assert not OrderSigning.objects.filter(order=order).exists()


def test_submit_sign_drawn_remember_saves_signature(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    assert submit_sign(signer, order, "drawn", _data_url(), True) == []
    assert SavedSignature.objects.filter(user=signer).count() == 1
    assert order_signing.saved_signature_png(signer) is not None


def test_submit_sign_unknown_mode_returns_method_error(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    assert submit_sign(signer, order, "typed", "", False) == [METHOD_ERROR]
    assert not OrderSigning.objects.filter(order=order).exists()


def test_submit_sign_salary_refusal_returns_the_message(signer: User, hired: Employee) -> None:
    order = _hire_order(hired, signer)
    assert submit_sign(signer, order, "drawn", _data_url(), False) == [SIGN_NEEDS_SALARY]
    assert not OrderSigning.objects.filter(order=order).exists()


def test_submit_sign_broken_template_returns_template_broken_and_writes_nothing(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    template = OrderTemplate.objects.create(order_type=int(order.order_type))
    template.file.save("broken.docx", ContentFile(b"this is not a Word file"), save=True)
    assert submit_sign(signer, order, "drawn", _data_url(), False) == [TEMPLATE_BROKEN]
    assert not OrderSigning.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED

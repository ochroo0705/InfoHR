"""The order pop-ups as request-free services: edit (number, date, text), upload (the signed scan) and history."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404

from employees.forms import CancelEventForm
from employees.models import ActivityEntry, ActivityKind, Employee, Event, EventType, HrOrder, OrderState, OrderType
from employees.services import order_popups, orders

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"
HINT = "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү."


def user_in(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def hr_user(db: None) -> User:
    return user_in("HR", "hr_popup")


@pytest.fixture
def plain_user(db: None) -> User:
    return user_in("Employee", "plain_popup")


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def values(number: str = "30", day: str = "2026-03-02", summary: str = "Шилжүүлэв", issued_by: str = "Б. Дорж"):
    return {"number": number, "date": day, "summary": summary, "issued_by": issued_by}


def make_cancelled(emp: Employee, number: str) -> HrOrder:
    event = Event.objects.create(employee=emp, type=EventType.PROMOTION, effective=date(2026, 2, 1))
    return HrOrder.objects.create(
        employee=emp, event=event, order_type=OrderType.POSITION, state=OrderState.CANCELLED,
        number=number, number_key=number.casefold(), date=date(2026, 2, 1),
    )  # fmt: skip


def test_edit_popup_suggests_number_when_empty(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(number="", date=date.today())
    order.refresh_from_db()
    popup = order_popups.edit_popup(hr_user, hired, order)
    suggested = orders.suggest_number(date.today())
    assert suggested and popup.form.initial["number"] == suggested
    assert popup.hint == HINT
    assert popup.title == "Тушаал: Ажилд орсон"


def test_edit_popup_keeps_the_saved_number_without_a_hint(hired: Employee, hr_user: User) -> None:
    popup = order_popups.edit_popup(hr_user, hired, hire_order(hired))
    assert popup.form.initial["number"] == "1" and popup.hint == ""


def test_edit_popup_signed_or_cancelled_is_404(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    for state in (OrderState.SIGNED, OrderState.CANCELLED):
        HrOrder.objects.filter(pk=order.pk).update(state=state)
        order.refresh_from_db()
        with pytest.raises(Http404):
            order_popups.edit_popup(hr_user, hired, order)


def test_edit_popup_needs_manage_right(hired: Employee, plain_user: User) -> None:
    with pytest.raises(PermissionDenied):
        order_popups.edit_popup(plain_user, hired, hire_order(hired))


def test_submit_edit_registers_and_returns_order(hired: Employee, hr_user: User) -> None:
    ok, popup, done = order_popups.submit_edit(hr_user, hired, hire_order(hired), values(number="31"))
    assert ok is True and done is not None
    hire_order(hired).refresh_from_db()
    assert hire_order(hired).number == "31" and hire_order(hired).date == date(2026, 3, 2)
    assert popup.form.is_bound


def test_submit_edit_blank_number_not_ok(hired: Employee, hr_user: User) -> None:
    ok, popup, done = order_popups.submit_edit(hr_user, hired, hire_order(hired), values(number=""))
    assert ok is False and done is None
    assert "number" in popup.form.errors
    assert hire_order(hired).number == "1"  # nothing written


def test_submit_edit_number_clash_error_on_number_field(hired: Employee, hr_user: User) -> None:
    make_cancelled(hired, "15")  # the number 15 is already used in 2026
    ok, popup, done = order_popups.submit_edit(hr_user, hired, hire_order(hired), values(number="15"))
    assert ok is False and done is None
    assert "number" in popup.form.errors
    assert hire_order(hired).number == "1"


def test_upload_valid_pdf_attaches(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    ok, _popup = order_popups.submit_upload(hr_user, order, SimpleUploadedFile("a.pdf", PDF))
    order.refresh_from_db()
    assert ok is True
    assert order.state == OrderState.SIGNED and order.file
    assert order.file.open("rb").read().startswith(b"%PDF-")


def test_upload_popup_has_its_title(hired: Employee, hr_user: User) -> None:
    popup = order_popups.upload_popup(hr_user, hire_order(hired))
    assert popup.title == "Гарын үсэгтэй файл хавсаргах" and popup.hint == ""


def test_upload_wrong_type_refused_with_form_message(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    ok, popup = order_popups.submit_upload(hr_user, order, SimpleUploadedFile("a.txt", b"hello text"))
    order.refresh_from_db()
    assert ok is False
    assert popup.form.errors["file"] == ["Зөвхөн PDF, JPG эсвэл PNG файл оруулна уу."]
    assert order.state == OrderState.REGISTERED and not order.file


def test_upload_needs_manage_right(hired: Employee, plain_user: User) -> None:
    with pytest.raises(PermissionDenied):
        order_popups.upload_popup(plain_user, hire_order(hired))
    with pytest.raises(PermissionDenied):
        order_popups.submit_upload(plain_user, hire_order(hired), SimpleUploadedFile("a.pdf", PDF))


def test_history_entries_order_and_by_fallback(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="", issued_by="", by=hr_user)
    orders.register(order, number="13", date=date(2026, 1, 5), summary="", issued_by="", by=hr_user)
    ActivityEntry.objects.create(
        employee=hired, by=None, kind=ActivityKind.CHANGED, message="системийн мөр", order=order
    )
    entries = order_popups.history_entries(order)  # newest first: the system line, then the two edits, then the hire
    assert entries[0] == {"by": "Систем", "at": entries[0]["at"], "message": "системийн мөр", "changes": []}
    assert entries[1]["by"] == "hr_popup"
    assert entries[1]["changes"] == [{"field": "Дугаар", "old": "12", "new": "13"}]
    assert len(entries[0]["at"]) == 16  # "Y-m-d H:i"


def test_history_title_names_type_and_number(hired: Employee) -> None:
    order = hire_order(hired)
    assert order_popups.history_title(order) == "Тушаалын түүх: Ажилд орсон · № 1"
    HrOrder.objects.filter(pk=order.pk).update(number="")
    order.refresh_from_db()
    assert order_popups.history_title(order) == "Тушаалын түүх: Ажилд орсон"


CANCEL_HINT_TEXT = (
    "Тушаал «цуцалсан» болж түүхэнд үлдэнэ, дугаар нь хэвээр хадгалагдана. Ажилд авсан бүртгэл өөрөө хэвээр үлдэнэ."
)


def test_cancel_popup_title_and_hint(hired: Employee, hr_user: User) -> None:
    popup = order_popups.cancel_popup(hr_user, hired, hire_order(hired))
    assert popup.title == "Тушаал цуцлах: Ажилд орсон № 1"
    assert popup.hint == CANCEL_HINT_TEXT == order_popups.CANCEL_HINT
    assert order_popups.CANCEL_LABEL == "Цуцлах"
    assert isinstance(popup.form, CancelEventForm) and not popup.form.is_bound


def test_cancel_popup_404_for_signed_pending_or_event_order(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    for state in (OrderState.SIGNED, OrderState.PENDING):
        HrOrder.objects.filter(pk=order.pk).update(state=state)
        order.refresh_from_db()
        with pytest.raises(Http404):
            order_popups.cancel_popup(hr_user, hired, order)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.REGISTERED)
    order.refresh_from_db()
    event = Event.objects.create(employee=hired, type=EventType.PROMOTION, effective=date(2026, 2, 1))
    change = HrOrder.objects.create(
        employee=hired, event=event, order_type=OrderType.POSITION, state=OrderState.REGISTERED,
        number="41", number_key="41", date=date(2026, 2, 1),
    )  # fmt: skip
    with pytest.raises(Http404):
        order_popups.cancel_popup(hr_user, hired, change)
    with pytest.raises(Http404):
        order_popups.submit_cancel(hr_user, hired, change, {"reason": "x"})
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_cancel_popup_403_without_manage(hired: Employee, plain_user: User) -> None:
    with pytest.raises(PermissionDenied):
        order_popups.cancel_popup(plain_user, hired, hire_order(hired))
    with pytest.raises(PermissionDenied):
        order_popups.submit_cancel(plain_user, hired, hire_order(hired), {"reason": "x"})


def test_submit_cancel_empty_reason_refused(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    ok, popup = order_popups.submit_cancel(hr_user, hired, order, {"reason": ""})
    order.refresh_from_db()
    assert ok is False
    assert "reason" in popup.form.errors
    assert order.state == OrderState.REGISTERED and order.cancel_reason == ""


def test_submit_cancel_cancels_order_with_reason(hired: Employee, hr_user: User) -> None:
    order = hire_order(hired)
    ok, popup = order_popups.submit_cancel(hr_user, hired, order, {"reason": "Буруу бичсэн"})
    order.refresh_from_db()
    assert ok is True
    assert order.state == OrderState.CANCELLED and order.cancel_reason == "Буруу бичсэн"
    assert order.number == "1"
    assert popup.form.is_bound


def test_submit_cancel_order_error_goes_to_form_error(hired: Employee, hr_user: User, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise orders.OrderError({"__all__": "Зөвхөн гарын үсэг зураагүй, бүртгэсэн тушаалыг цуцална."})

    monkeypatch.setattr(order_popups.orders, "cancel_order", refuse)
    order = hire_order(hired)
    ok, popup = order_popups.submit_cancel(hr_user, hired, order, {"reason": "x"})
    assert ok is False
    assert popup.form.non_field_errors() == ["Зөвхөн гарын үсэг зураагүй, бүртгэсэн тушаалыг цуцална."]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED

"""Signing a registered order on screen (order-signing board, Task 6): the signing service, the saved signature and
the permission check. A refused signing writes nothing: no file, no row, and the order stays registered."""

import hashlib
import io
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from employees import access, history_range
from employees.models import (
    ActivityEntry,
    Employee,
    Event,
    HistoryLock,
    HrOrder,
    OrderSigning,
    OrderState,
    OrderType,
    SavedSignature,
)
from employees.services import events, macs_writes, order_docs, order_signing, orders
from employees.services.order_signing import (
    METHOD_ERROR,
    SIGN_NEEDS_SALARY,
    delete_saved_signature,
    save_signature,
    saved_signature_png,
    sign_order,
    signer_name,
)
from employees.services.orders import OrderError
from employees.tests.conftest import link_login
from employees.tests.test_order_docs import _need_pdf_font

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
LATER = date(2026, 4, 1)


def _png(color: tuple[int, int, int, int] = (20, 20, 20, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _stored_files() -> set[str]:
    """Every file under the order files folder (the test fixture points it at a temporary folder)."""
    root = Path(settings.ORDER_FILES_ROOT)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _grant(user: User, codename: str, app_label: str = "accounts") -> None:
    user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app_label))


def _transfer(employee: Employee, actor: User, day: date, department: str) -> Event:
    return events.record(
        employee,
        type="transfer",
        effective=day,
        changes={"department": macs_writes.save_department(department)},
        salary=None,
        reason="",
        note="",
        by=actor,
    )


def _register_today(order: HrOrder, actor: User) -> HrOrder:
    today = timezone.localdate()
    orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def _scan() -> SimpleUploadedFile:
    return SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")


@pytest.fixture
def signer(actor: User) -> User:
    _grant(actor, "sign_orders")
    return actor


def _registered_transfer(hired: Employee, signer: User) -> HrOrder:
    event = _transfer(hired, signer, DAY, "Инженер")
    return _register_today(HrOrder.objects.get(event=event), signer)


# --- the permission check -------------------------------------------------------------------------------------


def test_can_sign_orders_needs_the_permission(actor: User, hired: Employee) -> None:
    order = _registered_transfer(hired, actor)
    assert not access.can_sign_orders(actor, order)
    _grant(actor, "sign_orders")
    assert access.can_sign_orders(User.objects.get(pk=actor.pk), order)


def test_can_sign_orders_is_false_for_inactive_user(actor: User, hired: Employee) -> None:
    _grant(actor, "sign_orders")
    order = _registered_transfer(hired, actor)
    actor.is_active = False
    actor.save(update_fields=["is_active"])
    assert not access.can_sign_orders(User.objects.get(pk=actor.pk), order)


# --- the signer's name ----------------------------------------------------------------------------------------


def test_signer_name_without_employee_link_is_account_name(actor: User) -> None:
    assert signer_name(actor) == "hr_actor"  # no first or last name on the account: the username
    actor.last_name, actor.first_name = "Дорж", "Бат"
    actor.save()
    assert signer_name(actor) == "Дорж Бат"


def test_signer_name_with_employee_link_is_employee_name(actor: User, hired: Employee) -> None:
    link_login(hired, actor)
    assert signer_name(actor) == hired.full_name


# --- signing ---------------------------------------------------------------------------------------------------


def test_sign_registered_change_order_writes_file_row_and_activity(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    ev = Event.objects.get(pk=order.event_id)
    signed = sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert signed.state == OrderState.SIGNED
    signed.refresh_from_db()
    assert Path(signed.file.name).name == f"order-{signed.pk}-signed.pdf"
    data = signed.file.read()
    assert data.startswith(b"%PDF-")
    ev.refresh_from_db()
    assert ev.applied_at is not None
    row = OrderSigning.objects.get(order=signed)
    assert row.signer_name == "hr_actor"
    assert row.method == OrderSigning.Method.DRAWN
    assert len(row.pdf_sha256) == 64
    assert row.pdf_sha256 == hashlib.sha256(data).hexdigest()
    assert row.image.name.replace("\\", "/").startswith("signing/")
    entry = ActivityEntry.objects.get(order=signed, kind="changed", message__contains="дэлгэц дээр")
    assert "түгжсэн" in entry.message


def test_remember_saves_signature_and_survives_replace_and_delete(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    png = _png()
    sign_order(order, by=signer, png=png, method=OrderSigning.Method.DRAWN, remember=True)
    assert SavedSignature.objects.filter(user=signer).count() == 1
    assert saved_signature_png(signer) == png
    stored_before = OrderSigning.objects.get(order=order).image.name
    save_signature(signer, _png((200, 0, 0, 255)))
    assert SavedSignature.objects.filter(user=signer).count() == 1
    delete_saved_signature(signer)
    assert SavedSignature.objects.filter(user=signer).count() == 0
    assert saved_signature_png(signer) is None
    row = OrderSigning.objects.get(order=order)
    assert row.image.name == stored_before
    assert Path(settings.ORDER_FILES_ROOT, stored_before).is_file()


def test_second_signing_is_refused_with_one_file_and_one_row(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    files_before = _stored_files()
    with pytest.raises(OrderError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert _stored_files() == files_before
    assert OrderSigning.objects.filter(order_id=order.pk).count() == 1


def test_prior_scan_makes_signing_refused_with_one_file_and_one_row(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    orders.attach_signed_file(order, _scan(), by=signer)
    files_before = _stored_files()
    with pytest.raises(OrderError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert _stored_files() == files_before
    assert OrderSigning.objects.filter(order_id=order.pk).count() == 0
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED


def test_pending_order_cannot_be_signed(signer: User, hired: Employee) -> None:
    event = _transfer(hired, signer, DAY, "Инженер")
    order = HrOrder.objects.get(event=event)
    assert order.state == OrderState.PENDING
    with pytest.raises(OrderError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert OrderSigning.objects.count() == 0


def test_cancelled_order_cannot_be_signed(signer: User, hired: Employee) -> None:
    order = _registered_transfer(hired, signer)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    order.refresh_from_db()
    with pytest.raises(OrderError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert OrderSigning.objects.count() == 0


def test_hire_order_needs_salary_right_and_writes_nothing(signer: User, hired: Employee) -> None:
    hire_order = orders.create_for_change(
        employee=hired,
        event=None,
        is_hire=True,
        order_type=OrderType.HIRED,
        number="",
        date=None,
        summary="",
        issued_by="",
        by=signer,
    )
    _register_today(hire_order, signer)
    files_before = _stored_files()
    with pytest.raises(OrderError) as refused:
        sign_order(hire_order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert refused.value.errors == {"__all__": SIGN_NEEDS_SALARY}
    assert _stored_files() == files_before
    assert OrderSigning.objects.count() == 0
    hire_order.refresh_from_db()
    assert hire_order.state == OrderState.REGISTERED
    assert not hire_order.file


def test_refused_change_leaves_no_file_no_row_and_order_registered(signer: User, hired: Employee) -> None:
    # Same field (department) twice: the earlier change still waits, so the later one cannot be applied first.
    _transfer(hired, signer, DAY, "Инженер")
    late = _transfer(hired, signer, LATER, "Худалдаа")
    order = _register_today(HrOrder.objects.get(event=late), signer)
    files_before = _stored_files()
    with pytest.raises(OrderError) as refused:
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert "2026-03-01" in refused.value.errors["__all__"]
    assert _stored_files() == files_before
    assert OrderSigning.objects.count() == 0
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    assert not order.file
    late.refresh_from_db()
    assert late.applied_at is None


@pytest.mark.parametrize("method", ["x", "drawn-and-more-than-8"])
def test_unknown_method_is_refused_before_anything_is_written(signer: User, hired: Employee, method: str) -> None:
    order = _registered_transfer(hired, signer)
    files_before = _stored_files()
    with pytest.raises(OrderError) as refused:
        sign_order(order, by=signer, png=_png(), method=method)
    assert refused.value.errors == {"__all__": METHOD_ERROR}
    assert _stored_files() == files_before
    assert OrderSigning.objects.count() == 0
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_failure_after_the_pdf_is_written_deletes_the_files_and_keeps_order_registered(
    signer: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    ev = Event.objects.get(pk=order.event_id)
    files_before = _stored_files()

    def boom(self: OrderSigning, *args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(OrderSigning, "save", boom)  # fails after the PDF and the picture are written
    with pytest.raises(RuntimeError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN, remember=True)
    assert _stored_files() == files_before  # the PDF and the picture written by this call are gone
    assert OrderSigning.objects.count() == 0
    assert SavedSignature.objects.count() == 0
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    assert not order.file
    ev.refresh_from_db()
    assert ev.applied_at is None


def test_attaching_a_scan_after_signing_is_refused(signer: User, hired: Employee) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    files_before = _stored_files()
    with pytest.raises(OrderError):
        orders.attach_signed_file(order, _scan(), by=signer)
    assert _stored_files() == files_before
    assert OrderSigning.objects.filter(order_id=order.pk).count() == 1


def test_locks_are_taken_before_the_pdf_is_rendered(
    signer: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    steps: list[object] = []
    ctx = CaptureQueriesContext(connection)
    real_lock = history_range.lock_employee
    real_render = order_docs.render_signed_pdf

    def lock(employee_id: int) -> None:
        steps.append("lock_employee")
        real_lock(employee_id)

    def render(order_arg: HrOrder, user: User, stamp: order_docs.SignatureStamp) -> bytes:
        steps.append(("render", len(ctx.captured_queries)))
        return real_render(order_arg, user, stamp)

    monkeypatch.setattr(history_range, "lock_employee", lock)
    monkeypatch.setattr(order_docs, "render_signed_pdf", render)
    with ctx:
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert steps[0] == "lock_employee"
    render_at = steps[1][1]  # type: ignore[index]
    sql = [q["sql"] for q in ctx.captured_queries[:render_at]]

    def first_locked(table: str) -> int:
        return next(i for i, s in enumerate(sql) if table in s and "FOR UPDATE" in s)

    lock_at = next(i for i, s in enumerate(sql) if HistoryLock._meta.db_table in s)
    employee_at = first_locked(Employee._meta.db_table)
    order_at = first_locked(HrOrder._meta.db_table)
    assert lock_at < employee_at < order_at < render_at


def test_signed_pdf_shows_the_same_job_as_the_order_before_signing(signer: User, hired: Employee) -> None:
    # Before signing, the event still waits, so build_context shows the proposed (new) job, which is what the
    # printed order shows. After signing the change is applied and must read the same.
    order = _registered_transfer(hired, signer)
    before = order_docs.build_context(order, signer)
    assert before["department"] == "Инженер"
    assert before["new_department"] == "Инженер"
    sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    order.refresh_from_db()
    after = order_docs.build_context(order, signer)
    for key in ("department", "position", "new_department", "old_department", "employee_type"):
        assert after[key] == before[key], key


def test_failing_delete_does_not_hide_the_original_error(
    signer: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, signer)
    attempted: list[str] = []
    real_delete = FileSystemStorage.delete

    def delete(self: FileSystemStorage, name: str) -> None:
        attempted.append(name)
        if "signing/" in name:  # the signing picture: its delete fails
            raise OSError("delete failed")
        real_delete(self, name)

    def boom(self: OrderSigning, *args: object, **kwargs: object) -> None:
        raise RuntimeError("original")

    monkeypatch.setattr(FileSystemStorage, "delete", delete)
    monkeypatch.setattr(OrderSigning, "save", boom)
    with pytest.raises(RuntimeError, match="^original$"):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN)
    assert any("signing/" in name for name in attempted)
    assert any("signed.pdf" in name for name in attempted)  # later files are still attempted


def test_failure_after_saved_signature_replace_keeps_the_old_one(
    signer: User, hired: Employee, monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    _need_pdf_font()
    old_png = _png((0, 0, 200, 255))
    with django_capture_on_commit_callbacks(execute=True):
        save_signature(signer, old_png)
    old_name = SavedSignature.objects.get(user=signer).image.name
    assert Path(settings.ORDER_FILES_ROOT, old_name).is_file()
    order = _registered_transfer(hired, signer)
    files_before = _stored_files()
    real_replace = order_signing._replace_saved_signature

    def replace_then_fail(user: User, png: bytes, stored: list[Any]) -> Any:
        real_replace(user, png, stored)  # the row now points at the new picture
        raise RuntimeError("boom")

    monkeypatch.setattr(order_signing, "_replace_saved_signature", replace_then_fail)
    with pytest.raises(RuntimeError):
        sign_order(order, by=signer, png=_png(), method=OrderSigning.Method.DRAWN, remember=True)
    assert _stored_files() == files_before  # the new picture is gone, the old file is still there
    assert SavedSignature.objects.get(user=signer).image.name == old_name
    assert saved_signature_png(signer) == old_png
    assert OrderSigning.objects.count() == 0
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED


def test_replacing_saved_signature_removes_old_file_only_on_commit(
    signer: User, hired: Employee, django_capture_on_commit_callbacks: Any
) -> None:
    _need_pdf_font()
    with django_capture_on_commit_callbacks(execute=True):
        save_signature(signer, _png((0, 0, 200, 255)))
    old_name = SavedSignature.objects.get(user=signer).image.name
    old_path = Path(settings.ORDER_FILES_ROOT, old_name)
    order = _registered_transfer(hired, signer)
    new_png = _png((200, 0, 0, 255))
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        sign_order(order, by=signer, png=new_png, method=OrderSigning.Method.DRAWN, remember=True)
    assert old_path.is_file()  # not removed before the commit
    for callback in callbacks:
        callback()  # what the commit would run
    assert not old_path.is_file()
    row = SavedSignature.objects.get(user=signer)
    assert row.image.name != old_name
    assert Path(settings.ORDER_FILES_ROOT, row.image.name).is_file()
    assert saved_signature_png(signer) == new_png
    assert SavedSignature.objects.filter(user=signer).count() == 1

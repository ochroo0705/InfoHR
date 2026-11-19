"""The order file payloads (services/order_files.py): the rights, the 404s and the file headers the views and the API
share. The HTTP side is covered by test_order_views.py and test_order_switches.py."""

import io
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404
from django.test import Client
from django.utils import timezone
from PIL import Image

from employees.models import Employee, HrOrder, OrderSigning, OrderState
from employees.services import order_docs, order_files, order_signing, orders
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), (20, 20, 20, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _user(role: str, name: str) -> User:
    return login_as(Client(), role, name)


def registered_hire(emp: Employee, actor: User) -> HrOrder:
    order = HrOrder.objects.get(employee=emp, is_hire=True)
    return orders.register(order, number="15", date=date(2026, 1, 5), summary="", issued_by="", by=actor)


def with_scan(order: HrOrder, content: bytes = PDF, name: str = "scan.pdf") -> HrOrder:
    order.file.save(name, ContentFile(content), save=True)
    order.refresh_from_db()
    return order


def test_scan_payload_sniffs_pdf_png_jpeg(hired: Employee, actor: User) -> None:
    order = with_scan(registered_hire(hired, actor), PDF)
    accountant = _user("Accountant", "acc_pdf")  # the Accountant holds macs.view_salary (OQ-080)
    payload = order_files.scan_payload(accountant, order)
    assert (payload.content_type, payload.filename) == ("application/pdf", f"order-{order.pk}.pdf")
    assert payload.inline is True and payload.private is True
    assert payload.handle is not None

    order.file.save("scan.png", ContentFile(_png()), save=True)
    order.refresh_from_db()
    assert order_files.scan_payload(accountant, order).content_type == "image/png"

    order.file.save("scan.jpg", ContentFile(b"\xff\xd8\xff\xe0 jpeg"), save=True)
    order.refresh_from_db()
    jpeg = order_files.scan_payload(accountant, order)
    assert (jpeg.content_type, jpeg.filename) == ("image/jpeg", f"order-{order.pk}.jpg")


def test_scan_payload_403_without_scan_right_on_hire_order(hired: Employee, actor: User) -> None:
    order = with_scan(registered_hire(hired, actor))
    hr = _user("HR", "hr_scan")  # HR may manage orders but not see the salary scan of a hire order
    with pytest.raises(PermissionDenied):
        order_files.scan_payload(hr, order)


def test_scan_payload_404_when_no_file_or_missing_on_disk(hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    accountant = _user("Accountant", "acc_none")
    with pytest.raises(Http404):
        order_files.scan_payload(accountant, order)  # nothing uploaded yet
    HrOrder.objects.filter(pk=order.pk).update(file="orders/gone-from-disk.pdf")
    order.refresh_from_db()
    with pytest.raises(Http404):
        order_files.scan_payload(accountant, order)  # the row names a file that is not on disk


def test_document_payload_docx_and_pdf_names(hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_docs, "render_order", lambda order, user: b"docx-bytes")
    monkeypatch.setattr(order_docs, "render_pdf", lambda order, user: b"pdf-bytes")
    order = registered_hire(hired, actor)
    hr = _user("HR", "hr_doc")
    word = order_files.document_payload(hr, order, pdf=False)
    assert word.filename == "tushaal-15.docx" and word.inline is False
    assert word.content_type == order_docs.DOCX_TYPE and word.handle is not None
    assert word.handle.read() == b"docx-bytes"
    pdf = order_files.document_payload(hr, order, pdf=True)
    assert pdf.filename == "tushaal-15.pdf" and pdf.content_type == order_docs.PDF_TYPE
    assert pdf.handle is not None and pdf.handle.read() == b"pdf-bytes"

    HrOrder.objects.filter(pk=order.pk).update(number="A/7")  # a non-word character becomes "_"
    order.refresh_from_db()
    assert order_files.document_payload(hr, order, pdf=True).filename == "tushaal-A_7.pdf"
    HrOrder.objects.filter(pk=order.pk).update(number="")  # no number: the row id
    order.refresh_from_db()
    assert order_files.document_payload(hr, order, pdf=False).filename == f"tushaal-id{order.pk}.docx"


def test_document_payload_404_for_cancelled_order(
    hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(order_docs, "render_order", lambda order, user: b"docx-bytes")
    order = registered_hire(hired, actor)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    order.refresh_from_db()
    with pytest.raises(Http404):
        order_files.document_payload(_user("HR", "hr_cancel"), order, pdf=False)


def test_document_payload_404_when_the_template_is_broken(
    hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(order: HrOrder, user: Any) -> bytes:
        raise order_docs.OrderDocError

    monkeypatch.setattr(order_docs, "render_order", broken)
    order = registered_hire(hired, actor)
    with pytest.raises(Http404):
        order_files.document_payload(_user("HR", "hr_broken"), order, pdf=False)


def test_document_payload_403_without_manage(hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    with pytest.raises(PermissionDenied):
        order_files.document_payload(actor, order, pdf=False)  # actor holds no role, so no manage right


def test_signing_image_payload_404_without_signing(hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    with pytest.raises(Http404):
        order_files.signing_image_payload(order)
    assert not OrderSigning.objects.filter(order=order).exists()


def test_signing_image_payload_404_when_the_picture_is_gone_from_disk(hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    OrderSigning.objects.create(
        order=order,
        signer=actor,
        signer_name="Бат Дорж",
        signed_at=timezone.now(),
        method=OrderSigning.Method.DRAWN,
        image="order-signings/gone-from-disk.png",  # the row names a file that is not on disk
        pdf_sha256="a" * 64,
    )
    with pytest.raises(Http404):
        order_files.signing_image_payload(order)


def test_saved_signature_payload_only_own_and_404_when_none(hired: Employee, actor: User) -> None:
    owner = _user("HR", "sig_owner")
    stranger = _user("HR", "sig_stranger")
    with pytest.raises(Http404):
        order_files.saved_signature_payload(owner)  # none saved yet
    order_signing.save_signature(owner, _png())
    payload = order_files.saved_signature_payload(owner)
    assert payload.data == order_signing.saved_signature_png(owner)
    assert payload.content_type == "image/png" and payload.private is True
    with pytest.raises(Http404):
        order_files.saved_signature_payload(stranger)  # only the requester's own row


def test_file_response_headers_scan_inline_nosniff_private(hired: Employee, actor: User) -> None:
    order = with_scan(registered_hire(hired, actor))
    payload = order_files.scan_payload(_user("Accountant", "acc_headers"), order)
    response = order_files.file_response(payload)
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "private, no-store"
    assert response["Content-Disposition"] == f'inline; filename="order-{order.pk}.pdf"'
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == PDF  # type: ignore[attr-defined]
    response.close()

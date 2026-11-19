"""The files of an HR order and of a user's saved signature, as request-free payloads: the signed scan, the Word and
PDF drafts, the signing picture and the saved-signature picture. The Django views and the API both build their
response from here (`file_response`), so the rights, the 404s and the headers are decided once."""

import io
import re
from dataclasses import dataclass
from typing import IO

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse

from employees import access
from employees.models import Employee, HrOrder, OrderSigning, OrderState
from employees.services import order_docs, order_signing

# The magic bytes of a signed scan and the type and extension it is served as (anything else is served as a JPEG).
FILE_TYPES = ((b"%PDF-", "application/pdf", ".pdf"), (b"\x89PNG", "image/png", ".png"))


@dataclass
class FilePayload:
    """One file ready to serve. Either `handle` (a file-like object, streamed) or `data` (bytes) is set.
    `filename` empty means no name is given (the storage name then applies, as the signing picture always had)."""

    handle: IO[bytes] | None = None
    data: bytes | None = None
    content_type: str = "application/octet-stream"
    filename: str = ""
    inline: bool = True
    private: bool = False  # adds `Cache-Control: private, no-store`


def order_label(order: HrOrder, employee: Employee) -> str:
    """The order and its employee for the system log: the number and the employee code, never the name."""
    return f"Тушаал № {order.number or 'дугаар байхгүй'}, ажилтны код {employee.code}"


def scan_payload(user: User, order: HrOrder) -> FilePayload:
    """The signed scan of an order, served inline. Hire and rehire scans need macs.view_salary (OQ-080)."""
    if not access.can_open_order_scan(user, order):
        raise PermissionDenied
    if not order.file:
        raise Http404
    try:
        handle = order.file.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    head = handle.read(8)
    handle.seek(0)
    content_type, ext = next(((t, e) for magic, t, e in FILE_TYPES if head.startswith(magic)), ("image/jpeg", ".jpg"))
    return FilePayload(
        handle=handle,
        content_type=content_type,
        filename=f"order-{order.pk}{ext}",
        inline=True,
        private=True,
    )


def document_payload(user: User, order: HrOrder, *, pdf: bool) -> FilePayload:
    """The order filled from its Word template, as .docx or .pdf (a draft to print and sign), as an attachment."""
    if not access.can_manage(user):
        raise PermissionDenied
    if order.state == OrderState.CANCELLED:
        raise Http404
    try:
        data = (order_docs.render_pdf if pdf else order_docs.render_order)(order, user)
    except order_docs.OrderDocError:
        raise Http404 from None
    name = re.sub(r"[^\w-]", "_", order.number) if order.number else f"id{order.pk}"
    return FilePayload(
        handle=io.BytesIO(data),
        content_type=order_docs.PDF_TYPE if pdf else order_docs.DOCX_TYPE,
        filename=f"tushaal-{name}.{'pdf' if pdf else 'docx'}",
        inline=False,
    )


def signing_image_payload(order: HrOrder) -> FilePayload:
    """The signature picture stamped on a signed order. Whoever may see the employee may see it."""
    signing = OrderSigning.objects.filter(order=order).first()
    if signing is None or not signing.image:
        raise Http404
    try:
        handle = signing.image.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    return FilePayload(handle=handle, content_type="image/png", inline=True, private=True)


def saved_signature_payload(user: User) -> FilePayload:
    """The user's own saved signature picture (only ever the requester's own, 404 when none)."""
    png = order_signing.saved_signature_png(user)
    if png is None:
        raise Http404
    return FilePayload(data=png, content_type="image/png", private=True)


def file_response(payload: FilePayload) -> HttpResponse:
    """The Django response for a payload, with the shared headers: nosniff always, and `Cache-Control: private,
    no-store` where the payload is private."""
    if payload.handle is not None:
        response: HttpResponse = FileResponse(
            payload.handle,
            content_type=payload.content_type,
            filename=payload.filename or None,
            as_attachment=not payload.inline,
        )
    else:
        response = HttpResponse(payload.data, content_type=payload.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    if payload.private:
        response["Cache-Control"] = "private, no-store"
    return response

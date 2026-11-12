"""Signing a registered HR order on screen (order-signing board, Task 6): the signed PDF, the signer's record and the
saved signature picture. Nothing is written unless every check passes; a refusal leaves the order registered."""

import hashlib
import logging
from typing import Any

from accounts.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from employees import access, history_range
from employees.models import Employee, HrOrder, OrderSigning, OrderState, SavedSignature
from employees.services import order_docs, orders
from employees.services.orders import OrderError

logger = logging.getLogger(__name__)

SIGN_NEEDS_SALARY = "Ажилд авах тушаалыг цалин харах эрхгүй хэрэглэгч гарын үсэг зурж болохгүй."
METHOD_ERROR = "Гарын үсгийн арга буруу байна."
SIGNED_MESSAGE = "гарын үсэг зурсан (дэлгэц дээр), түгжсэн"
SIGNER_NAME_MAX = 100


def signer_name(user: User) -> str:
    """The name printed under the signature: the employee's name when the login is linked to one, else the account's
    full name, else the username."""
    employee = access.own_employee(user)
    if employee is not None and employee.full_name:
        return employee.full_name[:SIGNER_NAME_MAX]
    return (user.get_full_name() or user.username)[:SIGNER_NAME_MAX]


def saved_signature_png(user: User) -> bytes | None:
    """The signature picture the user saved, or None when they have none."""
    row = SavedSignature.objects.filter(user=user).first()
    if row is None or not row.image:
        return None
    try:  # a row whose picture file is gone (FileNotFoundError is an OSError) counts as no saved signature
        row.image.open("rb")
        try:
            return row.image.read()
        finally:
            row.image.close()
    except OSError:
        logger.warning("Saved signature file of user %s is missing", user.pk)
        return None


def _replace_saved_signature(user: User, png: bytes, stored: list[tuple[Any, str]]) -> tuple[Any, str] | None:
    """Point the user's saved signature at a new picture, updating the row in place (or creating it). The new file is
    recorded in `stored` before the row is written, so a caller that fails afterwards can delete it. The old file is
    NOT touched here: it is returned, and the caller removes it only once the transaction has committed."""
    row = SavedSignature.objects.filter(user=user).first()
    old = (row.image.storage, row.image.name) if row is not None and row.image else None
    if row is None:
        row = SavedSignature(user=user)
    row.image.save("signature.png", ContentFile(png), save=False)
    stored.append((row.image.storage, row.image.name))
    row.save()
    return old


def _delete_stored(stored: list[tuple[Any, str]]) -> None:
    """Delete each file, one by one. A failing delete is logged and skipped, so the other files are still removed and
    the caller's original error is never replaced."""
    for storage, name in stored:
        try:
            storage.delete(name)
        except Exception:
            logger.warning("Could not delete order file %s", name, exc_info=True)


def _delete_old_on_commit(old: tuple[Any, str] | None) -> None:
    """Remove the replaced picture's file only if the transaction commits; a rollback keeps it."""
    if old is None:
        return
    items = [old]
    transaction.on_commit(lambda: _delete_stored(items))


@transaction.atomic
def save_signature(user: User, png: bytes) -> None:
    """Keep this picture as the user's saved signature, replacing any earlier one (its file is removed on commit)."""
    stored: list[tuple[Any, str]] = []
    try:
        old = _replace_saved_signature(user, png, stored)
    except BaseException:
        _delete_stored(stored)  # files are not rolled back with the transaction
        raise
    _delete_old_on_commit(old)


def delete_saved_signature(user: User) -> None:
    SavedSignature.objects.filter(user=user).delete()


@transaction.atomic
def sign_order(order: HrOrder, *, by: User, png: bytes, method: str, remember: bool = False) -> HrOrder:
    """Sign a registered order with the already cleaned signature picture `png` (a PNG, see
    signature_image.clean_signature_data_url). The change the order waits for is applied at its own date; the signed
    PDF, the signing record and, when `remember`, the saved signature are written in the same transaction. Files are
    not transactional: every file this call stores is deleted again if a later step fails, and a replaced saved
    signature's old file is removed only on commit."""
    if method not in OrderSigning.Method.values:
        raise OrderError({"__all__": METHOD_ERROR})
    # Lock order: the same three locks, in the same order, as orders.attach_signed_file. They are taken here, once,
    # so the PDF is rendered from the locked order; attach_signed_file itself is not called (it would take them again).
    history_range.lock_employee(order.employee_id)
    Employee.objects.select_for_update().get(pk=order.employee_id)
    order = HrOrder.objects.select_for_update().get(pk=order.pk)
    if order.state != OrderState.REGISTERED:
        raise OrderError({"__all__": "Зөвхөн бүртгэсэн тушаалд гарын үсэг зурна."})
    if access.signing_needs_salary_right(by, order):
        raise OrderError({"__all__": SIGN_NEEDS_SALARY})

    name = signer_name(by)
    signed_at = timezone.now()
    stamp = order_docs.SignatureStamp(image=png, name=name, signed_at=signed_at)
    pdf = order_docs.render_signed_pdf(order, by, stamp)

    scan_before = order.file.name
    stored: list[tuple[Any, str]] = []
    try:
        orders._attach_signed_file_locked(
            order, ContentFile(pdf, name=f"order-{order.pk}-signed.pdf"), by=by, message=SIGNED_MESSAGE
        )
        order.file.open("rb")
        try:
            stored_pdf = order.file.read()
        finally:
            order.file.close()
        row = OrderSigning(
            order=order,
            signer=by,
            signer_name=name,
            signed_at=signed_at,
            method=method,
            pdf_sha256=hashlib.sha256(stored_pdf).hexdigest(),
        )
        row.image.save("signature.png", ContentFile(png), save=False)
        stored.append((row.image.storage, row.image.name))
        row.save()
        if remember:
            old = _replace_saved_signature(by, png, stored)
            _delete_old_on_commit(old)
    except BaseException:
        if order.file.name != scan_before:  # the signed PDF written by the helper, if it got that far
            stored.append((order.file.storage, order.file.name))
        _delete_stored(stored)  # the rows roll back with the transaction; the files do not
        raise
    return order

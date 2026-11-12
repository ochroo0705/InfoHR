"""The saved signature and the order signing records (order-signing board, Task 3)."""

from pathlib import Path

import pytest
from accounts.models import User
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from employees.models import Employee, HrOrder, OrderSigning, OrderType, SavedSignature

pytestmark = pytest.mark.django_db


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _order(employee: Employee) -> HrOrder:
    return HrOrder.objects.create(employee=employee, order_type=OrderType.HIRED, is_hire=True)


def test_saved_signature_stores_file_under_signatures_folder(actor: User) -> None:
    SavedSignature.objects.create(user=actor, image=ContentFile(b"png-bytes", name="sig.png"))
    stored = _files(Path(settings.ORDER_FILES_ROOT))
    assert len(stored) == 1
    assert next(iter(stored)).replace("\\", "/").startswith("signatures/")


def test_deleting_saved_signature_row_removes_file(actor: User) -> None:
    row = SavedSignature.objects.create(user=actor, image=ContentFile(b"png-bytes", name="sig.png"))
    root = Path(settings.ORDER_FILES_ROOT)
    assert _files(root)
    row.delete()
    assert _files(root) == set()


def test_deleting_user_cascades_and_removes_signature_file(actor: User) -> None:
    signer = User.objects.create(username="signer_cascade")
    SavedSignature.objects.create(user=signer, image=ContentFile(b"png-bytes", name="sig.png"))
    root = Path(settings.ORDER_FILES_ROOT)
    assert _files(root)
    signer.delete()
    assert SavedSignature.objects.count() == 0
    assert _files(root) == set()


def test_order_signing_keeps_signer_name_after_user_deleted(actor: User, hired: Employee) -> None:
    signer = User.objects.create(username="signer_gone")
    order = _order(hired)
    OrderSigning.objects.create(
        order=order,
        signer=signer,
        signer_name="Бат Дорж",
        signed_at=timezone.now(),
        method=OrderSigning.Method.DRAWN,
        image=ContentFile(b"png-bytes", name="sign.png"),
        pdf_sha256="a" * 64,
    )
    signer.delete()
    signing = OrderSigning.objects.get(order=order)
    assert signing.signer_id is None
    assert signing.signer_name == "Бат Дорж"


def test_one_signing_per_order(actor: User, hired: Employee) -> None:
    order = _order(hired)
    values = {
        "signer": actor,
        "signer_name": "Бат",
        "signed_at": timezone.now(),
        "method": OrderSigning.Method.SAVED,
        "image": ContentFile(b"png-bytes", name="sign.png"),
        "pdf_sha256": "b" * 64,
    }
    OrderSigning.objects.create(order=order, **values)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderSigning.objects.create(order=order, **values)

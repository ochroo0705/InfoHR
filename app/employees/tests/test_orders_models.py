from datetime import date
from pathlib import Path
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from macs.models import Command, Employee, EmployeeHistory

from employees.models import HrOrder, OrderState, OrderType

pytestmark = pytest.mark.django_db


def test_order_needs_event_or_hire(hired: Employee) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        HrOrder.objects.create(employee=hired, order_type=OrderType.HIRED, is_hire=False, event=None)
    assert OrderState.PENDING.label == "Дугаар оруулаагүй"
    order = HrOrder.objects.create(employee=hired, order_type=OrderType.HIRED, is_hire=True)
    assert order.state == OrderState.PENDING


def test_command_mirror_reads_production_row(hired: Employee) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO command (employee_ident, command, outdate, human_command, commandno, command_type) "
            "VALUES (%s, 'Ажилд авсан', '2026-01-05', 'Захирал', 'А/12', 1) RETURNING command_id",
            [hired.pk],
        )
        row = cur.fetchone()
        assert row is not None
    cmd = Command.objects.get(pk=row[0])
    assert cmd.number == "А/12" and cmd.order_type == 1 and cmd.date == date(2026, 1, 5)
    assert cmd.employee_id == hired.pk


def test_history_mirror_has_order_columns(hired: Employee) -> None:
    hist = EmployeeHistory.objects.filter(employee_id_value=hired.pk).first()
    assert hist is not None
    hist.move_type = 2
    hist.command_id_value = 77
    hist.branch_id_value = None
    hist.save()
    back = EmployeeHistory.objects.get(pk=hist.pk)
    assert (back.move_type, back.command_id_value) == (2, 77)


def test_order_file_storage_follows_settings(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path
    storage: Any = HrOrder._meta.get_field("file").storage
    assert storage.location == str(tmp_path.resolve())
    name = storage.save("2026/x.txt", ContentFile(b"x"))
    assert (tmp_path / "2026" / "x.txt").exists() and name.endswith("x.txt")

"""System log: imports, the MACS daily sync, exports and downloads write one entry each, and a log failure never
blocks the export, download, import or sync itself."""

# ruff: noqa: F811  (the test functions take the employee fixtures imported below, as the other test modules do)

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory
from django.urls import reverse
from employees.daily_sync import run_daily_sync
from employees.models import HrOrder, OrderTemplate, OrderType, StaffImportDraft
from employees.services import orders
from employees.staff_import.run import run_import
from employees.tests.conftest import actor, hired, job_values  # noqa: F401 (fixtures)
from employees.tests.test_staff_import_run import make_draft, person

from accounts import audit_context
from accounts.audit import record_export
from accounts.models import SystemLogEntry, User

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


def _login(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _rows(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action).order_by("id"))


def _remove_export_switch() -> None:
    export = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name="HR").permissions.remove(export)


def test_report_excel_is_logged_with_title_and_row_count(client: Client, hired: Any) -> None:
    user = _login(client, "HR", "hr_export")

    assert client.get("/reports/staff-list/excel/?cols=code").status_code == 200

    [row] = _rows("export_report")
    assert row.category == "export" and row.actor == user
    assert row.message.startswith("Ажилтны хүснэгт") and "1 мөр" in row.message


def test_refused_excel_download_is_not_logged(client: Client, hired: Any) -> None:
    _remove_export_switch()
    _login(client, "HR", "hr_no_export")

    assert client.get("/reports/staff-list/excel/").status_code == 403

    assert _rows("export_report") == []


def test_print_page_is_logged_with_a_readable_filter_label(client: Client, hired: Any) -> None:
    _login(client, "HR", "hr_print")

    assert client.get("/reports/staff-list/print/?state=working").status_code == 200

    [row] = _rows("print_page")
    assert row.category == "export"
    assert "Ажиллаж байгаа" in row.message and "state=" not in row.message


def test_order_download_names_order_number_and_employee_code(client: Client, hired: Any, actor: User) -> None:
    _login(client, "HR", "hr_orders")
    order = orders.register(
        HrOrder.objects.get(employee=hired, is_hire=True),
        number="А/12",
        date=date(2026, 1, 5),
        summary="",
        issued_by="",
        by=actor,
    )

    assert client.get(f"/employees/{hired.pk}/order/{order.pk}/document/").status_code == 200

    [row] = _rows("download_order")
    assert "А/12" in row.message and hired.code in row.message
    assert hired.family_name not in row.message and hired.given_name not in row.message


def test_rejected_rows_download_is_logged_with_its_count(client: Client) -> None:
    user = _login(client, "HR", "hr_rejected")
    draft = StaffImportDraft.objects.create(
        created_by=user, filename="a.xlsx", data=b"", state="imported", rejected_file=b"rows", rejected_count=2
    )

    assert client.get(reverse("employees:import_rejected", args=[draft.pk])).status_code == 200

    [row] = _rows("staff_import_rejected_download")
    assert row.category == "export" and "2 мөр" in row.message
    assert _rows("staff_import_download") == []  # the blank template's code is for the template only


def test_staff_import_is_logged_once_with_counts_and_importer() -> None:
    importer = User.objects.create_user("importer_one", password=PASSWORD)
    draft = make_draft([person()])

    run_import(draft, by=importer, allow_salary=False)

    [row] = _rows("staff_import")
    assert row.category == "import" and row.actor == importer
    assert row.message == "1 шинэ, 0 татгалзсан"


def test_daily_sync_is_logged_once_a_day_with_no_actor() -> None:
    visitor = User.objects.create_user("sync_visitor", password=PASSWORD)
    audit_context.set_context(visitor, "10.0.0.9")

    assert run_daily_sync(date(2026, 10, 29)) == 0

    [row] = _rows("macs_sync")
    assert row.actor is None and row.ip is None and row.message == "0 ажилтны мэдээлэл шинэчлэгдсэн"
    assert audit_context.current_user() == visitor  # the request's own user is back after the sync

    assert run_daily_sync(date(2026, 10, 29)) is None  # already synced today: nothing new
    assert len(_rows("macs_sync")) == 1


def test_export_logging_failure_does_not_block_download(
    client: Client, hired: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client, "HR", "hr_broken_log")

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(SystemLogEntry.objects, "create", boom)

    assert client.get("/reports/staff-list/excel/?cols=code").status_code == 200


def test_record_export_writes_label_and_count_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User.objects.create_user("export_user", password=PASSWORD)
    request = RequestFactory().get("/anything/")
    request.user = user

    record_export(request, "export_report", "Тайлан", filters="Төлөв: Ажиллаж байгаа", rows=3)

    [row] = _rows("export_report")
    assert row.message == "Тайлан · Төлөв: Ажиллаж байгаа · 3 мөр" and row.actor == user

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(SystemLogEntry.objects, "create", boom)
    record_export(request, "export_report", "Тайлан")  # must not raise


def test_employee_filter_is_not_written_to_the_log(client: Client, hired: Any) -> None:
    _login(client, "HR", "hr_person_filter")

    assert client.get(f"/reports/history/print/?employee={hired.pk}").status_code == 200
    assert client.get(f"/reports/history/excel/?employee={hired.pk}").status_code == 200

    rows = _rows("print_page") + _rows("export_report")
    assert len(rows) == 2
    for row in rows:
        assert "Ажилтан: сонгосон" in row.message
        assert hired.family_name not in row.message and hired.given_name not in row.message
        assert hired.code not in row.message


def test_admin_order_template_download_is_logged_with_its_own_code() -> None:
    admin_user = User.objects.create_superuser("template_admin", "admin@example.test", PASSWORD)
    client = Client()
    client.force_login(admin_user)
    template, _ = OrderTemplate.objects.get_or_create(order_type=OrderType.HIRED)

    response = client.get(reverse("admin:employees_ordertemplate_download", args=[template.pk]))

    assert response.status_code == 200
    [row] = _rows("order_template_download")
    assert row.category == "export" and row.message == "Тушаалын загвар: Ажилд орсон"
    assert _rows("download_order") == []

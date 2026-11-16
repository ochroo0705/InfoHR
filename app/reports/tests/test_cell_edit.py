"""Inline edit of one employee field from a report cell (reports.cell_edit)."""

from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.db import OperationalError
from django.http import QueryDict
from employees import stale
from employees.forms import EmployeeForm
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import records
from macs.models import Employee as MacsEmployee

from reports import cell_edit

pytestmark = pytest.mark.django_db


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


def _post(data: dict[str, str]) -> QueryDict:
    return QueryDict(urlencode(data))


def _loaded(user: User, employee: MacsEmployee) -> str:
    """The `loaded` snapshot the editor posts: what the form showed as stored."""
    return stale.snapshot(EmployeeForm(employee=Employee.objects.get(pk=employee.pk), user=user))


def test_manager_saves_private_phone(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr")
    loaded = _loaded(manager, hired)
    before = ActivityEntry.objects.filter(employee=hired).count()
    result = cell_edit.save(manager, hired.pk, "private_phone", _post({"private_phone": "99887766", "loaded": loaded}))
    assert result == cell_edit.CellResult(ok=True, text="99887766")
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"
    entries = ActivityEntry.objects.filter(employee=hired)
    assert entries.count() == before + 1
    entry = entries.order_by("-pk").first()
    assert entry is not None and entry.kind == ActivityKind.CHANGED
    assert entry.changes == [{"field": entry.changes[0]["field"], "old": "", "new": "99887766"}]


def test_invalid_email_gives_error(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr_email")
    loaded = _loaded(manager, hired)
    result = cell_edit.save(manager, hired.pk, "email", _post({"email": "not-an-email", "loaded": loaded}))
    assert result.ok is False
    assert result.error != ""
    hired.refresh_from_db()
    assert hired.email != "not-an-email"


def test_field_outside_editable_is_not_editable(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr_field")
    assert cell_edit.can_edit(manager, hired, "department") is False
    assert cell_edit.can_edit(manager, hired, "private_phone") is True


def test_user_without_manage_right_cannot_edit(hired: MacsEmployee) -> None:
    accountant = _user("Accountant", "cell_acc")
    assert cell_edit.can_edit(accountant, hired, "private_phone") is False


def test_stale_clash_refuses_and_writes_nothing(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr_stale")
    loaded = _loaded(manager, hired)
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")  # the old program changed it meanwhile
    result = cell_edit.save(manager, hired.pk, "private_phone", _post({"private_phone": "99887766", "loaded": loaded}))
    assert result == cell_edit.CellResult(ok=False, error=cell_edit.CLASH)
    hired.refresh_from_db()
    assert hired.private_phone == "99001122"


def test_nationality_needs_view_personal(hired: MacsEmployee) -> None:
    """nationality is a personal field (employees.models.PERSONAL_FIELDS) though no personal section shows it: a
    manager without view_personal must not edit it."""
    hr = _user("HR", "cell_hr_nat")
    assert cell_edit.can_edit(hr, hired, "nationality") is True
    manager = User.objects.create_user("cell_manager_nat", password="x-long-pass-123")  # noqa: S106
    for codename in ("manage_employees", "view_employees"):  # manage, but not view_personal
        manager.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    manager = User.objects.get(pk=manager.pk)  # fresh permission cache
    assert cell_edit.can_edit(manager, hired, "nationality") is False


def test_dry_run_returns_the_new_text_and_writes_nothing(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr_dry")
    loaded = _loaded(manager, hired)
    before = ActivityEntry.objects.filter(employee=hired).count()
    result = cell_edit.save(
        manager, hired.pk, "private_phone", _post({"private_phone": "99887766", "loaded": loaded}), dry_run=True
    )
    assert result == cell_edit.CellResult(ok=True, text="99887766")
    hired.refresh_from_db()
    assert hired.private_phone != "99887766"
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_database_error_during_the_write_is_refused_not_raised(
    hired: MacsEmployee, monkeypatch: pytest.MonkeyPatch
) -> None:
    from employees.views import DB_REFUSED

    manager = _user("HR", "cell_hr_db")
    loaded = _loaded(manager, hired)

    def database_down(*args: object, **kwargs: object) -> None:
        raise OperationalError("database is locked")

    monkeypatch.setattr(records, "update_employee", database_down)
    result = cell_edit.save(manager, hired.pk, "private_phone", _post({"private_phone": "99887766", "loaded": loaded}))
    assert result == cell_edit.CellResult(ok=False, error=DB_REFUSED)
    hired.refresh_from_db()
    assert hired.private_phone != "99887766"


def test_dry_run_of_invalid_email_gives_the_error(hired: MacsEmployee) -> None:
    manager = _user("HR", "cell_hr_dry_email")
    loaded = _loaded(manager, hired)
    result = cell_edit.save(
        manager, hired.pk, "email", _post({"email": "not-an-email", "loaded": loaded}), dry_run=True
    )
    assert result.ok is False
    assert result.error != ""
    hired.refresh_from_db()
    assert hired.email != "not-an-email"

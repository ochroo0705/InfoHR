"""The employee page save as a service (employees.services.page_writes): the rights, the stale check and the write,
without the request. The Django view tests (test_views, test_stale_save, test_scope_screens) cover the HTTP side."""

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.utils.datastructures import MultiValueDict
from macs.models import Bank

from employees import stale
from employees.forms import EmployeeForm
from employees.models import ActivityEntry, Employee
from employees.services import page_writes

from .conftest import named
from .test_views import save_payload

pytestmark = pytest.mark.django_db


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


def _post(data: dict[str, str]) -> MultiValueDict:
    return RequestFactory().post("/employees/1/save/", data).POST


def test_changed_work_phone_is_written(hired: Employee) -> None:
    hr = _user("HR", "hr_work_phone")
    result = page_writes.save_page(hr, hired, _post(save_payload(hired, work_phone="77110022")), MultiValueDict())
    assert result.ok is True
    hired.refresh_from_db()
    assert hired.work_phone == "77110022"


def test_invalid_email_is_a_field_error(hired: Employee) -> None:
    hr = _user("HR", "hr_bad_email")
    result = page_writes.save_page(hr, hired, _post(save_payload(hired, email="not-an-email")), MultiValueDict())
    assert result.ok is False
    assert result.field_errors["email"]
    hired.refresh_from_db()
    assert hired.email != "not-an-email"


def test_field_changed_by_both_sides_is_a_conflict_and_nothing_is_written(hired: Employee) -> None:
    hr = _user("HR", "hr_clash")
    loaded = stale.snapshot(page_writes.page_form_state(hr, hired)[0])  # what the page showed
    Employee.objects.filter(pk=hired.pk).update(work_phone="99001122")  # MACS changed it meanwhile
    data = save_payload(hired, work_phone="88112233", loaded=loaded)
    result = page_writes.save_page(hr, hired, _post(data), MultiValueDict())
    assert result.ok is False
    assert result.conflicts["work_phone"] == "99001122"
    assert result.field_errors["work_phone"]
    assert result.loaded  # a fresh snapshot, so the page can be re-rendered with the current values
    hired.refresh_from_db()
    assert hired.work_phone == "99001122"


def test_same_post_with_resolve_mine_writes(hired: Employee) -> None:
    hr = _user("HR", "hr_resolve")
    loaded = stale.snapshot(page_writes.page_form_state(hr, hired)[0])
    Employee.objects.filter(pk=hired.pk).update(work_phone="99001122")
    data = save_payload(hired, work_phone="88112233", loaded=loaded)
    data["resolve-work_phone"] = "mine"
    result = page_writes.save_page(hr, hired, _post(data), MultiValueDict())
    assert result.ok is True
    hired.refresh_from_db()
    assert hired.work_phone == "88112233"


def test_salary_only_user_writes_salary_fields_and_not_work_phone(hired: Employee) -> None:
    accountant = _user("Accountant", "acc_salary_only")
    bank = named(Bank, "Хаан банк")
    stored_phone = hired.work_phone
    data = {"si-bank": str(bank.pk), "work_phone": "77001122"}
    result = page_writes.save_page(accountant, hired, _post(data), MultiValueDict())
    assert result.ok is True
    assert result.form is None
    hired.refresh_from_db()
    assert hired.bank_id == bank.pk
    assert hired.work_phone == stored_phone


def test_user_with_neither_right_is_refused(hired: Employee) -> None:
    plain = _user("Employee", "plain_user")
    with pytest.raises(PermissionDenied):
        page_writes.save_page(plain, hired, _post({"work_phone": "77001122"}), MultiValueDict())


def test_invalid_stored_field_not_posted_goes_to_form_errors_with_its_label(hired: Employee) -> None:
    hr = _user("HR", "hr_hidden_error")
    Employee.objects.filter(pk=hired.pk).update(email="not-an-email")  # stored value is invalid, the post omits it
    data = save_payload(hired)
    data.pop("email", None)  # a blank email is not posted
    result = page_writes.save_page(hr, hired, _post(data), MultiValueDict())
    label = EmployeeForm(employee=hired, user=hr).fields["email"].label
    assert result.ok is False
    assert "email" not in result.field_errors
    assert any(line.startswith(f"{label}: ") for line in result.form_errors)


def _section_post(values: dict[str, str], loaded: str) -> MultiValueDict:
    return _post({**values, "loaded": loaded})


def test_identity_section_change_is_written_and_logged(hired: Employee) -> None:
    hr = _user("HR", "hr_section_write")
    loaded = stale.snapshot(page_writes.employee_form(hr, hired))
    result = page_writes.save_section(hr, hired, "identity", _section_post({"clan_name": "Ботгон"}, loaded))
    assert result.ok is True
    assert result.field_errors == {} and result.conflicts == {}
    assert result.loaded  # a fresh snapshot of the stored employee
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон"
    assert ActivityEntry.objects.filter(employee=hired, personal=True, message="Хувийн мэдээлэл өөрчилсөн").exists()


def test_identity_section_clash_returns_conflicts_and_writes_nothing(hired: Employee) -> None:
    hr = _user("HR", "hr_section_clash")
    loaded = stale.snapshot(page_writes.employee_form(hr, hired))
    Employee.objects.filter(pk=hired.pk).update(clan_name="Өөр")  # MACS changed it meanwhile
    result = page_writes.save_section(hr, hired, "identity", _section_post({"clan_name": "Шинэ"}, loaded))
    assert result.ok is False
    assert result.conflicts["clan_name"] == "Өөр"
    assert result.field_errors["clan_name"]
    assert result.loaded
    hired.refresh_from_db()
    assert hired.clan_name == "Өөр"


def test_blank_required_field_outside_the_section_does_not_block(hired: Employee) -> None:
    hr = _user("HR", "hr_section_outside")
    loaded = stale.snapshot(page_writes.employee_form(hr, hired))
    Employee.objects.filter(pk=hired.pk).update(work_phone="")  # old data: required, but not in the section
    result = page_writes.save_section(hr, hired, "identity", _section_post({"clan_name": "Ботгон"}, loaded))
    assert result.ok is True
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон"


def test_unknown_section_is_404(hired: Employee) -> None:
    hr = _user("HR", "hr_section_unknown")
    with pytest.raises(Http404):
        page_writes.save_section(hr, hired, "nope", _post({"clan_name": "Ботгон"}))


@pytest.mark.parametrize("role", ["Employee", "Accountant"])
def test_section_save_without_the_personal_right_is_refused(hired: Employee, role: str) -> None:
    user = _user(role, f"no_personal_{role.lower()}")
    with pytest.raises(PermissionDenied):
        page_writes.save_section(user, hired, "identity", _post({"clan_name": "Ботгон"}))
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_section_save_by_a_viewer_who_cannot_manage_is_refused(hired: Employee) -> None:
    user = _user("Accountant", "personal_viewer_only")
    user.user_permissions.add(Permission.objects.get(codename="view_personal", content_type__app_label="macs"))
    with pytest.raises(PermissionDenied):
        page_writes.save_section(user, hired, "identity", _post({"clan_name": "Ботгон"}))
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"

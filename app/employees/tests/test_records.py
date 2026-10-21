import pytest
from accounts.models import User
from lists.models import MONGOLIA, MeaningfulEntry
from macs.models import Bank, Country

from employees.models import Employee, ensure_ext
from employees.services import records

from .conftest import named

pytestmark = pytest.mark.django_db


@pytest.mark.django_db
def test_edit_routes_ext_fields_and_recomputes_fullname(hired: Employee, actor: User) -> None:
    changes = records.update_employee(hired, {"given_name": "Номин", "prior_service_months": 3}, actor)
    hired.refresh_from_db()
    assert hired.fullname == "Батын".ljust(25) + ", Номин"
    assert hired.ext.prior_service_months == 3
    assert {c["field"] for c in changes} == {"Нэр", "Өмнөх ажилласан сар"}


@pytest.mark.django_db
def test_citizenship_sets_foreign_flag(hired: Employee, actor: User) -> None:
    mongolia = Country.objects.create(name="Монгол")
    china = Country.objects.create(name="Хятад")
    MeaningfulEntry.objects.create(key=MONGOLIA, value=mongolia.pk)
    records.update_employee(hired, {"citizenship": china}, actor)
    hired.refresh_from_db()
    assert hired.foreign_emp == 1
    records.update_employee(hired, {"citizenship": mongolia}, actor)
    hired.refresh_from_db()
    assert hired.foreign_emp is None


@pytest.mark.django_db
def test_account_number_goes_to_ecode(hired: Employee, actor: User) -> None:
    records.update_salary_insurance(hired, {"account_no": "5012345678", "bank": named(Bank, "Хаан")}, actor)
    hired.refresh_from_db()
    assert hired.account_no == "5012345678" and str(hired.bank) == "Хаан"


@pytest.mark.django_db
def test_noop_edit_writes_nothing(hired: Employee, actor: User) -> None:
    ext = ensure_ext(hired)
    ext.updated_by = None
    ext.save()
    changed_date = hired.changed_date
    changes = records.update_employee(hired, {"given_name": hired.given_name}, actor)
    hired.refresh_from_db()
    ext.refresh_from_db()
    assert changes == []
    assert hired.changed_date == changed_date
    assert ext.updated_by is None


@pytest.mark.django_db
def test_replacing_photo_logs_one_activity_entry(hired: Employee, actor: User) -> None:
    from employees.models import ActivityEntry

    before = ActivityEntry.objects.filter(employee=hired).count()
    records.set_photo(hired, b"first", by=actor)
    records.set_photo(hired, b"second", by=actor)
    assert ActivityEntry.objects.filter(employee=hired).count() == before + 2
    records.set_photo(hired, None, by=actor)
    records.set_photo(hired, None, by=actor)  # nothing left to remove: no entry
    assert ActivityEntry.objects.filter(employee=hired).count() == before + 3

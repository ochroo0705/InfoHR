import pytest
from django.test import Client
from employees.services import macs_writes, records
from employees.services.macs_writes import ListEntryInUse
from macs.models import City, Country, District, FiredReason, MaritalStatus

from lists.models import DEATH, MONGOLIA, MeaningfulEntry


@pytest.mark.django_db
def test_add_rename_remove(admin_client: Client) -> None:
    admin_client.post("/lists/marital_status/add/", {"name": "Гэрлэсэн"})
    entry = MaritalStatus.objects.get(name="Гэрлэсэн")
    admin_client.post(f"/lists/marital_status/{entry.pk}/", {"name": "Гэрлэсэн (батлагдсан)"})
    entry.refresh_from_db()
    assert entry.name == "Гэрлэсэн (батлагдсан)"
    admin_client.post(f"/lists/marital_status/{entry.pk}/delete/")
    assert not MaritalStatus.objects.filter(pk=entry.pk).exists()


@pytest.mark.django_db
def test_entry_in_use_by_former_employee_cannot_be_removed(admin_client: Client, hired, actor) -> None:  # type: ignore[no-untyped-def]
    married = MaritalStatus.objects.create(name="Гэрлэсэн")
    records.update_employee(hired, {"marital_status": married}, actor)
    # The employee has left: status inactive, emptype 3 (the same flags macs_writes uses for a leaver).
    macs_writes.update_employee_columns(hired, {"status": "inactive", "emptype": 3, "contract_flag": "no"})
    hired.refresh_from_db()
    assert hired.status == "inactive"
    response = admin_client.post(f"/lists/marital_status/{married.pk}/delete/")
    assert MaritalStatus.objects.filter(pk=married.pk).exists()  # Review Focus 4
    assert "1 ажилтан" in response.content.decode()


@pytest.mark.django_db
def test_entry_in_employee_history_cannot_be_removed(hired, job_values) -> None:  # type: ignore[no-untyped-def]
    department = hired.department
    macs_writes.snapshot_history(hired)  # the history row keeps the department after the employee moves on
    macs_writes.update_employee_columns(hired, {"department": None})
    with pytest.raises(ListEntryInUse):
        macs_writes.delete_department(department)
    assert department.__class__.objects.filter(pk=department.pk).exists()


@pytest.mark.django_db
def test_fired_reason_used_only_by_history_row_cannot_be_removed(hired) -> None:  # type: ignore[no-untyped-def]
    from macs.models import EmployeeHistory

    reason = FiredReason.objects.create(name="Туршилтын шалтгаан")
    macs_writes.snapshot_history(hired)
    n = EmployeeHistory.objects.filter(employee_id_value=hired.pk).update(fired_reason_id_value=reason.pk)
    assert hired.fired_reason_id != reason.pk
    with pytest.raises(ListEntryInUse, match=str(n)):
        macs_writes.delete_list_entry(reason)
    assert FiredReason.objects.filter(pk=reason.pk).exists()


@pytest.mark.django_db
def test_unused_department_is_removed() -> None:
    department = macs_writes.save_department("Туршилт")
    macs_writes.delete_department(department)
    assert not department.__class__.objects.filter(pk=department.pk).exists()


@pytest.mark.django_db
def test_district_belongs_to_a_city(admin_client: Client) -> None:
    ub = City.objects.create(name="Улаанбаатар")
    admin_client.post("/lists/district/add/", {"name": "Сүхбаатар", "city": ub.pk})
    assert District.objects.get(name="Сүхбаатар").city == ub


@pytest.mark.django_db
def test_admin_picks_mongolia(admin_client: Client) -> None:
    mn = Country.objects.create(name="Монгол")
    admin_client.post("/lists/meaning/", {MONGOLIA: mn.pk})
    assert MeaningfulEntry.get(MONGOLIA) == mn.pk


@pytest.mark.django_db
def test_lists_need_permission(client: Client, actor) -> None:  # type: ignore[no-untyped-def]
    client.force_login(actor)
    assert client.get("/lists/").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/lists/"),
        ("get", "/lists/marital_status/"),
        ("get", "/lists/marital_status/add/"),
        ("post", "/lists/marital_status/add/"),
        ("get", "/lists/marital_status/1/"),
        ("post", "/lists/marital_status/1/"),
        ("post", "/lists/marital_status/1/delete/"),
        ("get", "/lists/meaning/"),
        ("post", "/lists/meaning/"),
    ],
)
def test_every_lists_view_needs_permission(client: Client, actor, method: str, url: str) -> None:  # type: ignore[no-untyped-def]
    client.force_login(actor)
    assert getattr(client, method)(url).status_code == 403


@pytest.mark.django_db
def test_fired_reason_list_add_rename_remove(admin_client: Client, hired) -> None:  # type: ignore[no-untyped-def]
    admin_client.post("/lists/fired_reason/add/", {"name": "Туршилтын шалтгаан"})
    entry = FiredReason.objects.get(name="Туршилтын шалтгаан")
    admin_client.post(f"/lists/fired_reason/{entry.pk}/", {"name": "Шинэ шалтгаан"})
    entry.refresh_from_db()
    assert entry.name == "Шинэ шалтгаан"
    # An employee's production row points at it: removal is refused with the count.
    type(hired).objects.filter(pk=hired.pk).update(fired_reason=entry)
    response = admin_client.post(f"/lists/fired_reason/{entry.pk}/delete/")
    assert FiredReason.objects.filter(pk=entry.pk).exists()
    assert "1 ажилтан" in response.content.decode()
    type(hired).objects.filter(pk=hired.pk).update(fired_reason=None)
    admin_client.post(f"/lists/fired_reason/{entry.pk}/delete/")
    assert not FiredReason.objects.filter(pk=entry.pk).exists()


@pytest.mark.django_db
def test_death_meaning_settable(admin_client: Client) -> None:
    dead = FiredReason.objects.create(name="Нас барсан")
    admin_client.post("/lists/meaning/", {DEATH: dead.pk})
    assert MeaningfulEntry.get(DEATH) == dead.pk

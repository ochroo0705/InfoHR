from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from employees.forms import EmployeeForm
from employees.models import Department, Employee, SalaryInsurance
from employees.services import history

from .conftest import new_employee

pytestmark = pytest.mark.django_db


def login_as(client: Client, role: str, name: str = "viewer") -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def test_list_shows_active_hides_left(client: Client, hired: Employee, actor: User) -> None:
    fields = ("position", "department", "employee_type", "contract_type")
    other = history.hire(
        new_employee("УБ00000001"),
        start=date(2025, 1, 1),
        job={**{f: getattr(hired.job_records.get(), f) for f in fields}, "status": "active"},
        salary=None,
        by=actor,
    )
    history.change_job(
        other, effective=date(2025, 6, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
    )
    login_as(client, "HR")
    body = client.get("/employees/?view=table").content.decode()
    assert hired.code in body and other.code not in body
    assert other.code in client.get("/employees/?view=table&state=left").content.decode()


def test_list_search_htmx_returns_rows_only(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.get("/employees/?view=table&q=Сараа", HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert hired.code in body and "<html" not in body


def test_grid_view_shows_cards_not_table(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get("/employees/?view=grid").content.decode()
    assert reverse("employees:detail", args=[hired.pk]) in body
    assert "<table" not in body


def test_grid_htmx_returns_cards_only(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get("/employees/?view=grid", HTTP_HX_REQUEST="true").content.decode()
    assert reverse("employees:detail", args=[hired.pk]) in body
    assert "<table" not in body and "<html" not in body


def test_history_restore_returns_full_page(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.get("/employees/?view=grid", HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true")
    assert "<html" in response.content.decode()


def test_grid_applies_state_filter(client: Client, hired: Employee, actor: User) -> None:
    fields = ("position", "department", "employee_type", "contract_type")
    other = history.hire(
        new_employee("УБ00000002"),
        start=date(2025, 1, 1),
        job={**{f: getattr(hired.job_records.get(), f) for f in fields}, "status": "active"},
        salary=None,
        by=actor,
    )
    history.change_job(
        other, effective=date(2025, 6, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
    )
    login_as(client, "HR")
    other_url = reverse("employees:detail", args=[other.pk])
    assert other_url not in client.get("/employees/?view=grid").content.decode()
    body = client.get("/employees/?view=grid&state=left", HTTP_HX_REQUEST="true").content.decode()
    assert other_url in body and reverse("employees:detail", args=[hired.pk]) not in body


def test_future_hire_listed_as_upcoming(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(
        new_employee(),
        start=timezone.localdate() + timedelta(days=5),
        job=job_values,
        salary=Decimal("1"),
        by=actor,
    )
    login_as(client, "HR")
    body = client.get("/employees/?view=table").content.decode()
    assert emp.code in body and "Ажилд орох" in body


def test_employee_role_list_shows_only_self(client: Client, hired: Employee) -> None:
    login_as(client, "Employee")
    assert hired.code not in client.get("/employees/").content.decode()


def test_hr_page_hides_salary_everywhere(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert hired.full_name in body and "Хувийн" in body
    assert "2500000" not in body and "2 500 000" not in body and "2,500,000" not in body
    assert "Цалин, даатгал" not in body  # tab not rendered


def test_accountant_sees_salary_not_personal(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "2 500 000" in body and "Регистрийн дугаар" not in body


def test_employee_role_404_on_other_page(client: Client, hired: Employee) -> None:
    login_as(client, "Employee")
    assert client.get(f"/employees/{hired.pk}/").status_code == 404


def test_own_page_has_no_notes(client: Client, hired: Employee, actor: User) -> None:
    from employees.services.records import add_note

    me = login_as(client, "Employee", "me")
    hired.user = me
    hired.save()
    add_note(hired, text="дотоод тэмдэглэл", by=actor)
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "дотоод тэмдэглэл" not in body and "2 500 000" not in body


def _hr_edits_personal(hired: Employee, actor: User) -> None:
    from employees.services.records import update_employee

    update_employee(hired, {"register_no": "УБ11223344", "address": "Баянзүрх 5-р хороо"}, by=actor)


def test_personal_changes_hidden_from_accountant(client: Client, hired: Employee, actor: User) -> None:
    _hr_edits_personal(hired, actor)
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    for text in ("УБ99112233", "УБ11223344", "Баянзүрх 5-р хороо", "Хувийн мэдээлэл өөрчилсөн"):
        assert text not in body


def test_personal_changes_shown_to_hr(client: Client, hired: Employee, actor: User) -> None:
    _hr_edits_personal(hired, actor)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "УБ11223344" in body and "Баянзүрх 5-р хороо" in body and "Хувийн мэдээлэл өөрчилсөн" in body


def test_personal_changes_shown_on_own_page(client: Client, hired: Employee, actor: User) -> None:
    _hr_edits_personal(hired, actor)
    hired.user = login_as(client, "Employee", "me")
    hired.save()
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Хувийн мэдээлэл өөрчилсөн" in body and "УБ11223344" in body


def test_salary_insurance_change_hidden_without_switch(client: Client, hired: Employee, actor: User) -> None:
    from employees.services.records import update_salary_insurance

    update_salary_insurance(hired, {"account_no": "123456789"}, by=actor)
    login_as(client, "HR")
    hr_body = client.get(f"/employees/{hired.pk}/").content.decode()
    hired.user = login_as(client, "Employee", "me")
    hired.save()
    own_body = client.get(f"/employees/{hired.pk}/").content.decode()
    for body in (hr_body, own_body):
        assert "123456789" not in body and "Цалин, даатгалын мэдээлэл өөрчилсөн" not in body
    login_as(client, "Accountant", "acc")
    acc = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "123456789" in acc and "Цалин, даатгалын мэдээлэл өөрчилсөн" in acc


def test_add_note_rejects_blank(hired: Employee, actor: User) -> None:
    from employees.services.records import add_note

    with pytest.raises(ValueError):
        add_note(hired, text="   ", by=actor)


def test_hr_corrects_job_with_reason(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    job = hired.job_records.get()
    data = {
        "position": job.position_id,
        "department": job.department_id,
        "employee_type": "part_time",
        "status": "active",
        "contract_type": "open_ended",
        "contract_no": "",
        "reason": "буруу төрөл",
    }
    response = client.post(f"/employees/{hired.pk}/job/{job.pk}/correct/", data, HTTP_HX_REQUEST="true")
    assert response.headers["HX-Refresh"] == "true"
    job.refresh_from_db()
    assert job.employee_type == "part_time"


def test_correction_without_reason_shows_error(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    job = hired.job_records.get()
    data = {
        "position": job.position_id,
        "department": job.department_id,
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
        "reason": "",
    }
    body = client.post(f"/employees/{hired.pk}/job/{job.pk}/correct/", data).content.decode()
    assert "шаардлагатай" in body or "заавал" in body


def test_hr_cannot_correct_salary(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    record = hired.salary_records.get()
    assert client.get(f"/employees/{hired.pk}/salary/{record.pk}/correct/").status_code == 403


def test_accountant_corrects_salary(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    record = hired.salary_records.get()
    client.post(f"/employees/{hired.pk}/salary/{record.pk}/correct/", {"amount": "2600000", "reason": "typo"})
    record.refresh_from_db()
    assert record.base_salary == Decimal("2600000.00")


def save_payload(employee: Employee, **extra: str) -> dict[str, str]:
    """What the page's form posts: every field of the employee as it is now, then the overrides."""
    form = EmployeeForm(instance=employee)
    data = {name: form[name].value() for name in form.fields if name != "photo" and form[name].value() is not None}
    data = {k: (v.isoformat() if isinstance(v, date) else str(v)) for k, v in data.items()}
    data.update(extra)
    return {k: v for k, v in data.items() if v != "False"}


def test_accountant_saves_bank_details_but_not_employee_fields(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'id="emp-form"' in body and 'id="save-bar"' in body and 'name="si-bank"' in body
    data = {"si-bank": "Хаан банк", "work_schedule": "hack", "family_name": "Hack"}
    assert client.post(f"/employees/{hired.pk}/save/", data).status_code == 303
    hired.refresh_from_db()
    assert hired.work_schedule == "" and hired.family_name == "Батын"
    assert SalaryInsurance.objects.get(employee=hired).bank == "Хаан банк"
    assert hired.activity.get(message__contains="Цалин, даатгалын").sensitive


def test_user_without_manage_perms_cannot_save(client: Client, hired: Employee) -> None:
    login_as(client, "Employee", "nobody")
    assert client.post(f"/employees/{hired.pk}/save/", {"si-bank": "x"}).status_code in (403, 404)
    user = User.objects.create_user("viewer2", password="x-long-pass-123")  # noqa: S106
    from django.contrib.auth.models import Permission

    user.user_permissions.add(Permission.objects.get(codename="view_employees"))
    client.force_login(user)
    assert client.post(f"/employees/{hired.pk}/save/", {"si-bank": "x"}).status_code == 403


def test_accountant_cannot_save_employee(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    client.post(f"/employees/{hired.pk}/save/", save_payload(hired, work_schedule="x"))
    hired.refresh_from_db()
    assert hired.work_schedule == ""
    assert client.get(f"/employees/{hired.pk}/save/").status_code == 405


def test_accountant_page_has_no_salary_or_register_inputs(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'name="register_no"' not in body and 'name="family_name"' not in body
    login_as(client, "HR", "hr2")  # HR has no salary access
    assert 'name="si-' not in client.get(f"/employees/{hired.pk}/").content.decode()


def test_photo_clear_removes_photo(client: Client, hired: Employee, settings: Any, tmp_path: Any) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    hired.photo.save("p.png", SimpleUploadedFile("p.png", PNG, content_type="image/png"))
    login_as(client, "HR")
    assert 'name="photo-clear"' in client.get(f"/employees/{hired.pk}/").content.decode()
    response = client.post(f"/employees/{hired.pk}/save/", save_payload(hired) | {"photo-clear": "on"})
    assert response.status_code == 303
    hired.refresh_from_db()
    assert not hired.photo and hired.photo.name == ""


def test_manager_without_personal_access_can_save_work_fields(client: Client, hired: Employee) -> None:
    from django.contrib.auth.models import Permission

    user = User.objects.create_user("mgr", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_employees", "manage_employees"]))
    client.force_login(user)
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'name="work_schedule"' in body and 'name="register_no"' not in body
    response = client.post(
        f"/employees/{hired.pk}/save/",
        {
            "work_schedule": "08-17",
            "given_name": "Сараа",
            "family_name": "Батын",
            "work_phone": "99112233",
            "first_hire_date": "2026-01-05",
            "work_conditions": "normal",
        },
    )
    assert response.status_code == 303
    hired.refresh_from_db()
    assert hired.work_schedule == "08-17" and hired.register_no == "УБ99112233"


def test_accountant_page_has_no_inputs(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'name="work_schedule"' not in body and 'name="family_name"' not in body


def test_hr_page_has_inline_inputs_and_save_bar(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'name="family_name"' in body and 'name="work_schedule"' in body and 'name="register_no"' in body
    assert 'id="save-bar"' in body and "Хадгалах" in body and "Болих" in body
    assert 'name="si-bank"' not in body  # HR has no salary access


def test_hr_saves_work_and_personal_fields(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = save_payload(hired, work_schedule="08:00-17:00", address="Баянзүрх 5-р хороо", tab="personal")
    response = client.post(f"/employees/{hired.pk}/save/", data)
    assert response.status_code == 303 and response["Location"] == f"/employees/{hired.pk}/#personal"
    hired.refresh_from_db()
    assert hired.work_schedule == "08:00-17:00" and hired.address == "Баянзүрх 5-р хороо"
    work = hired.activity.get(kind="changed", personal=False)
    personal = hired.activity.get(kind="changed", personal=True)
    assert [c["field"] for c in work.changes] == ["Ажлын цагийн хуваарь"]
    assert [c["field"] for c in personal.changes] == ["Хаяг"]


def test_save_with_unknown_tab_redirects_to_plain_detail(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", save_payload(hired, tab="evil"))
    assert response.status_code == 303 and response["Location"] == f"/employees/{hired.pk}/"


def test_save_duplicate_register_shows_error_and_keeps_input(
    client: Client, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _other_employee(actor, job_values)
    login_as(client, "HR")
    data = save_payload(hired, register_no=other.register_no, work_schedule="typed value")
    response = client.post(f"/employees/{hired.pk}/save/", data)
    body = response.content.decode()
    assert response.status_code == 400
    assert "аль хэдийн бүртгэлтэй" in body and "typed value" in body
    assert 'id="save-bar"' in body and "hidden sticky" not in body
    hired.refresh_from_db()
    assert hired.register_no == "УБ99112233" and hired.work_schedule == ""


def test_hr_without_salary_permission_cannot_change_bank(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = save_payload(hired, work_schedule="x") | {"si-bank": "Хаан банк", "si-account_no": "123"}
    assert client.post(f"/employees/{hired.pk}/save/", data).status_code == 303
    assert not SalaryInsurance.objects.filter(employee=hired).exists()
    assert not hired.activity.filter(message__contains="Цалин, даатгалын").exists()


def test_admin_saves_bank_details(client: Client, hired: Employee) -> None:
    login_as(client, "Admin")
    assert 'name="si-bank"' in client.get(f"/employees/{hired.pk}/").content.decode()
    data = save_payload(hired) | {"si-bank": "Хаан банк", "si-account_no": "5001"}
    response = client.post(f"/employees/{hired.pk}/save/", data)
    assert response.status_code == 303
    details = SalaryInsurance.objects.get(employee=hired)
    assert details.bank == "Хаан банк" and details.account_no == "5001"
    entry = hired.activity.get(message__contains="Цалин, даатгалын")
    assert entry.sensitive
    assert {c["field"] for c in entry.changes} == {"Банк", "Дансны дугаар"}


def test_note_added(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.post(f"/employees/{hired.pk}/note/", {"text": "дипломын хуулбар дутуу"}).content.decode()
    assert "дипломын хуулбар дутуу" in body


def test_blank_note_does_not_crash(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.post(f"/employees/{hired.pk}/note/", {"text": "   "}).status_code == 200


FAMILY_DATA = {
    "family-TOTAL_FORMS": "1",
    "family-INITIAL_FORMS": "0",
    "family-MIN_NUM_FORMS": "0",
    "family-MAX_NUM_FORMS": "1000",
    "family-0-name": "Дорж",
    "family-0-relation": "Эцэг",
    "family-0-birth_year": "1960",
}


def test_hr_edits_family_list(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    client.post(f"/employees/{hired.pk}/family/", FAMILY_DATA)
    assert hired.family.get().name == "Дорж"
    assert hired.activity.filter(kind="changed", message__contains="Гэр бүл").exists()


def test_family_entry_hidden_from_accountant(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    client.post(f"/employees/{hired.pk}/family/", FAMILY_DATA)
    assert "Гэр бүл жагсаалт" in client.get(f"/employees/{hired.pk}/").content.decode()
    login_as(client, "Accountant", "acc")
    assert "Гэр бүл жагсаалт" not in client.get(f"/employees/{hired.pk}/").content.decode()


TALENT_GIFT_DATA = {
    "talents-TOTAL_FORMS": "1",
    "talents-INITIAL_FORMS": "0",
    "talents-MIN_NUM_FORMS": "0",
    "talents-MAX_NUM_FORMS": "1000",
    "talents-0-name": "Хөгжим",
    "talents-0-trained_year": "2010",
    "talents-0-description": "Гитар",
}
GIFT_DATA = {
    "gifts-TOTAL_FORMS": "1",
    "gifts-INITIAL_FORMS": "0",
    "gifts-MIN_NUM_FORMS": "0",
    "gifts-MAX_NUM_FORMS": "1000",
    "gifts-0-gift_type": "Шинэ жил",
    "gifts-0-given_date": "2026-01-01",
    "gifts-0-child_count": "2",
    "gifts-0-amount": "50000",
    "gifts-0-note": "",
}


def test_hr_edits_talents_and_gifts(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    client.post(f"/employees/{hired.pk}/talents/", TALENT_GIFT_DATA)
    client.post(f"/employees/{hired.pk}/gifts/", GIFT_DATA)
    assert hired.talents.get().name == "Хөгжим"
    assert hired.gifts.get().gift_type == "Шинэ жил"
    assert hired.activity.filter(kind="changed", personal=True, message__contains="Авьяас").exists()
    assert hired.activity.filter(kind="changed", personal=True, message__contains="Олгосон бэлэг").exists()


def test_talents_and_gifts_refused_for_accountant(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.get(f"/employees/{hired.pk}/talents/").status_code == 403
    assert client.get(f"/employees/{hired.pk}/gifts/").status_code == 403


def test_talent_gift_entries_hidden_from_accountant(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    client.post(f"/employees/{hired.pk}/talents/", TALENT_GIFT_DATA)
    client.post(f"/employees/{hired.pk}/gifts/", GIFT_DATA)
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Авьяас жагсаалт" in page and "Олгосон бэлэг жагсаалт" in page
    login_as(client, "Accountant", "acc")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Авьяас жагсаалт" not in page and "Олгосон бэлэг жагсаалт" not in page


def test_set_salary_refused_when_salary_exists(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    url = f"/employees/{hired.pk}/salary/set/"
    assert client.get(url).status_code == 403
    assert client.post(url, {"effective": "2026-06-01", "amount": "3000000"}).status_code == 403
    record = hired.salary_records.get()
    assert hired.salary_records.count() == 1 and record.base_salary == Decimal("2500000.00")


def _other_employee(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        new_employee("УБ00000002"), start=date(2026, 1, 5), job=job_values, salary=Decimal("1"), by=actor
    )


def test_job_correction_rejects_other_employees_record(
    client: Client, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _other_employee(actor, job_values)
    record = other.job_records.get()
    login_as(client, "HR")
    data = {**{k: v for k, v in job_values.items()}, "position": record.position_id, "department": record.department_id}
    data.update({"employee_type": "part_time", "reason": "x"})
    assert client.post(f"/employees/{hired.pk}/job/{record.pk}/correct/", data).status_code == 404
    record.refresh_from_db()
    assert record.employee_type == "full_time"


def test_salary_correction_rejects_other_employees_record(
    client: Client, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _other_employee(actor, job_values)
    record = other.salary_records.get()
    login_as(client, "Accountant")
    url = f"/employees/{hired.pk}/salary/{record.pk}/correct/"
    assert client.post(url, {"amount": "9", "reason": "x"}).status_code == 404
    record.refresh_from_db()
    assert record.base_salary == Decimal("1.00")


def test_history_error_shown_as_form_error(client: Client, hired: Employee, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise history.HistoryError("сорил")

    monkeypatch.setattr(history, "correct_job", boom)
    login_as(client, "HR")
    job = hired.job_records.get()
    data = {
        "position": job.position_id,
        "department": job.department_id,
        "employee_type": "part_time",
        "status": "active",
        "contract_type": "open_ended",
        "reason": "x",
    }
    response = client.post(f"/employees/{hired.pk}/job/{job.pk}/correct/", data)
    assert response.status_code == 200 and "сорил" in response.content.decode()
    job.refresh_from_db()
    assert job.employee_type == "full_time"


def test_accountant_sets_first_salary(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(new_employee("УБ00000002"), start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    login_as(client, "Accountant")
    url = f"/employees/{emp.pk}/salary/set/"
    assert "Цалин тогтоох" in client.get(f"/employees/{emp.pk}/").content.decode()
    assert client.get(url).status_code == 200
    response = client.post(url, {"effective": emp.first_hire_date.isoformat(), "amount": "1800000"})
    assert response.status_code == 204 and response.headers["HX-Refresh"] == "true"
    record = emp.salary_records.get()
    assert record.base_salary == Decimal("1800000.00") and record.change_type == "hire"
    assert "Цалин тогтоох" not in client.get(f"/employees/{emp.pk}/").content.decode()


def add_payload(job_values: dict[str, Any], **extra: str) -> dict[str, str]:
    data = {
        "family_name": "Доржийн", "given_name": "Болд", "register_no": "ук 88010122", "birth_date": "1988-01-01",
        "gender": "male", "work_phone": "99001122", "citizenship": "Монгол", "first_hire_date": "2026-02-01",
        "prior_service_years": "3", "prior_service_months": "0", "work_conditions": "normal",
        "start": "2026-02-01", "position": str(job_values["position"].pk),
        "department": str(job_values["department"].pk),
        "employee_type": "full_time", "status": "active", "contract_type": "open_ended",
        # Empty list formsets: management forms only, so the lists are valid when not filled in.
        "family-TOTAL_FORMS": "0", "family-INITIAL_FORMS": "0",
        "education-TOTAL_FORMS": "0", "education-INITIAL_FORMS": "0",
        "talents-TOTAL_FORMS": "0", "talents-INITIAL_FORMS": "0",
        "gifts-TOTAL_FORMS": "0", "gifts-INITIAL_FORMS": "0",
    }  # fmt: skip
    data.update(extra)
    return data


def test_hr_adds_employee_without_salary_field(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert "Үндсэн цалин" not in client.get("/employees/new/").content.decode()
    response = client.post("/employees/new/", add_payload(job_values, base_salary="9999999"))
    emp = Employee.objects.get(register_no="УК88010122")
    assert response.status_code == 302 and response.headers["Location"] == f"/employees/{emp.pk}/"
    assert not emp.salary_records.exists()  # salary ignored without permission


def test_admin_adds_with_salary_and_login(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    client.post("/employees/new/", add_payload(job_values, base_salary="1800000", create_login="on", username="bold"))
    emp = Employee.objects.get(register_no="УК88010122")
    assert emp.salary_records.get().base_salary == Decimal("1800000.00")
    assert emp.user is not None and emp.user.username == "bold"
    assert list(emp.user.groups.values_list("name", flat=True)) == ["Employee"]
    assert emp.user.must_change_password and emp.user.has_usable_password()


def test_hr_add_ignores_salary_insurance_fields(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post("/employees/new/", add_payload(job_values, **{"si-account_no": "123456"}))
    emp = Employee.objects.get(register_no="УК88010122")
    assert not SalaryInsurance.objects.filter(employee=emp, account_no="123456").exists()


def test_admin_adds_every_tab_in_one_post(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    response = client.post(
        "/employees/new/",
        add_payload(
            job_values,
            **{
                "si-bank": "Хаан банк",
                "si-account_no": "123456",
                "shoe_size": "42",
                "family-TOTAL_FORMS": "1",
                "family-0-name": "Доржийн Сараа",
                "family-0-relation": "Эхнэр",
            },
        ),
    )
    emp = Employee.objects.get(register_no="УК88010122")
    assert response.status_code == 302
    assert emp.salary_insurance.bank == "Хаан банк" and emp.salary_insurance.account_no == "123456"
    assert emp.shoe_size == "42"
    assert emp.family.get().name == "Доржийн Сараа"


def test_invalid_family_row_creates_nothing(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    response = client.post(
        "/employees/new/",
        add_payload(
            job_values,
            **{"family-TOTAL_FORMS": "1", "family-0-name": "", "family-0-relation": "Эхнэр"},
        ),
    )
    assert response.status_code == 200
    assert not Employee.objects.filter(register_no="УК88010122").exists()


def test_admin_hire_saves_photo_as_jpg(
    client: Client, job_values: dict[str, Any], settings: Any, tmp_path: Any
) -> None:
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    settings.MEDIA_ROOT = tmp_path
    login_as(client, "Admin")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    photo = SimpleUploadedFile("p.png", buffer.getvalue(), content_type="image/png")
    data: dict[str, Any] = add_payload(job_values)
    data["photo"] = photo
    response = client.post("/employees/new/", data)
    assert response.status_code == 302
    emp = Employee.objects.get(register_no="УК88010122")
    assert emp.photo and emp.photo.name.endswith(".jpg")


def test_invalid_add_creates_no_salary_login_or_user(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    response = client.post(
        "/employees/new/",
        add_payload(
            job_values,
            **{
                "si-bank": "Хаан банк",
                "si-account_no": "777777",
                "create_login": "on",
                "username": "newhire",
                "family-TOTAL_FORMS": "1",
                "family-0-name": "",
                "family-0-relation": "Эхнэр",
            },
        ),
    )
    assert response.status_code == 200
    assert not Employee.objects.filter(register_no="УК88010122").exists()
    assert not SalaryInsurance.objects.filter(account_no="777777").exists()
    assert not Employee.objects.filter(user__username="newhire").exists()
    assert not Employee.objects.exists()


def test_admin_hire_with_blank_salary_insurance_creates_no_row(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    client.post("/employees/new/", add_payload(job_values))
    emp = Employee.objects.get(register_no="УК88010122")
    assert not SalaryInsurance.objects.filter(employee=emp).exists()


def test_duplicate_register_rejected(client: Client, hired: Employee, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    body = client.post("/employees/new/", add_payload(job_values, register_no="уб99112233")).content.decode()
    assert "аль хэдийн" in body or "already exists" in body
    assert Employee.objects.count() == 1


def test_register_live_check(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get("/employees/check-register/?register_no=уб 99112233").content.decode()
    assert hired.full_name in body


def test_accountant_cannot_add(client: Client) -> None:
    login_as(client, "Accountant")
    assert client.get("/employees/new/").status_code == 403
    assert client.get("/employees/check-register/?register_no=x").status_code == 403


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_clearing_photo_stores_empty_not_false(hired: Employee, actor: User, settings: Any, tmp_path: Any) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    from employees.services import records

    settings.MEDIA_ROOT = tmp_path
    hired.photo.save("p.png", SimpleUploadedFile("p.png", PNG, content_type="image/png"))
    records.update_employee(hired, {"photo": False}, actor)
    hired.refresh_from_db()
    assert not hired.photo and hired.photo.name == ""
    entry = hired.activity.filter(kind="changed").latest("pk")
    assert all(c["new"] != "False" for c in entry.changes)


def test_register_search_only_for_personal_viewers(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert hired.code not in client.get("/employees/?view=table&q=УБ99112233").content.decode()
    assert hired.code in client.get("/employees/?view=table&q=Сараа").content.decode()
    login_as(client, "HR", "hr2")
    assert hired.code in client.get("/employees/?view=table&q=УБ99112233").content.decode()


def test_admin_add_page_shows_four_tabs_and_list_tables(client: Client) -> None:
    login_as(client, "Admin")
    body = client.get("/employees/new/").content.decode()
    for label in ("Үндсэн", "Хувийн", "Цалин, даатгал", "Нэвтрэх эрх"):
        assert label in body
    assert 'name="family-TOTAL_FORMS"' in body
    assert 'name="si-account_no"' in body
    assert 'data-tab="salary"' in body
    basic = body[body.index('data-tab="basic"') : body.index('data-tab="personal"')]
    assert 'name="first_hire_date"' in basic
    assert 'name="family_name"' in basic


def test_hr_add_page_has_no_salary_tab(client: Client) -> None:
    login_as(client, "HR")
    body = client.get("/employees/new/").content.decode()
    assert "Цалин, даатгал" not in body
    assert 'name="si-account_no"' not in body


def test_failed_add_post_marks_field_errors(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "Admin")
    response = client.post("/employees/new/", add_payload(job_values, family_name=""))
    assert response.status_code == 200
    body = response.content.decode()
    assert '<span class="field-error text-xs text-red-600">' in body  # rendered error markup, not the script
    assert not Employee.objects.filter(register_no="УК88010122").exists()


def test_other_fields_activity_split(hired: Employee, actor: User) -> None:
    from employees.models import ActivityEntry
    from employees.services import records

    records.update_employee(hired, {"blood_type": "II+", "shoe_size": "42", "work_schedule": "8-17"}, by=actor)
    personal = ActivityEntry.objects.get(employee=hired, personal=True, message="Хувийн мэдээлэл өөрчилсөн")
    work = ActivityEntry.objects.get(employee=hired, personal=False, message="Мэдээлэл өөрчилсөн")
    assert [c["field"] for c in personal.changes] == ["Цусны бүлэг", "Гутлын хэмжээ"]
    assert [c["field"] for c in work.changes] == ["Ажлын цагийн хуваарь"]


def test_hire_form_takes_other_fields(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    form = client.get("/employees/new/").context["person"]
    assert "blood_type" in form.fields and "shoe_size" in form.fields
    edit = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'name="blood_type"' in edit and 'name="shoe_size"' in edit


def _set_other_fields(hired: Employee) -> None:
    from employees.models import Gift, Talent

    hired.blood_type = "II+"
    hired.social_origin = "Ядуу"
    hired.housing_condition = "Хашаатай байшин"
    hired.shoe_size = "42"
    hired.elected_position = "Хорооны гишүүн"
    hired.save()
    Talent.objects.create(employee=hired, name="Хөгжим", trained_year=2010)
    Gift.objects.create(employee=hired, gift_type="Шинэ жил", given_date=date(2026, 1, 1))


def test_hr_sees_other_fields_talents_and_gifts(client: Client, hired: Employee) -> None:
    _set_other_fields(hired)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "II (A) Rh+" in body and "Ядуу" in body
    assert "Хөгжим" in body and "Шинэ жил" in body


def test_accountant_sees_no_other_fields(client: Client, hired: Employee) -> None:
    _set_other_fields(hired)
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Гутлын хэмжээ" not in body
    for text in ("<dd>42</dd>", "Хорооны гишүүн", "II (A) Rh+", "Ядуу", "Хашаатай байшин", "Хөгжим", "Шинэ жил"):
        assert text not in body


def test_own_page_shows_sensitive_other_fields(client: Client, hired: Employee) -> None:
    _set_other_fields(hired)
    hired.user = login_as(client, "Employee", "me")
    hired.save()
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "II (A) Rh+" in body and "Ядуу" in body and "Хашаатай байшин" in body
    assert "Хөгжим" in body and "Шинэ жил" in body


def test_hr_header_shows_latest_change(client: Client, hired: Employee, actor: User) -> None:
    from employees.services.records import update_employee

    update_employee(hired, {"shoe_size": "42"}, by=actor)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Сүүлд:" in body and "Гутлын хэмжээ: 42" in body


def test_accountant_header_latest_ignores_personal(client: Client, hired: Employee, actor: User) -> None:
    from employees.services.records import update_employee

    update_employee(hired, {"work_schedule": "8-17"}, by=actor)
    update_employee(hired, {"address": "Баянзүрх 5-р хороо"}, by=actor)
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Сүүлд: Ажлын цагийн хуваарь" in body
    assert "Баянзүрх 5-р хороо" not in body and "Хувийн мэдээлэл" not in body


@pytest.mark.parametrize("role", ["HR", "Accountant"])
def test_header_count_matches_visible_activity(client: Client, hired: Employee, actor: User, role: str) -> None:
    from employees import access
    from employees.services.records import update_employee

    update_employee(hired, {"shoe_size": "42"}, by=actor)
    update_employee(hired, {"address": "Баянзүрх 5-р хороо"}, by=actor)
    user = login_as(client, role)
    expected = access.visible_activity(user, hired).count()
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert f'Түүх (<span id="activity-count">{expected}</span>)' in body


def test_note_post_returns_activity_block(client: Client, hired: Employee, actor: User) -> None:
    from django.contrib.auth.models import Permission

    from employees import access
    from employees.services.records import update_employee

    update_employee(hired, {"shoe_size": "42"}, by=actor)
    update_employee(hired, {"address": "Баянзүрх 5-р хороо"}, by=actor)
    user = User.objects.create_user("mgr", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_employees", "manage_employees"]))
    client.force_login(user)
    body = client.post(f"/employees/{hired.pk}/note/", {"text": "шинэ тэмдэглэл"}).content.decode()
    assert "шинэ тэмдэглэл" in body and "Баянзүрх 5-р хороо" not in body
    latest = body[body.index('id="activity-latest"') :]
    assert "Сүүлд: шинэ тэмдэглэл" in latest
    expected = access.visible_activity(user, hired).count()
    assert f'<span id="activity-count" hx-swap-oob="true">{expected}</span>' in body


def _second_department_employee(hired: Employee, actor: User) -> Employee:
    fields = ("position", "employee_type", "contract_type")
    job = {
        **{f: getattr(hired.job_records.get(), f) for f in fields},
        "department": Department.objects.create(name="Борлуулалт"),
        "status": "active",
    }
    return history.hire(new_employee("УБ00000003"), start=date(2025, 1, 1), job=job, salary=None, by=actor)


def test_group_table_shows_department_headings_with_counts(client: Client, hired: Employee, actor: User) -> None:
    other = _second_department_employee(hired, actor)
    login_as(client, "HR")
    body = client.get("/employees/?view=table&group=1").content.decode()
    assert "Санхүү (1)</td>" in body and "Борлуулалт (1)</td>" in body
    assert body.index("Борлуулалт (1)") < body.index("Санхүү (1)")  # ordered by department name
    assert hired.code in body and other.code in body


def test_group_grid_shows_department_headings(client: Client, hired: Employee, actor: User) -> None:
    _second_department_employee(hired, actor)
    login_as(client, "HR")
    body = client.get("/employees/?view=grid&group=1").content.decode()
    assert "<h2" in body and "Санхүү (1)</h2>" in body and "Борлуулалт (1)</h2>" in body


def test_group_combines_with_department_filter(client: Client, hired: Employee, actor: User) -> None:
    _second_department_employee(hired, actor)
    login_as(client, "HR")
    body = client.get(
        f"/employees/?view=table&group=1&department={hired.job_records.get().department_id}"
    ).content.decode()
    assert "Санхүү (1)</td>" in body and "Борлуулалт (1)" not in body
    partial = client.get(
        f"/employees/?group=1&view=grid&department={hired.job_records.get().department_id}", HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "Санхүү (1)</h2>" in partial and "Борлуулалт (1)" not in partial and "<html" not in partial


def test_ungrouped_list_has_no_department_headings(client: Client, hired: Employee, actor: User) -> None:
    _second_department_employee(hired, actor)
    login_as(client, "HR")
    body = client.get("/employees/?view=table").content.decode()
    assert "Санхүү (1)" not in body and "Борлуулалт (1)" not in body


def test_list_page_keeps_group_checkbox_and_offers_clear_link(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get("/employees/?group=1").content.decode()
    assert 'name="group" value="1" checked' in body
    assert 'href="?clear=1"' in body


def test_other_fields_sit_on_personal_tab_for_hr(client: Client, hired: Employee) -> None:
    _set_other_fields(hired)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    personal = body.index('id="tab-personal"')
    label = '<dt class="text-slate-500">Гутлын хэмжээ</dt>'
    assert body.count(label) == 1 and body.index(label) > personal


def test_htmx_save_error_swaps_in_place(
    client: Client, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _other_employee(actor, job_values)
    login_as(client, "HR")
    data = save_payload(hired, register_no=other.register_no, work_schedule="typed value")
    response = client.post(f"/employees/{hired.pk}/save/", data, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and "typed value" in response.content.decode()
    hired.refresh_from_db()
    assert hired.work_schedule != "typed value"


def test_htmx_save_success_refreshes_in_place(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(
        f"/employees/{hired.pk}/save/", save_payload(hired, work_schedule="8-17"), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 204 and response.headers["HX-Refresh"] == "true"
    hired.refresh_from_db()
    assert hired.work_schedule == "8-17"


def test_save_form_posts_with_htmx(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    assert 'hx-post="/employees/' in page and 'hx-select="main"' in page


def test_hire_form_htmx_error_in_place_and_success_redirects(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    page = client.get("/employees/new/").content.decode()
    assert 'hx-post="/employees/new/"' in page
    bad = client.post("/employees/new/", add_payload(job_values, family_name=""), HTTP_HX_REQUEST="true")
    assert bad.status_code == 200 and 'id="add-form"' in bad.content.decode()
    good = client.post("/employees/new/", add_payload(job_values), HTTP_HX_REQUEST="true")
    assert good.status_code == 204 and good.headers["HX-Redirect"].startswith("/employees/")


def test_hire_open_ended_drops_end_date(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post("/employees/new/", add_payload(job_values, contract_end="2027-01-01"))
    job = Employee.objects.order_by("-pk").first().job_records.get()  # type: ignore[union-attr]
    assert job.contract_type == "open_ended" and job.contract_end is None


def test_hire_fixed_term_requires_end_date(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    before = Employee.objects.count()
    page = client.post("/employees/new/", add_payload(job_values, contract_type="fixed_term")).content.decode()
    assert "Хугацаатай гэрээнд дуусах огноог заавал" in page and Employee.objects.count() == before

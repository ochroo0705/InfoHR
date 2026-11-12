import io
from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from assistant import providers
from assistant.providers import ProviderError
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from employees.models import Employee, SalaryRecord, StaffImportDraft, StaffImportSettings
from employees.staff_import.fields import FIELDS
from employees.staff_import.views import UNFINISHED

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET = "Ажилтан"
KEYS = ("family_name", "given_name", "register_no", "start", "department", "position", "base_salary")
HEADINGS = ["Овог", "Нэр", "Регистр", "Ажилд орсон огноо", "Хэлтэс", "Албан тушаал", "Цалин"]
NO_SALARY_KEYS = KEYS[:-1]


def login_as(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def make_xlsx(rows: list[list[object]], headings: list[str] = HEADINGS) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET
    ws.append(headings)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def person(serial: int, **changes: Any) -> list[object]:
    cells: dict[str, Any] = {
        "family_name": "Бат",
        "given_name": f"Дорж{serial}",
        "register_no": f"УБ991122{serial:02d}",
        "start": date(2026, 3, 1),
        "department": "Санхүү",
        "position": "Нягтлан",
        "base_salary": 1500000,
        **changes,
    }
    return [cells[key] for key in KEYS]


def upload(client: Client, data: bytes, name: str = "staff.xlsx") -> Any:
    return client.post(reverse("employees:import"), {"file": SimpleUploadedFile(name, data, content_type=XLSX)})


def map_post(keys: tuple[str, ...] = KEYS, **extra: str) -> dict[str, str]:
    data = {f"col_{index}": key for index, key in enumerate(keys)}
    data["date_format"] = "iso"
    data.update(extra)
    return data


def headings_of(content: bytes) -> list[object]:
    sheet = load_workbook(io.BytesIO(content)).active
    assert sheet is not None
    return [cell.value for cell in sheet[1]]


def only_draft() -> StaffImportDraft:
    return StaffImportDraft.objects.get()


def employees_count() -> int:
    return Employee.objects.count()


def test_list_shows_import_button_only_to_managers(client: Client) -> None:
    login_as(client, "HR", "hr_one")
    report = reverse("reports:report", args=["staff-list"])
    assert "Ажилтан импортлох" in client.get(report).content.decode()
    client.logout()
    login_as(client, "Employee", "plain_one")
    assert client.get(report).status_code == 403  # the employee role has no staff report, so no import button


def test_upload_stores_draft_and_opens_map(client: Client) -> None:
    user = login_as(client, "HR", "hr_upload")
    response = upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_map", args=[draft.pk])
    assert draft.created_by == user
    assert draft.filename == "staff.xlsx"
    assert draft.sheet == SHEET
    assert draft.state == "uploaded"


def test_upload_of_junk_stays_on_page_with_message(client: Client) -> None:
    login_as(client, "HR", "hr_junk")
    response = upload(client, b"junk")
    assert response.status_code == 200
    assert "Файл .xlsx хэлбэрээр байх ёстой" in response.content.decode()
    assert not StaffImportDraft.objects.exists()


def test_upload_of_csv_renamed_to_xlsx_stays_on_page(client: Client) -> None:
    login_as(client, "HR", "hr_csv")
    response = upload(client, b"ovog,ner\nBat,Dorj\n")
    assert response.status_code == 200
    assert "Файл .xlsx хэлбэрээр байх ёстой" in response.content.decode()
    assert not StaffImportDraft.objects.exists()


def test_upload_of_wrong_extension_is_refused(client: Client) -> None:
    login_as(client, "HR", "hr_ext")
    response = upload(client, make_xlsx([person(10)]), name="staff.csv")
    assert response.status_code == 200
    assert "Зөвхөн .xlsx файл оруулна уу." in response.content.decode()
    assert not StaffImportDraft.objects.exists()


def test_upload_page_lists_last_ten_finished_imports(client: Client) -> None:
    user = login_as(client, "HR", "hr_recent")
    for number in range(11):
        StaffImportDraft.objects.create(
            created_by=user, filename=f"file{number}.xlsx", data=b"", state="imported", finished_at=timezone.now()
        )
    content = client.get(reverse("employees:import")).content.decode()
    assert content.count("Дэлгэрэнгүй") == 10


def test_upload_deletes_drafts_older_than_seven_days(client: Client) -> None:
    user = login_as(client, "HR", "hr_old")
    old = StaffImportDraft.objects.create(created_by=user, filename="old.xlsx", data=b"")
    StaffImportDraft.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
    upload(client, make_xlsx([person(10)]))
    assert not StaffImportDraft.objects.filter(pk=old.pk).exists()
    assert StaffImportDraft.objects.count() == 1


def test_every_page_needs_the_manage_right(client: Client) -> None:
    owner = User.objects.create_user("owner_hr", password="x-long-pass-123")  # noqa: S106
    owner.groups.add(Group.objects.get(name="HR"))
    draft = StaffImportDraft.objects.create(created_by=owner, filename="a.xlsx", data=make_xlsx([person(10)]))
    login_as(client, "Employee", "plain_403")
    assert client.get(reverse("employees:import")).status_code == 403
    assert client.get(reverse("employees:import_template")).status_code == 403
    assert client.get(reverse("employees:import_map", args=[draft.pk])).status_code == 403
    assert client.post(reverse("employees:import_map", args=[draft.pk]), map_post()).status_code == 403
    assert client.get(reverse("employees:import_preview", args=[draft.pk])).status_code == 403
    assert client.post(reverse("employees:import_run", args=[draft.pk])).status_code == 403
    assert client.get(reverse("employees:import_result", args=[draft.pk])).status_code == 403
    assert client.get(reverse("employees:import_rejected", args=[draft.pk])).status_code == 403


def test_another_user_gets_404_but_an_admin_may_open_the_draft(client: Client) -> None:
    login_as(client, "HR", "hr_owner")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    client.logout()
    login_as(client, "HR", "hr_other")
    for name in ("import_map", "import_preview", "import_result", "import_rejected"):
        assert client.get(reverse(f"employees:{name}", args=[draft.pk])).status_code == 404
    client.logout()
    login_as(client, "Admin", "admin_one")
    assert client.get(reverse("employees:import_map", args=[draft.pk])).status_code == 200


def test_map_without_required_fields_shows_missing_and_saves_nothing(client: Client) -> None:
    login_as(client, "HR", "hr_missing")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    response = client.post(reverse("employees:import_map", args=[draft.pk]), {"col_1": "given_name"})
    assert response.status_code == 200
    content = response.content.decode()
    assert "Эцэг/эхийн нэр" in content  # the required family name is named in the missing list
    assert "Анх ажилд орсон огноо" in content
    assert "Регистр эсвэл паспортын дугаар" in content
    draft.refresh_from_db()
    assert draft.mapping == {}


def test_map_refuses_one_field_on_two_columns(client: Client) -> None:
    login_as(client, "HR", "hr_twice")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    response = client.post(
        reverse("employees:import_map", args=[draft.pk]), map_post(("family_name", "family_name", "given_name"))
    )
    assert response.status_code == 200
    assert "хоёр баганад холбосон байна" in response.content.decode()
    draft.refresh_from_db()
    assert draft.mapping == {}


def test_map_save_remembers_choice_and_preview_creates_nothing(client: Client) -> None:
    login_as(client, "HR", "hr_save")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    response = client.post(reverse("employees:import_map", args=[draft.pk]), map_post(NO_SALARY_KEYS))
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_preview", args=[draft.pk])
    draft.refresh_from_db()
    assert draft.mapping["0"] == "family_name"
    assert "овог" in StaffImportSettings.get().mapping
    before = employees_count()
    page = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert "Шинэ" in page
    assert employees_count() == before
    assert only_draft().state == "uploaded"


def test_preview_refuses_a_draft_that_was_never_mapped(client: Client) -> None:
    login_as(client, "HR", "hr_nomap")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    response = client.get(reverse("employees:import_preview", args=[draft.pk]))
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_map", args=[draft.pk])


def make_mapped_draft(client: Client, rows: list[list[object]]) -> StaffImportDraft:
    login_as(client, "HR", "hr_mapped")
    upload(client, make_xlsx(rows))
    draft = only_draft()
    client.post(reverse("employees:import_map", args=[draft.pk]), map_post(NO_SALARY_KEYS))
    return draft


def test_run_with_wrong_count_imports_nobody(client: Client) -> None:
    draft = make_mapped_draft(client, [person(serial) for serial in range(10, 35)])
    response = client.post(reverse("employees:import_run", args=[draft.pk]), {"confirm_count": "24"})
    assert response.status_code == 302
    assert "err=count" in response["Location"]
    assert employees_count() == 0
    assert only_draft().state == "uploaded"


def test_run_with_right_count_imports_all_new_rows(client: Client) -> None:
    draft = make_mapped_draft(client, [person(serial) for serial in range(10, 35)])
    preview = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert 'name="confirm_count"' in preview
    response = client.post(reverse("employees:import_run", args=[draft.pk]), {"confirm_count": "25"})
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_result", args=[draft.pk])
    assert employees_count() == 25
    assert only_draft().state == "imported"


def test_run_twice_does_not_import_twice(client: Client) -> None:
    draft = make_mapped_draft(client, [person(10), person(11)])
    client.post(reverse("employees:import_run", args=[draft.pk]))
    assert employees_count() == 2
    response = client.post(reverse("employees:import_run", args=[draft.pk]))
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_result", args=[draft.pk])
    assert employees_count() == 2


def test_imported_draft_redirects_to_its_result(client: Client) -> None:
    draft = make_mapped_draft(client, [person(10)])
    client.post(reverse("employees:import_run", args=[draft.pk]))
    response = client.get(reverse("employees:import_preview", args=[draft.pk]))
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:import_result", args=[draft.pk])
    assert client.get(reverse("employees:import_result", args=[draft.pk])).status_code == 200


def test_running_draft_shows_the_unfinished_message(client: Client) -> None:
    login_as(client, "HR", "hr_running")
    draft = StaffImportDraft.objects.create(
        created_by=User.objects.get(username="hr_running"), filename="a.xlsx", data=b"", state="running"
    )
    response = client.get(reverse("employees:import_preview", args=[draft.pk]))
    assert response.status_code == 200
    assert UNFINISHED in response.content.decode()
    assert "Импорт дуусаагүй байна. Файлыг дахин оруулна уу." in response.content.decode()


def test_result_offers_rejected_rows_and_the_file_downloads(client: Client) -> None:
    draft = make_mapped_draft(client, [person(10), person(11), person(12, start="not a date")])
    client.post(reverse("employees:import_run", args=[draft.pk]))
    result = client.get(reverse("employees:import_result", args=[draft.pk])).content.decode()
    assert reverse("employees:import_rejected", args=[draft.pk]) in result
    response = client.get(reverse("employees:import_rejected", args=[draft.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    assert "attachment" in response["Content-Disposition"]
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    assert sheet.cell(row=1, column=sheet.max_column).value == "Алдаа"
    assert sheet.max_row == 2


def test_hr_without_salary_right_sees_the_notice_and_saves_no_salary(client: Client) -> None:
    login_as(client, "HR", "hr_nosalary")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert "таны эрхээр импортлогдохгүй" in page
    assert 'value="base_salary"' not in page
    # A salary column posted by hand is still skipped.
    client.post(reverse("employees:import_map", args=[draft.pk]), map_post(KEYS))
    preview = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert "таны эрхээр импортлогдохгүй" in preview
    client.post(reverse("employees:import_run", args=[draft.pk]))
    assert employees_count() == 1
    assert not SalaryRecord.objects.exists()


def test_template_download_follows_the_salary_right(client: Client) -> None:
    login_as(client, "HR", "hr_template")
    response = client.get(reverse("employees:import_template"))
    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    assert 'filename="ajiltan-zagvar.xlsx"' in response["Content-Disposition"]
    assert "Цалин" not in headings_of(response.content)
    client.logout()
    login_as(client, "Admin", "admin_template")
    admin = client.get(reverse("employees:import_template"))
    assert "Цалин" in headings_of(admin.content)


def test_admin_sees_the_salary_option_on_the_map_page(client: Client) -> None:
    login_as(client, "Admin", "admin_options")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert 'value="base_salary"' in page


def test_all_error_file_runs_to_a_rejected_download(client: Client) -> None:
    """A file whose rows are all refused still ends as imported: nobody is created, the rejected rows download."""
    draft = make_mapped_draft(client, [person(10, start="junk"), person(11, start="junk")])
    preview = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert "Алдаатай мөрүүдийг татаж авах" in preview
    response = client.post(reverse("employees:import_run", args=[draft.pk]))
    assert response["Location"] == reverse("employees:import_result", args=[draft.pk])
    assert employees_count() == 0
    draft.refresh_from_db()
    assert draft.state == "imported"
    assert draft.created_count == 0
    assert draft.rejected_count == 2
    result = client.get(reverse("employees:import_result", args=[draft.pk])).content.decode()
    assert "Нэмэгдсэн" in result
    download = client.get(reverse("employees:import_rejected", args=[draft.pk]))
    assert download.status_code == 200
    assert download["Content-Type"] == XLSX


def test_a_failure_inside_the_run_is_not_reported_as_already_imported(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = make_mapped_draft(client, [person(10)])

    def broken(*args: Any, **kwargs: Any) -> None:
        raise ValueError("inside the run")

    monkeypatch.setattr("employees.staff_import.run.build_preview", broken)
    with pytest.raises(ValueError, match="inside the run"):
        client.post(reverse("employees:import_run", args=[draft.pk]))
    draft.refresh_from_db()
    assert draft.state == "uploaded"  # the claim is given back, so the user can try again
    assert employees_count() == 0


def test_oversize_upload_is_refused_with_no_draft(client: Client) -> None:
    login_as(client, "HR", "hr_big")
    too_big = b"0" * (5 * 1024 * 1024 + 1)
    response = upload(client, too_big)
    assert response.status_code == 200
    assert "Файл хэт том байна" in response.content.decode()
    assert not StaffImportDraft.objects.exists()


@pytest.mark.parametrize("typed", ["abc", "0", ""])
def test_bad_confirm_count_imports_nobody(client: Client, typed: str) -> None:
    draft = make_mapped_draft(client, [person(serial) for serial in range(10, 35)])
    response = client.post(reverse("employees:import_run", args=[draft.pk]), {"confirm_count": typed})
    assert "err=count" in response["Location"]
    assert employees_count() == 0
    assert only_draft().state == "uploaded"


def test_cell_and_file_name_are_escaped_on_every_page(client: Client) -> None:
    login_as(client, "HR", "hr_escape")
    upload(client, make_xlsx([person(10, given_name="<script>cell()</script>")]))
    draft = only_draft()
    # Django strips angle brackets from upload names, so the stored name is set directly to test the template.
    evil_name = "<script>evil()</script>.xlsx"
    StaffImportDraft.objects.filter(pk=draft.pk).update(filename=evil_name)
    client.post(reverse("employees:import_map", args=[draft.pk]), map_post(NO_SALARY_KEYS))
    preview = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert "<script>cell()" not in preview
    assert "&lt;script&gt;cell()" in preview
    client.post(reverse("employees:import_run", args=[draft.pk]))
    result = client.get(reverse("employees:import_result", args=[draft.pk])).content.decode()
    assert "<script>evil()" not in result
    assert "&lt;script&gt;evil()" in result


def test_map_selects_have_accessible_labels(client: Client) -> None:
    login_as(client, "HR", "hr_labels")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert 'aria-label="Багана: Овог"' in page


IN_PROGRESS = "Импорт явагдаж байна. Хэдэн секундын дараа хуудсаа шинэчилнэ үү."


def test_a_recent_running_draft_shows_the_in_progress_message(client: Client) -> None:
    login_as(client, "HR", "hr_inprog")
    owner = User.objects.get(username="hr_inprog")
    draft = StaffImportDraft.objects.create(
        created_by=owner, filename="a.xlsx", data=b"", state="running", started_at=timezone.now()
    )
    page = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert IN_PROGRESS in page
    assert UNFINISHED not in page
    assert "Файлыг дахин оруулна уу" not in page


def test_an_old_running_draft_shows_the_re_upload_message(client: Client) -> None:
    login_as(client, "HR", "hr_stuck")
    owner = User.objects.get(username="hr_stuck")
    draft = StaffImportDraft.objects.create(
        created_by=owner,
        filename="a.xlsx",
        data=b"",
        state="running",
        started_at=timezone.now() - timedelta(minutes=31),
    )
    page = client.get(reverse("employees:import_preview", args=[draft.pk])).content.decode()
    assert UNFINISHED in page
    assert IN_PROGRESS not in page


def test_upload_takes_the_first_sheet_that_has_staff_rows(client: Client) -> None:
    login_as(client, "HR", "hr_sheets")
    wb = Workbook()
    first = wb.active
    assert first is not None
    first.title = "Хоосон"
    second = wb.create_sheet("Ажилтан")
    second.append(HEADINGS)
    second.append(person(10))
    buffer = io.BytesIO()
    wb.save(buffer)
    response = upload(client, buffer.getvalue())
    assert response.status_code == 302
    assert only_draft().sheet == "Ажилтан"


def test_a_workbook_with_no_staff_rows_on_any_sheet_is_refused(client: Client) -> None:
    login_as(client, "HR", "hr_nosheet")
    wb = Workbook()
    first = wb.active
    assert first is not None
    first.title = "Хоосон"
    buffer = io.BytesIO()
    wb.save(buffer)
    response = upload(client, buffer.getvalue())
    assert response.status_code == 200
    assert "Файлд ажилтны мөр олдсонгүй." in response.content.decode()
    assert not StaffImportDraft.objects.exists()


def test_the_upload_page_cleans_up_old_drafts_but_keeps_the_import_record(client: Client) -> None:
    user = login_as(client, "HR", "hr_purge")
    long_ago = timezone.now() - timedelta(days=8)
    old_uploaded = StaffImportDraft.objects.create(created_by=user, filename="old.xlsx", data=b"x")
    old_imported = StaffImportDraft.objects.create(
        created_by=user, filename="done.xlsx", data=b"", state="imported", rejected_file=b"rows", rejected_count=1
    )
    fresh = StaffImportDraft.objects.create(created_by=user, filename="new.xlsx", data=b"x")
    StaffImportDraft.objects.filter(pk__in=[old_uploaded.pk, old_imported.pk]).update(created_at=long_ago)
    assert client.get(reverse("employees:import")).status_code == 200  # a GET, not an upload
    assert not StaffImportDraft.objects.filter(pk=old_uploaded.pk).exists()
    kept = StaffImportDraft.objects.get(pk=old_imported.pk)
    assert kept.state == "imported"
    assert kept.rejected_file is None
    assert StaffImportDraft.objects.filter(pk=fresh.pk).exists()


UNKNOWN = "Төрсөн өдөр"  # not an alias, so the plain matcher leaves this column for the AI
UNKNOWN_HEADINGS = [*HEADINGS[:-1], UNKNOWN]
SALARY_KEY = next(field.key for field in FIELDS if field.needs_salary)


class FakeAssistant:
    """Stands in for the configured provider: counts its calls and gives back a fixed reply, or raises."""

    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    def complete_json(self, system: str, user: str) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply


# Patches assistant.providers.get_provider to return None, so no test reaches a real provider.
@pytest.fixture(autouse=True)
def assistant_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The assistant is off unless a test turns it on, so no test calls a real provider."""
    monkeypatch.setattr(providers, "get_provider", lambda: None)


def unknown_upload(client: Client, headings: list[str] = UNKNOWN_HEADINGS) -> StaffImportDraft:
    upload(client, make_xlsx([person(10)[:6] + [date(1990, 5, 1)]], headings=headings))
    return only_draft()


def test_map_prefills_ai_suggestion_with_badge(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_badge")
    draft = unknown_upload(client)
    fake = FakeAssistant(reply={"matches": [{"column": 6, "field": "birth_date"}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert '<option value="birth_date" selected>' in page
    assert page.count(">AI<") == 1
    assert fake.calls == 1


def test_map_without_ai_looks_as_before(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_off")
    draft = unknown_upload(client)
    monkeypatch.setattr(providers, "get_provider", lambda: None)
    response = client.get(reverse("employees:import_map", args=[draft.pk]))
    assert response.status_code == 200
    page = response.content.decode()
    assert ">AI<" not in page
    assert '<option value="birth_date" selected>' not in page


def test_map_survives_provider_error(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_error")
    draft = unknown_upload(client)
    fake = FakeAssistant(error=ProviderError("provider down"))
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    response = client.get(reverse("employees:import_map", args=[draft.pk]))
    assert response.status_code == 200
    assert ">AI<" not in response.content.decode()
    assert fake.calls == 1


def test_ai_is_not_asked_again_after_mapping_saved(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_once")
    draft = unknown_upload(client)
    fake = FakeAssistant(reply={"matches": []})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    client.get(reverse("employees:import_map", args=[draft.pk]))
    assert fake.calls == 1
    saved = client.post(reverse("employees:import_map", args=[draft.pk]), map_post(NO_SALARY_KEYS))
    assert saved.status_code == 302
    client.get(reverse("employees:import_map", args=[draft.pk]))
    assert fake.calls == 1


def test_reread_asks_ai_again(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_reread")
    draft = unknown_upload(client)
    fake = FakeAssistant(reply={"matches": []})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    client.get(reverse("employees:import_map", args=[draft.pk]))
    assert fake.calls == 1
    response = client.post(
        reverse("employees:import_map", args=[draft.pk]),
        {"action": "reread", "sheet": SHEET, "header_rows": "1"},
        follow=True,
    )
    assert response.status_code == 200
    assert fake.calls == 2


def test_hr_without_salary_right_gets_no_salary_suggestion(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_nosalary")
    draft = unknown_upload(client, headings=[*HEADINGS[:-1], "Бусад тайлбар"])
    fake = FakeAssistant(reply={"matches": [{"column": 6, "field": SALARY_KEY}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert fake.calls == 1
    assert f'value="{SALARY_KEY}"' not in page
    assert ">AI<" not in page


def test_known_columns_get_no_badge(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "Admin", "admin_ai_known")
    upload(client, make_xlsx([person(10)]))
    draft = only_draft()
    fake = FakeAssistant(reply={"matches": [{"column": 0, "field": "birth_date"}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert fake.calls == 0
    assert ">AI<" not in page


def test_ai_chip_survives_a_validation_error(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_error_post")
    draft = unknown_upload(client)
    fake = FakeAssistant(reply={"matches": [{"column": 6, "field": "birth_date"}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    url = reverse("employees:import_map", args=[draft.pk])
    assert 'name="ai_cols" value="6:birth_date"' in client.get(url).content.decode()
    failed = client.post(url, {"col_6": "birth_date", "ai_cols": "6:birth_date", "date_format": "iso"})
    assert failed.status_code == 200
    page = failed.content.decode()
    assert "Дараах заавал талбарт" in page  # the required fields are missing, so the save is refused
    assert '<option value="birth_date" selected>' in page
    assert page.count(">AI<") == 1
    draft.refresh_from_db()
    assert draft.mapping == {}
    assert fake.calls == 1


def test_ai_cols_junk_and_out_of_range_show_no_badge(client: Client) -> None:
    login_as(client, "HR", "hr_ai_junk")
    draft = unknown_upload(client)
    url = reverse("employees:import_map", args=[draft.pk])
    response = client.post(url, {"col_6": "birth_date", "ai_cols": "abc,,99:x,0", "date_format": "iso"})
    assert response.status_code == 200
    page = response.content.decode()
    assert ">AI<" not in page  # no pair survives: no colon, a bad index, or an unknown key
    assert '<option value="birth_date" selected>' in page


def test_ai_chip_goes_when_the_user_changes_the_column(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_changed")
    draft = unknown_upload(client)
    fake = FakeAssistant(reply={"matches": [{"column": 6, "field": "birth_date"}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    url = reverse("employees:import_map", args=[draft.pk])
    client.get(url)
    failed = client.post(url, {"col_6": "department", "ai_cols": "6:birth_date", "date_format": "iso"})
    assert failed.status_code == 200
    page = failed.content.decode()
    assert "Дараах заавал талбарт" in page
    assert '<option value="department" selected>' in page
    assert ">AI<" not in page  # the user chose another field, so the AI guess no longer applies
    assert fake.calls == 1


def test_tampered_ai_pair_adds_a_chip_only_where_the_value_matches(client: Client) -> None:
    # Accepted as harmless: a forged pair can add a chip, but only on a column whose posted value equals the pair's
    # key. Here column 0 really holds given_name, so the chip shows; nothing is saved by the error re-render.
    login_as(client, "HR", "hr_ai_tamper")
    draft = unknown_upload(client)
    url = reverse("employees:import_map", args=[draft.pk])
    posted = {"col_0": "given_name", "col_6": "birth_date", "ai_cols": "0:given_name", "date_format": "iso"}
    failed = client.post(url, posted)
    assert failed.status_code == 200
    assert failed.content.decode().count(">AI<") == 1
    draft.refresh_from_db()
    assert draft.mapping == {}


def test_hr_salary_heading_gets_no_salary_suggestion(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    login_as(client, "HR", "hr_ai_salary_heading")
    draft = unknown_upload(client, headings=HEADINGS)
    fake = FakeAssistant(reply={"matches": [{"column": 6, "field": SALARY_KEY}]})
    monkeypatch.setattr(providers, "get_provider", lambda: fake)
    page = client.get(reverse("employees:import_map", args=[draft.pk])).content.decode()
    assert fake.calls == 1
    assert f'value="{SALARY_KEY}"' not in page
    assert ">AI<" not in page


def test_hr_tampered_salary_pair_shows_no_chip_and_selects_nothing(client: Client) -> None:
    login_as(client, "HR", "hr_ai_tamper_salary")
    draft = unknown_upload(client)
    url = reverse("employees:import_map", args=[draft.pk])
    # The required fields are left blank, so the page re-renders with the validation error.
    failed = client.post(url, {"col_6": SALARY_KEY, "ai_cols": f"6:{SALARY_KEY}", "date_format": "iso"})
    assert failed.status_code == 200
    page = failed.content.decode()
    assert ">AI<" not in page
    assert f'value="{SALARY_KEY}" selected' not in page
    draft.refresh_from_db()
    assert draft.mapping == {}

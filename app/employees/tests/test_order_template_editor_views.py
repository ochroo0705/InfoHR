"""The in-page order template editor: its page, save and reset (views in order_template_editor_views.py)."""

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from docx import Document

from employees.models import Employee, HrOrder, OrderTemplate, OrderType
from employees.services import order_docs

pytestmark = pytest.mark.django_db

FIRED = OrderType.FIRED
HIRED = OrderType.HIRED
PENSION = OrderType.PENSION
STALE_MESSAGE = "Өөр хүн өөрчилсөн байна. Хуудсаа дахин нээнэ үү."


@pytest.fixture(autouse=True)
def private_files(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_superuser("editor_admin", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def admin_client(admin_user: User) -> Client:
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def view_client(db: None) -> Client:
    user = User.objects.create_user("editor_viewer", password="x-long-pass-123", is_staff=True)  # noqa: S106
    user.user_permissions.add(
        Permission.objects.get(codename="view_ordertemplate", content_type__app_label="employees")
    )
    client = Client()
    client.force_login(user)
    return client


def row_of(order_type: OrderType) -> OrderTemplate:
    OrderTemplate.ensure_all()
    return OrderTemplate.objects.get(order_type=order_type.value)


def edit_url(order_type: OrderType) -> str:
    return reverse("admin:employees_ordertemplate_edit", args=[row_of(order_type).pk])


def save_url(order_type: OrderType) -> str:
    return reverse("admin:employees_ordertemplate_save", args=[row_of(order_type).pk])


def reset_url(order_type: OrderType) -> str:
    return reverse("admin:employees_ordertemplate_reset", args=[row_of(order_type).pk])


def current_updated_at(order_type: OrderType) -> str:
    return row_of(order_type).updated_at.isoformat()


def para(*parts: dict[str, str], align: str = "left", bold: bool = False) -> dict[str, Any]:
    return {"align": align, "bold": bold, "italic": False, "size": None, "parts": list(parts)}


def text_para(text: str) -> dict[str, Any]:
    return para({"text": text})


def body_of(paragraphs: list[dict[str, Any]], updated_at: str, show_letterhead: bool = True) -> dict[str, Any]:
    return {"updated_at": updated_at, "doc": {"paragraphs": paragraphs}, "show_letterhead": show_letterhead}


def save(client: Client, order_type: OrderType, payload: dict[str, Any]) -> Any:
    return client.post(save_url(order_type), json.dumps(payload), content_type="application/json")


def docx_with(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def docx_with_table() -> bytes:
    document = Document()
    document.add_paragraph("Хүснэгттэй загвар")
    document.add_table(rows=1, cols=1)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def text_of(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def stored_bytes(order_type: OrderType) -> bytes:
    with row_of(order_type).file.open("rb") as handle:
        data: bytes = handle.read()
    return data


def upload(order_type: OrderType, data: bytes) -> None:
    row_of(order_type).file.save("mine.docx", ContentFile(data))


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def test_page_shows_starter_doc_when_no_file(admin_client: Client) -> None:
    response = admin_client.get(edit_url(FIRED))

    assert response.status_code == 200
    assert response.context["doc"] is not None
    assert response.context["can_change"] is True
    assert response.context["show_letterhead"] is True


def test_page_is_read_only_for_a_file_with_a_table(admin_client: Client) -> None:
    upload(FIRED, docx_with_table())

    response = admin_client.get(edit_url(FIRED))

    assert response.status_code == 200
    assert response.context["doc"] is None
    assert "боломжгүй" in response.content.decode()


def test_hired_starter_opens_editable_with_conditional_and_numbered_lines(admin_client: Client) -> None:
    response = admin_client.get(edit_url(HIRED))

    doc = response.context["doc"]
    assert doc is not None
    assert response.context["can_change"] is True
    assert [p["show_if"] for p in doc["paragraphs"] if p["show_if"]] == ["probation_end", "salary"]
    assert sum(1 for p in doc["paragraphs"] if p["numbered"]) == 5


def test_page_is_read_only_for_view_only_user(view_client: Client) -> None:
    response = view_client.get(edit_url(FIRED))

    assert response.status_code == 200
    assert response.context["can_change"] is False

    payload = body_of([text_para("Үзэх эрхтэй хэрэглэгч")], current_updated_at(FIRED))
    assert save(view_client, FIRED, payload).status_code == 403
    assert view_client.post(reset_url(FIRED)).status_code == 403
    assert not row_of(FIRED).file


def test_save_stores_a_docx_that_renders(admin_client: Client, hired: Employee, actor: User) -> None:
    payload = body_of(
        [para({"text": "Туршилтын хэвлэлт "}, {"field": "employee_full_name"})],
        current_updated_at(FIRED),
    )

    response = save(admin_client, FIRED, payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    # The hire order is rendered with the FIRED template: an in-memory copy, nothing is saved.
    order = hire_order(hired)
    order.order_type = FIRED.value
    assert "Туршилтын хэвлэлт" in text_of(order_docs.render_order(order, actor))


def test_save_refuses_unknown_field_in_mongolian(admin_client: Client) -> None:
    payload = body_of([para({"field": "nope"})], current_updated_at(FIRED))

    response = save(admin_client, FIRED, payload)

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert any("Танигдаагүй талбар: nope" in message for message in body["errors"])
    assert not row_of(FIRED).file


def test_save_refused_for_a_file_with_a_table_and_bytes_unchanged(admin_client: Client) -> None:
    upload(FIRED, docx_with_table())
    before = stored_bytes(FIRED)

    response = save(admin_client, FIRED, body_of([text_para("Засах оролдлого")], current_updated_at(FIRED)))

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert stored_bytes(FIRED) == before


def test_hired_starter_edit_keeps_its_conditions_when_saved(admin_client: Client) -> None:
    doc = admin_client.get(edit_url(HIRED)).context["doc"]
    doc["paragraphs"][0]["parts"] = [{"text": "Өөрчилсөн толгой"}]

    response = save(admin_client, HIRED, {"updated_at": current_updated_at(HIRED), "doc": doc, "show_letterhead": True})

    assert response.status_code == 200
    saved = admin_client.get(edit_url(HIRED)).context["doc"]
    assert saved["paragraphs"][0]["parts"] == [{"text": "Өөрчилсөн толгой"}]
    assert [p["show_if"] for p in saved["paragraphs"] if p["show_if"]] == ["probation_end", "salary"]


def test_reset_works_on_a_file_the_editor_cannot_show(admin_client: Client) -> None:
    upload(FIRED, docx_with_table())

    response = admin_client.post(reset_url(FIRED))

    assert response.status_code == 200
    assert not row_of(FIRED).file
    assert admin_client.get(edit_url(FIRED)).context["doc"] is not None


@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        b"[1, 2]",
        ("[" * 100000 + "]" * 100000).encode(),
    ],
    ids=["invalid-json", "non-dict", "deeply-nested"],
)
def test_unreadable_body_is_400_not_500(admin_client: Client, raw: bytes) -> None:
    response = admin_client.post(save_url(FIRED), raw, content_type="application/json")

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_missing_updated_at_is_400(admin_client: Client) -> None:
    payload = body_of([text_para("Текст")], current_updated_at(FIRED))
    del payload["updated_at"]

    response = save(admin_client, FIRED, payload)

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_non_bool_show_letterhead_is_400(admin_client: Client) -> None:
    payload = body_of([text_para("Текст")], current_updated_at(FIRED))
    payload["show_letterhead"] = "yes"

    response = save(admin_client, FIRED, payload)

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert not row_of(FIRED).file


def test_data_can_change_is_true_only_for_an_editable_page_with_change_right(
    admin_client: Client, view_client: Client
) -> None:
    assert 'data-can-change="true"' in admin_client.get(edit_url(FIRED)).content.decode()
    assert 'data-can-change="false"' in view_client.get(edit_url(FIRED)).content.decode()

    upload(FIRED, docx_with_table())
    assert 'data-can-change="false"' in admin_client.get(edit_url(FIRED)).content.decode()


def test_stale_save_is_refused(admin_client: Client) -> None:
    stale = current_updated_at(FIRED)
    assert save(admin_client, FIRED, body_of([text_para("Эхний хувилбар")], stale)).status_code == 200
    before = stored_bytes(FIRED)

    response = save(admin_client, FIRED, body_of([text_para("Хоцорсон хувилбар")], stale))

    assert response.status_code == 409
    assert response.json() == {"ok": False, "errors": [STALE_MESSAGE]}
    assert stored_bytes(FIRED) == before


def test_save_updates_show_letterhead_and_updated_by(admin_client: Client, admin_user: User) -> None:
    response = save(
        admin_client,
        FIRED,
        body_of([text_para("Бланкгүй")], current_updated_at(FIRED), show_letterhead=False),
    )

    assert response.status_code == 200
    row = row_of(FIRED)
    assert row.show_letterhead is False
    assert row.updated_by == admin_user
    assert response.json()["updated_at"] == row.updated_at.isoformat()


def test_reset_puts_the_starter_back(admin_client: Client) -> None:
    save(admin_client, FIRED, body_of([text_para("Өөр загвар")], current_updated_at(FIRED), show_letterhead=False))

    response = admin_client.post(reset_url(FIRED))

    assert response.status_code == 200
    assert response.json()["ok"] is True
    row = row_of(FIRED)
    assert not row.file
    assert row.show_letterhead is True
    assert admin_client.get(edit_url(FIRED)).context["doc"] is not None


def test_save_writes_the_same_audit_event_as_admin_save(admin_client: Client) -> None:
    admin_client.post(
        reverse("admin:employees_ordertemplate_change", args=[row_of(PENSION).pk]),
        {
            "file": SimpleUploadedFile("mine.docx", docx_with("{{ company_name }}"), content_type=order_docs.DOCX_TYPE),
            "show_letterhead": "on",
        },
    )
    admin_entry = SystemLogEntry.objects.filter(action="setting_changed").order_by("id").last()

    save(admin_client, FIRED, body_of([text_para("Аудит")], current_updated_at(FIRED)))

    editor_entry = SystemLogEntry.objects.filter(action="setting_changed").order_by("id").last()
    assert admin_entry is not None and editor_entry is not None and editor_entry.pk != admin_entry.pk
    assert editor_entry.category == admin_entry.category
    assert editor_entry.changes == admin_entry.changes
    assert editor_entry.changes == [{"field": "Загварын файл (.docx)", "old": "", "new": "(файл)"}]


def test_field_for_another_type_opens_flagged_and_saves(admin_client: Client) -> None:
    page = admin_client.get(edit_url(FIRED))
    flags = {item["name"]: item["for_this_type"] for group in page.context["fields"] for item in group["items"]}
    assert flags["salary"] is False
    assert flags["company_name"] is True

    payload = body_of([para({"text": "Цалин "}, {"field": "salary"})], current_updated_at(FIRED))
    assert save(admin_client, FIRED, payload).status_code == 200


def test_changelist_links_to_the_editor(admin_client: Client) -> None:
    OrderTemplate.ensure_all()

    body = admin_client.get(reverse("admin:employees_ordertemplate_changelist")).content.decode()

    assert "Засах" in body
    assert reverse("admin:employees_ordertemplate_edit", args=[row_of(FIRED).pk]) in body


# --- Preview: the real renderer on the unsaved editor document; nothing is saved ---


def preview_url(order_type: OrderType) -> str:
    return reverse("admin:employees_ordertemplate_preview", args=[row_of(order_type).pk])


def preview(client: Client, order_type: OrderType, payload: dict[str, Any]) -> Any:
    return client.post(preview_url(order_type), json.dumps(payload), content_type="application/json")


def preview_body(paragraphs: list[dict[str, Any]], employee_id: int | None = None, show_letterhead: bool = True) -> Any:
    return {"doc": {"paragraphs": paragraphs}, "employee_id": employee_id, "show_letterhead": show_letterhead}


def field_para(name: str) -> dict[str, Any]:
    return para({"field": name})


def reader_client(db: None, *, salary: bool) -> Client:
    """A user who may open the editor (view), see every employee, and may or may not see salary."""
    user = User.objects.create_user("preview_reader", password="x-long-pass-123", is_staff=True)  # noqa: S106
    user.user_permissions.add(
        Permission.objects.get(codename="view_ordertemplate", content_type__app_label="employees"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    if salary:
        user.user_permissions.add(Permission.objects.get(codename="view_salary", content_type__app_label="macs"))
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def reader(db: None) -> Client:
    return reader_client(db, salary=False)


@pytest.fixture
def rendered(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Every filled .docx the renderer produced, in order. The PDF text cannot be read here (pypdf is not installed),
    so the tests check the filled Word text that the PDF is drawn from."""
    seen: list[bytes] = []
    real_render = order_docs._render  # noqa: SLF001

    def spy(source: Any, context: dict[str, Any]) -> bytes:
        out = real_render(source, context)
        seen.append(out)
        return out

    monkeypatch.setattr(order_docs, "_render", spy)
    return seen


def test_preview_returns_pdf_with_employee_name(admin_client: Client, hired: Employee, rendered: list[bytes]) -> None:
    payload = preview_body([field_para("employee_full_name")], employee_id=hired.pk)

    response = preview(admin_client, HIRED, payload)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert hired.full_name in text_of(rendered[-1])


def test_preview_creates_nothing(admin_client: Client, hired: Employee) -> None:
    from employees.models import CompanySettings, Event

    row_of(FIRED)  # the template rows are created on first use (ensure_all): that is setup, not the preview
    CompanySettings.get()  # the one-off company row the renderer creates on first use: setup, as on a first print
    before = (
        HrOrder.objects.count(),
        Event.objects.count(),
        SystemLogEntry.objects.count(),
        row_of(FIRED).updated_at,
    )
    numbered = list(HrOrder.objects.filter(number__gt="").values_list("pk", flat=True))
    payload = preview_body([field_para("order_number"), text_para("x")], employee_id=hired.pk)

    assert preview(admin_client, FIRED, payload).status_code == 200

    after = (
        HrOrder.objects.count(),
        Event.objects.count(),
        SystemLogEntry.objects.count(),
        row_of(FIRED).updated_at,
    )
    assert after == before
    assert list(HrOrder.objects.filter(number__gt="").values_list("pk", flat=True)) == numbered  # only the setup's order
    assert not row_of(FIRED).file


def test_preview_hides_salary_without_permission(reader: Client, hired: Employee, rendered: list[bytes]) -> None:
    payload = preview_body([field_para("salary")], employee_id=hired.pk)

    response = preview(reader, HIRED, payload)

    assert response.status_code == 200
    assert "₮" not in text_of(rendered[-1])


def test_preview_shows_salary_with_permission(admin_client: Client, hired: Employee, rendered: list[bytes]) -> None:
    payload = preview_body([field_para("salary")], employee_id=hired.pk)

    assert preview(admin_client, HIRED, payload).status_code == 200

    assert "₮" in text_of(rendered[-1])


def test_preview_empty_employee_data_shows_blank_line_not_error(
    admin_client: Client, hired: Employee, rendered: list[bytes]
) -> None:
    payload = preview_body([field_para("termination_reason"), field_para("probation_end")], employee_id=hired.pk)

    response = preview(admin_client, HIRED, payload)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert "{{" not in text_of(rendered[-1])


def test_preview_refuses_an_employee_the_user_cannot_see(view_client: Client, hired: Employee) -> None:
    # view_client may open the editor but sees no employee (no macs.view_employees, not linked to a login): 404,
    # the same answer the order pages give for an employee outside the user's scope.
    response = preview(view_client, HIRED, preview_body([text_para("x")], employee_id=hired.pk))

    assert response.status_code == 404


def test_preview_unknown_employee_is_404(admin_client: Client) -> None:
    response = preview(admin_client, HIRED, preview_body([text_para("x")], employee_id=999_999))

    assert response.status_code == 404


def test_preview_without_employee_uses_first_visible_one(admin_client: Client, hired: Employee) -> None:
    response = preview(admin_client, HIRED, preview_body([text_para("x")], employee_id=None))

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_preview_allowed_with_view_permission_only(reader: Client, hired: Employee) -> None:
    response = preview(reader, HIRED, preview_body([text_para("x")], employee_id=hired.pk))

    assert response.status_code == 200


def test_preview_uses_unsaved_content_not_the_stored_file(
    admin_client: Client, hired: Employee, rendered: list[bytes]
) -> None:
    upload(FIRED, docx_with("Хадгалагдсан текст"))

    response = preview(admin_client, FIRED, preview_body([text_para("Шинэ текст")], employee_id=hired.pk))

    assert response.status_code == 200
    filled = text_of(rendered[-1])
    assert "Шинэ текст" in filled
    assert "Хадгалагдсан текст" not in filled


def test_preview_letterhead_follows_the_request_not_the_stored_flag(
    admin_client: Client, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    from employees.models import CompanySettings

    company = CompanySettings.get()
    company.letterhead_lines = "MACS ХХК"
    company.save()
    upload(FIRED, docx_with("Загвар"))
    row = row_of(FIRED)
    row.show_letterhead = False
    row.save()
    drawn: list[bool] = []
    real_draw = order_docs._draw_letterhead  # noqa: SLF001

    def spy(pdf: Any, company: Any, logo: Any) -> None:
        drawn.append(True)
        real_draw(pdf, company, logo)

    monkeypatch.setattr(order_docs, "_draw_letterhead", spy)

    on = preview_body([text_para("x")], employee_id=hired.pk, show_letterhead=True)
    assert preview(admin_client, FIRED, on).status_code == 200
    assert drawn

    drawn.clear()
    off = preview_body([text_para("x")], employee_id=hired.pk, show_letterhead=False)
    assert preview(admin_client, FIRED, off).status_code == 200
    assert not drawn


# --- Editor page UI (task 8): mount point, read-only banner, starter link, letterhead block, admin column ---


def test_page_contains_mount_point_and_urls(admin_client: Client) -> None:
    row = row_of(FIRED)
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert f'data-save-url="{save_url(FIRED)}"' in body
    assert f'data-preview-url="{reverse("admin:employees_ordertemplate_preview", args=[row.pk])}"' in body
    assert f'data-reset-url="{reset_url(FIRED)}"' in body
    download = reverse("admin:employees_ordertemplate_download", args=[row.pk])
    assert f'data-download-url="{download}?which=current"' in body
    assert 'data-csrf="' in body
    assert "Word болгон татах" in body


def test_read_only_banner_text_for_unsupported_file(admin_client: Client) -> None:
    upload(FIRED, docx_with_table())

    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert "Энэ загварыг хуудсан дээр засах боломжгүй" in body
    assert "хүснэгт, нөхцөлт блок, зураг" in body
    assert 'data-can-change="false"' in body


def test_start_from_starter_link_present_only_when_read_only(admin_client: Client) -> None:
    body = admin_client.get(edit_url(FIRED)).content.decode()
    assert "Анхдагчаас шинээр эхлэх" not in body

    upload(FIRED, docx_with_table())
    body = admin_client.get(edit_url(FIRED)).content.decode()
    assert "Анхдагчаас шинээр эхлэх" in body


def test_letterhead_block_links_to_company_settings(admin_client: Client) -> None:
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert "Бланк засах" in body
    assert f'href="{reverse("admin:employees_companysettings_changelist")}"' in body
    assert "js/letterhead_preview.js" in body


def test_reset_button_label_is_exact(admin_client: Client) -> None:
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert "Анхдагч загварт буцаах" in body


def test_letterhead_column_header_is_mongolian(admin_client: Client) -> None:
    OrderTemplate.ensure_all()

    body = admin_client.get(reverse("admin:employees_ordertemplate_changelist")).content.decode()

    assert "Бланк" in body
    assert "Letterhead" not in body


def test_company_settings_page_loads_letterhead_preview_js(admin_client: Client) -> None:
    from employees.models import CompanySettings

    row = CompanySettings.get()
    body = admin_client.get(reverse("admin:employees_companysettings_change", args=[row.pk])).content.decode()

    assert "js/letterhead_preview.js" in body


STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


def test_editor_css_styles_every_hr_confirm_class_modal_js_builds() -> None:
    # The class names come from modal.js itself, so the stylesheet cannot drift from the dialog it draws.
    modal = (STATIC_DIR / "js" / "modal.js").read_text(encoding="utf-8")
    css = (STATIC_DIR / "css" / "order_template_editor.css").read_text(encoding="utf-8")
    built: set[str] = set()
    for classes in re.findall(r'className\s*=\s*"([^"]*)"', modal):
        built.update(name for name in classes.split() if name.startswith("hr-confirm"))
    assert {"hr-confirm", "hr-confirm-panel", "hr-confirm-text", "hr-confirm-row"} <= built  # the scan found the dialog
    for name in sorted(built):
        assert re.search(r"\." + re.escape(name) + r"(?![\w-])", css), name
    assert re.search(r"\.hr-confirm\s*\{[^}]*position:\s*fixed", css)  # the overlay covers the page


def test_editor_page_loads_order_template_editor_css(admin_client: Client) -> None:
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert "css/order_template_editor.css" in body


def test_company_settings_page_loads_the_editor_css_for_the_letterhead_mock(admin_client: Client) -> None:
    from employees.models import CompanySettings

    row = CompanySettings.get()
    body = admin_client.get(reverse("admin:employees_companysettings_change", args=[row.pk])).content.decode()

    assert "order_template_editor.css" in body


# --- Fix wave (task 10): a read-only template has no save or letterhead switch, but still previews and downloads ---


def test_read_only_hired_page_has_no_save_or_letterhead_switch_but_preview_and_download(
    admin_client: Client,
) -> None:
    upload(HIRED, docx_with_table())
    body = admin_client.get(edit_url(HIRED)).content.decode()

    assert "Хадгалах" not in body
    assert 'id="ote-save"' not in body
    assert "Бланк харуулах" not in body
    assert 'id="ote-show-letterhead"' not in body
    assert "Урьдчилан харах" in body
    assert "Word болгон татах" in body


def test_preview_without_doc_renders_the_stored_template(
    admin_client: Client, hired: Employee, rendered: list[bytes]
) -> None:
    body = {"doc": None, "employee_id": hired.pk, "show_letterhead": True}

    response = preview(admin_client, HIRED, body)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert rendered  # the stored starter was filled and drawn


@pytest.mark.parametrize("bad_doc", ["text", ["paragraph"], 5, {"paragraphs": "no"}, False, 0, ""])
def test_preview_with_a_malformed_doc_is_400(admin_client: Client, hired: Employee, bad_doc: Any) -> None:
    body = {"doc": bad_doc, "employee_id": hired.pk, "show_letterhead": True}

    response = preview(admin_client, HIRED, body)

    assert response.status_code == 400


def test_preview_of_a_corrupt_stored_template_is_400_not_500(admin_client: Client, hired: Employee) -> None:
    upload(HIRED, b"not a word file")
    body = {"doc": None, "employee_id": hired.pk, "show_letterhead": True}

    response = preview(admin_client, HIRED, body)

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert response.json()["errors"]


def test_preview_of_a_zip_that_is_not_a_word_file_is_400_not_500(admin_client: Client, hired: Employee) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")
    upload(HIRED, buffer.getvalue())
    body = {"doc": None, "employee_id": hired.pk, "show_letterhead": True}

    response = preview(admin_client, HIRED, body)

    assert response.status_code == 400
    assert response.json()["ok"] is False


# --- Fix round 1: view-only page hides the write controls; start-new is offered only for a read-only file ---


def test_view_only_page_has_no_save_or_letterhead_switch(view_client: Client) -> None:
    body = view_client.get(edit_url(FIRED)).content.decode()

    assert 'id="ote-save"' not in body
    assert 'id="ote-show-letterhead"' not in body
    assert 'id="ote-reset"' not in body
    assert 'id="ote-preview-open"' in body
    assert "Word болгон татах" in body


def test_start_new_button_only_for_read_only_uploaded_file(admin_client: Client) -> None:
    upload(FIRED, docx_with_table())
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert 'id="ote-start-new"' in body
    assert "Одоогийн файлын текст алдагдана" in body  # the confirm wording lives in the page script


def test_start_new_button_absent_on_editable_page(admin_client: Client) -> None:
    body = admin_client.get(edit_url(FIRED)).content.decode()

    assert 'id="ote-start-new"' not in body

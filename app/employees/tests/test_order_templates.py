"""The install's own order templates (D-053): upload check, sandbox, fallback to the bundled starter, admin page."""

import importlib
import io
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from docx import Document

from employees.models import CompanySettings, Employee, HrOrder, OrderTemplate, OrderType
from employees.services import order_docs

from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def private_files(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path


def docx_with(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def text_of(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def upload(order_type: OrderType, data: bytes) -> None:
    row, _ = OrderTemplate.objects.get_or_create(order_type=order_type.value)
    row.file.save("mine.docx", ContentFile(data))


def test_placeholders_are_exactly_what_the_context_fills(hired: Employee, actor: User) -> None:
    assert set(order_docs.PLACEHOLDERS) == set(order_docs.build_context(hire_order(hired), actor))


@pytest.mark.parametrize("order_type", list(OrderType))
def test_bundled_starters_pass_the_upload_check(order_type: OrderType) -> None:
    assert order_docs.check_template(order_docs.starter_path(order_type).read_bytes()) == []


def test_check_refuses_what_is_not_a_template() -> None:
    assert order_docs.check_template(b"not a word file")
    assert "secret" in order_docs.check_template(docx_with("{{ secret }}"))[0]
    assert order_docs.check_template(docx_with("{% if %}"))  # broken tag
    assert order_docs.check_template(docx_with("{{ company_name }} № {{ order_number }}")) == []


def test_template_cannot_reach_python_internals() -> None:
    assert order_docs.check_template(docx_with("{{ order_number.__class__.__mro__ }}"))


def test_an_uploaded_template_is_used_and_the_starter_is_the_fallback(hired: Employee, actor: User) -> None:
    order = hire_order(hired)
    assert "ТУШААЛ" in text_of(order_docs.render_order(order, actor))  # starter
    CompanySettings.objects.update_or_create(pk=1, defaults={"name": "Жишээ ХХК"})
    upload(OrderType.HIRED, docx_with("Манай загвар: {{ company_name }}"))
    assert "Манай загвар: Жишээ ХХК" in text_of(order_docs.render_order(order, actor))
    OrderTemplate.objects.filter(order_type=OrderType.HIRED).update(file="")  # cleared: the starter again
    assert "ТУШААЛ" in text_of(order_docs.render_order(order, actor))


def test_a_missing_uploaded_file_is_an_error_not_a_silent_fallback(hired: Employee, actor: User) -> None:
    upload(OrderType.HIRED, docx_with("{{ company_name }}"))
    OrderTemplate.objects.get(order_type=OrderType.HIRED).file.delete(save=False)
    with pytest.raises(order_docs.OrderDocError):
        order_docs.render_order(hire_order(hired), actor)


@pytest.fixture
def admin_client() -> Client:
    client = Client()
    client.force_login(User.objects.create_superuser("tpl_admin", password="x-long-pass-123"))  # noqa: S106
    return client


def test_admin_lists_all_six_types_from_the_first_visit(admin_client: Client) -> None:
    body = admin_client.get(reverse("admin:employees_ordertemplate_changelist")).content.decode()
    assert OrderTemplate.objects.count() == 6
    for label in OrderType.labels:
        assert label in body


def change_url(order_type: OrderType) -> str:
    OrderTemplate.ensure_all()
    return reverse("admin:employees_ordertemplate_change", args=[OrderTemplate.objects.get(order_type=order_type).pk])


def post(client: Client, order_type: OrderType, **fields: Any) -> Any:
    return client.post(change_url(order_type), fields)


def test_admin_upload_is_checked_and_saved(admin_client: Client) -> None:
    good = SimpleUploadedFile("mine.docx", docx_with("{{ company_name }}"), content_type=order_docs.DOCX_TYPE)
    assert post(admin_client, OrderType.FIRED, file=good).status_code == 302
    row = OrderTemplate.objects.get(order_type=OrderType.FIRED)
    assert row.file and row.updated_by is not None

    for name, data, needle in (
        ("x.docx", b"junk", "docx"),
        ("x.docx", docx_with("{{ nope }}"), "nope"),
        ("x.txt", docx_with("{{ company_name }}"), ".docx"),
    ):
        bad = SimpleUploadedFile(name, data)
        response = post(admin_client, OrderType.PENSION, file=bad)
        assert response.status_code == 200 and needle in response.content.decode()
    assert not OrderTemplate.objects.get(order_type=OrderType.PENSION).file


def test_admin_clear_puts_the_starter_back(admin_client: Client) -> None:
    upload(OrderType.POSITION, docx_with("{{ company_name }}"))
    assert post(admin_client, OrderType.POSITION, **{"file-clear": "on"}).status_code == 302
    assert not OrderTemplate.objects.get(order_type=OrderType.POSITION).file


def download(client: Client, url: str, which: str) -> bytes:
    response: Any = client.get(url, {"which": which})
    return b"".join(response.streaming_content)


def test_admin_downloads_the_current_and_the_starter_file(admin_client: Client) -> None:
    upload(OrderType.DEPARTMENT, docx_with("Манай загвар"))
    pk = OrderTemplate.objects.get(order_type=OrderType.DEPARTMENT).pk
    url = reverse("admin:employees_ordertemplate_download", args=[pk])
    assert "Манай загвар" in text_of(download(admin_client, url, "current"))
    assert "ТУШААЛ" in text_of(download(admin_client, url, "starter"))


def test_only_the_admin_may_open_the_page(client: Client) -> None:
    OrderTemplate.ensure_all()
    login_as(client, "HR", "hr1")
    pk = OrderTemplate.objects.first().pk  # type: ignore[union-attr]
    for url in (
        reverse("admin:employees_ordertemplate_changelist"),
        reverse("admin:employees_ordertemplate_download", args=[pk]),
    ):
        response = client.get(url)
        assert response.status_code in (302, 403, 404) and b"ordertemplate" not in response.content.lower()


def test_letterhead_on_is_true_without_a_row_or_file() -> None:
    assert OrderTemplate.letterhead_on(OrderType.HIRED) is True  # no row yet
    OrderTemplate.objects.create(order_type=OrderType.HIRED, show_letterhead=False)
    assert OrderTemplate.letterhead_on(OrderType.HIRED) is True  # no file: the starter, which always has it


def test_letterhead_new_row_defaults_to_on() -> None:
    row = OrderTemplate.objects.create(order_type=OrderType.POSITION)
    assert row.show_letterhead is True


def test_letterhead_migration_data_step_turns_off_rows_with_a_file() -> None:
    from django.apps import apps

    migration = importlib.import_module("employees.migrations.0036_ordertemplate_show_letterhead")
    upload(OrderType.HIRED, docx_with("Манай загвар"))
    OrderTemplate.objects.get_or_create(order_type=OrderType.DEPARTMENT)
    OrderTemplate.objects.update(show_letterhead=True)
    migration.turn_off_for_uploaded(apps, None)
    assert OrderTemplate.objects.get(order_type=OrderType.HIRED).show_letterhead is False
    assert OrderTemplate.objects.get(order_type=OrderType.DEPARTMENT).show_letterhead is True


def test_letterhead_on_reads_the_flag_for_an_uploaded_file() -> None:
    upload(OrderType.DEPARTMENT, docx_with("Манай загвар"))
    assert OrderTemplate.letterhead_on(OrderType.DEPARTMENT) is True
    OrderTemplate.objects.filter(order_type=OrderType.DEPARTMENT).update(show_letterhead=False)
    assert OrderTemplate.letterhead_on(OrderType.DEPARTMENT) is False


def test_admin_change_page_has_the_letterhead_switch_even_for_a_starter_template(client: Client) -> None:
    client.force_login(User.objects.create_superuser("tpl_admin", password="x-long-pass-123"))  # noqa: S106
    row = OrderTemplate.objects.get_or_create(order_type=OrderType.HIRED.value)[0]  # no file: the starter

    response = client.get(f"/admin/employees/ordertemplate/{row.pk}/change/")

    assert response.status_code == 200
    assert b'name="show_letterhead"' in response.content


def test_admin_post_without_the_switch_stores_false_and_keeps_the_file(client: Client) -> None:
    client.force_login(User.objects.create_superuser("tpl_admin2", password="x-long-pass-123"))  # noqa: S106
    upload(OrderType.HIRED, docx_with("Манай загвар"))
    row = OrderTemplate.objects.get(order_type=OrderType.HIRED.value)
    stored_file = row.file.name

    response = client.post(f"/admin/employees/ordertemplate/{row.pk}/change/", {})

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.show_letterhead is False
    assert row.file.name == stored_file


def test_view_only_user_cannot_change_the_letterhead_switch(client: Client) -> None:
    viewer = User.objects.create_user("tpl_viewer", password="x-long-pass-123")  # noqa: S106
    viewer.is_staff = True
    viewer.save(update_fields=["is_staff"])
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_ordertemplate", content_type__app_label="employees")
    )
    client.force_login(viewer)
    row = OrderTemplate.objects.get_or_create(order_type=OrderType.HIRED.value)[0]

    response = client.post(f"/admin/employees/ordertemplate/{row.pk}/change/", {})

    assert response.status_code == 403
    row.refresh_from_db()
    assert row.show_letterhead is True


def test_admin_untick_on_a_starter_row_saves_true_because_the_starter_always_prints_the_letterhead(
    client: Client,
) -> None:
    client.force_login(User.objects.create_superuser("tpl_admin3", password="x-long-pass-123"))  # noqa: S106
    row = OrderTemplate.objects.get_or_create(order_type=OrderType.HIRED.value)[0]  # no file: the starter

    response = client.post(f"/admin/employees/ordertemplate/{row.pk}/change/", {})

    assert response.status_code == 302
    row.refresh_from_db()
    assert not row.file
    assert row.show_letterhead is True


def test_admin_untick_with_a_new_docx_on_a_starter_row_keeps_the_unticked_switch(client: Client) -> None:
    client.force_login(User.objects.create_superuser("tpl_admin4", password="x-long-pass-123"))  # noqa: S106
    row = OrderTemplate.objects.get_or_create(order_type=OrderType.HIRED.value)[0]  # no file: the starter
    good = SimpleUploadedFile("mine.docx", docx_with("{{ company_name }}"), content_type=order_docs.DOCX_TYPE)

    response = client.post(f"/admin/employees/ordertemplate/{row.pk}/change/", {"file": good})

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.file
    assert row.show_letterhead is False


def test_admin_clear_with_an_untick_on_a_row_with_a_file_saves_true(client: Client) -> None:
    client.force_login(User.objects.create_superuser("tpl_admin5", password="x-long-pass-123"))  # noqa: S106
    upload(OrderType.HIRED, docx_with("Манай загвар"))
    row = OrderTemplate.objects.get(order_type=OrderType.HIRED.value)

    response = client.post(f"/admin/employees/ordertemplate/{row.pk}/change/", {"file-clear": "on"})

    assert response.status_code == 302
    row.refresh_from_db()
    assert not row.file
    assert row.show_letterhead is True

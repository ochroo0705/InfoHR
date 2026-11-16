"""Company letterhead: the fields on CompanySettings, the logo check in the admin form, and who may change them."""

import io
import warnings
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from employees.admin import CompanySettingsAdmin, CompanySettingsForm
from employees.models import LETTERHEAD_LOGO_MM, CompanySettings

pytestmark = pytest.mark.django_db

MAX_LOGO_BYTES = 2 * 1024 * 1024


@pytest.fixture(autouse=True)
def private_files(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path


def _image_bytes(fmt: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(out, fmt)
    return out.getvalue()


def _upload(name: str, data: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def _form_data(**extra: Any) -> dict[str, Any]:
    """The fields the company settings form needs to be valid; the letterhead fields come in through extra."""
    data: dict[str, Any] = {
        "soon_days": 30,
        "selfform_retention_days": 30,
        "selfform_default_hours": 72,
        "selfform_base_url": "",
        "selfform_notice": "",
        "letterhead_logo_place": "left",
        "letterhead_text_align": "left",
        "letterhead_logo_size": "medium",
    }
    data.update(extra)
    return data


def _logo_form(upload: SimpleUploadedFile) -> CompanySettingsForm:
    return CompanySettingsForm(data=_form_data(), files={"letterhead_logo": upload}, instance=CompanySettings.get())


def test_defaults() -> None:
    row = CompanySettings.get()

    assert not row.letterhead_logo
    assert row.letterhead_lines == ""
    assert row.letterhead_logo_place == "left"
    assert row.letterhead_text_align == "left"
    assert row.letterhead_logo_size == "medium"
    assert row.letterhead_rule is True
    assert row.letterhead_every_page is False
    assert LETTERHEAD_LOGO_MM == {"small": 20, "medium": 30, "large": 45}


def test_letterhead_text_substitutes_company_and_director_and_drops_blank_lines() -> None:
    row = CompanySettings.get()
    row.name = "Жишээ ХХК"
    row.director_name = "Б. Батболд"
    row.letterhead_lines = "{company_name}\n\n Утас: 7700-0000 \n{director_name}\n{director_name}x\n   \n"
    row.save()

    assert CompanySettings.objects.get(pk=1).letterhead_text() == [
        "Жишээ ХХК",
        "Утас: 7700-0000",
        "Б. Батболд",
        "Б. Батболдx",
    ]


def test_letterhead_text_drops_a_line_that_is_only_an_empty_field() -> None:
    row = CompanySettings.get()
    row.letterhead_lines = "{director_name}\nХаяг"
    row.save()

    assert CompanySettings.objects.get(pk=1).letterhead_text() == ["Хаяг"]


def test_form_refuses_non_image_logo() -> None:
    form = _logo_form(_upload("logo.gif", _image_bytes("GIF")))

    assert not form.is_valid()
    assert "letterhead_logo" in form.errors
    assert "PNG" in str(form.errors["letterhead_logo"])


def test_form_refuses_a_file_that_is_not_an_image() -> None:
    form = _logo_form(_upload("logo.png", b"this is not a picture"))

    assert not form.is_valid()
    assert "letterhead_logo" in form.errors


def test_form_refuses_logo_over_2mb() -> None:
    too_big = _image_bytes("PNG") + b"\0" * (MAX_LOGO_BYTES + 1 - len(_image_bytes("PNG")))
    form = _logo_form(_upload("logo.png", too_big))

    assert not form.is_valid()
    assert "2 МБ" in str(form.errors["letterhead_logo"])


def test_form_accepts_png_and_jpg() -> None:
    for name, fmt in (("logo.png", "PNG"), ("logo.jpg", "JPEG")):
        form = _logo_form(_upload(name, _image_bytes(fmt)))
        assert form.is_valid(), form.errors


def test_view_only_user_cannot_change_letterhead(client: Client) -> None:
    user = User.objects.create_user("letterhead_viewer", password="x-long-pass-123")  # noqa: S106
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(
        Permission.objects.get(codename="view_companysettings", content_type__app_label="employees")
    )
    client.force_login(user)
    row = CompanySettings.get()

    response = client.post(
        f"/admin/employees/companysettings/{row.pk}/change/",
        _form_data(letterhead_lines="Хаяг", letterhead_logo_size="large"),
    )

    assert response.status_code == 403
    stored = CompanySettings.objects.get(pk=1)
    assert stored.letterhead_lines == ""
    assert stored.letterhead_logo_size == "medium"


def test_logo_lands_in_order_files_root(client: Client, settings: Any) -> None:
    client.force_login(User.objects.create_superuser("letterhead_admin", password="x-long-pass-123"))  # noqa: S106
    row = CompanySettings.get()

    response = client.post(
        f"/admin/employees/companysettings/{row.pk}/change/",
        _form_data(
            name="Жишээ ХХК",
            letterhead_lines="{company_name}",
            letterhead_logo=_upload("logo.png", _image_bytes("PNG")),
        ),
    )

    assert response.status_code == 302
    stored = CompanySettings.objects.get(pk=1)
    assert stored.letterhead_logo.name.startswith("letterhead/")
    assert Path(settings.ORDER_FILES_ROOT, stored.letterhead_logo.name).is_file()


def _solid_png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, "PNG")  # solid colour: compresses to a few kilobytes
    return out.getvalue()


def _lines_form(lines: str) -> CompanySettingsForm:
    return CompanySettingsForm(data=_form_data(letterhead_lines=lines), instance=CompanySettings.get())


def test_form_refuses_more_than_8_letterhead_lines() -> None:
    form = _lines_form("\n".join(f"Мөр {index}" for index in range(9)))

    assert not form.is_valid()
    assert "8 мөр" in str(form.errors["letterhead_lines"])


def test_form_refuses_a_letterhead_line_longer_than_120_characters() -> None:
    form = _lines_form("а" * 121)

    assert not form.is_valid()
    assert "120" in str(form.errors["letterhead_lines"])


def test_form_accepts_8_letterhead_lines_of_120_characters() -> None:
    form = _lines_form("\n".join("б" * 120 for _ in range(8)))

    assert form.is_valid(), form.errors


def test_form_does_not_count_blank_lines_towards_the_limit() -> None:
    form = _lines_form("\n\n".join("Мөр" for _ in range(8)) + "\n\n\n")

    assert form.is_valid(), form.errors


def test_form_refuses_a_logo_with_too_many_pixels() -> None:
    form = _logo_form(_upload("huge.png", _solid_png(6000, 5000)))  # 30 megapixels, a few kilobytes on disk

    assert not form.is_valid()
    assert "мегапиксел" in str(form.errors["letterhead_logo"])


def test_letterhead_mock_renders_without_a_format_html_warning() -> None:
    admin_page = CompanySettingsAdmin(CompanySettings, AdminSite())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        html = admin_page.letterhead_mock(CompanySettings.get())

    assert "data-letterhead-mock" in html
    assert not [w for w in caught if "format_html" in str(w.message)]

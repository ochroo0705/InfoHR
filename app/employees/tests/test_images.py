from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.datastructures import MultiValueDict
from PIL import Image

from employees.forms import EmployeeForm
from employees.images import MAX_SIDE, MAX_UPLOAD_BYTES, shrink_photo, thumbnail_url
from employees.models import Employee


def _upload(size: tuple[int, int], fmt: str = "JPEG", exif: Image.Exif | None = None) -> SimpleUploadedFile:
    buffer = BytesIO()
    image = Image.new("RGB", size, "red")
    image.save(buffer, fmt, **({"exif": exif} if exif is not None else {}))
    return SimpleUploadedFile(f"big.{fmt.lower()}", buffer.getvalue(), content_type=f"image/{fmt.lower()}")


def _open(upload: SimpleUploadedFile) -> Image.Image:
    upload.seek(0)
    return Image.open(upload)


def test_large_photo_is_shrunk_to_max_side_as_jpeg() -> None:
    result = shrink_photo(_upload((3840, 2160)))
    image = _open(result)
    assert image.format == "JPEG"
    assert max(image.size) == MAX_SIDE
    assert image.size == (MAX_SIDE, MAX_SIDE * 9 // 16)
    assert str(result.name).endswith(".jpg")


def test_small_photo_keeps_its_size() -> None:
    image = _open(shrink_photo(_upload((300, 400), "PNG")))
    assert image.size == (300, 400) and image.format == "JPEG"


def test_exif_orientation_is_applied_and_metadata_removed() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees when displayed
    exif[0x010F] = "PhoneMaker"
    image = _open(shrink_photo(_upload((1600, 800), exif=exif)))
    assert image.size == (MAX_SIDE // 2, MAX_SIDE)
    assert not image.getexif()


def test_transparent_png_becomes_jpeg_on_white() -> None:
    buffer = BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, "PNG")
    upload = SimpleUploadedFile("t.png", buffer.getvalue(), content_type="image/png")
    image = _open(shrink_photo(upload)).convert("RGB")
    assert image.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.django_db
def test_form_rejects_oversized_upload() -> None:
    upload = _upload((2000, 1800), "BMP")  # uncompressed, about 10.8 MB
    assert (upload.size or 0) > MAX_UPLOAD_BYTES
    form = EmployeeForm(data={}, files=MultiValueDict({"photo": [upload]}))
    form.is_valid()
    assert "photo" in form.errors
    assert "МБ" in form.errors["photo"][0]


@pytest.mark.django_db
def test_thumbnail_is_exact_square_cached_and_survives_missing_file(
    hired: Employee, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(tmp_path)
    assert thumbnail_url(hired.photo, 80) == ""
    hired.photo.save("face.jpg", shrink_photo(_upload((800, 600))))
    url = thumbnail_url(hired.photo, 80)
    thumb = tmp_path / "employees" / "photos" / Path(url).name
    assert url.endswith("_80hq.jpg") and Image.open(thumb).size == (80, 80)
    mtime = thumb.stat().st_mtime_ns
    assert thumbnail_url(hired.photo, 80) == url and thumb.stat().st_mtime_ns == mtime
    gone = Employee.objects.get(pk=hired.pk)
    gone.photo.name = "employees/photos/gone.jpg"
    assert thumbnail_url(gone.photo, 80) == gone.photo.url

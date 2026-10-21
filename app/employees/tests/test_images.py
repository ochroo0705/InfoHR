import base64
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils.datastructures import MultiValueDict
from PIL import Image

from employees.forms import EmployeeForm
from employees.images import JPEG_SIGNATURE, MAX_SIDE, MAX_UPLOAD_BYTES, photo_bytes, shrink_photo, thumbnail_url
from employees.models import Employee


def _upload(
    size: tuple[int, int], fmt: str = "JPEG", exif: Image.Exif | None = None, color: str = "white"
) -> SimpleUploadedFile:
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
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
    assert image.size[0] == MAX_SIDE and abs(image.size[1] - MAX_SIDE * 9 / 16) <= 1  # aspect kept
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
def test_photo_round_trip_and_replacement(hired: Employee, settings: Any, tmp_path: Path) -> None:
    from macs.models import EmployeePhoto

    from employees.services import macs_writes

    settings.MEDIA_ROOT = str(tmp_path)
    assert thumbnail_url(hired, 80) == ""
    first = shrink_photo(_upload((800, 600))).read()
    macs_writes.save_photo(hired, first)
    url1 = thumbnail_url(hired, 80)
    second = shrink_photo(_upload((640, 640), color="red")).read()
    macs_writes.save_photo(hired, second)
    url2 = thumbnail_url(hired, 80)
    assert EmployeePhoto.objects.filter(employee=hired).count() == 1
    assert url1 != url2  # new picture, new cache file
    pixel = Image.open(tmp_path / "employees" / "thumbs" / Path(url2).name).getpixel((40, 40))
    red, green, blue = cast(tuple[int, int, int], pixel)
    assert red > 240 and green < 16 and blue < 16  # JPEG is lossy: allow a little drift
    stored = bytes(cast(bytes, EmployeePhoto.objects.get(employee=hired).data))
    assert stored == second  # raw JPEG bytes, no base64


@pytest.mark.django_db
def test_thumbnail_is_exact_square_and_cached(hired: Employee, settings: Any, tmp_path: Path) -> None:
    from employees.services import macs_writes

    settings.MEDIA_ROOT = str(tmp_path)
    macs_writes.save_photo(hired, shrink_photo(_upload((800, 600))).read())
    url = thumbnail_url(hired, 80)
    thumb = next((tmp_path / "employees" / "thumbs").glob("*_80_*.jpg"))
    assert url.endswith(thumb.name) and Image.open(thumb).size == (80, 80)
    mtime = thumb.stat().st_mtime_ns
    assert thumbnail_url(hired, 80) == url and thumb.stat().st_mtime_ns == mtime


def _png_upload(size: tuple[int, int]) -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", size, "blue").save(buffer, "PNG")
    return SimpleUploadedFile("big.png", buffer.getvalue(), content_type="image/png")


def _jpeg_bytes(size: tuple[int, int] = (200, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "green").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("encode", [False, True], ids=["raw_jpeg", "base64_jpeg"])
def test_reader_shows_raw_and_base64_jpeg(hired: Employee, settings: Any, tmp_path: Path, encode: bool) -> None:
    from employees.services import macs_writes

    settings.MEDIA_ROOT = str(tmp_path)
    jpeg = _jpeg_bytes()
    macs_writes.save_photo(hired, base64.b64encode(jpeg) if encode else jpeg)
    assert thumbnail_url(hired, 80) != ""


@pytest.mark.django_db
def test_reader_shows_raw_png(hired: Employee, settings: Any, tmp_path: Path) -> None:
    from employees.services import macs_writes

    settings.MEDIA_ROOT = str(tmp_path)
    buffer = BytesIO()
    Image.new("RGB", (120, 90), "blue").save(buffer, "PNG")
    macs_writes.save_photo(hired, buffer.getvalue())
    assert thumbnail_url(hired, 80) != ""


@pytest.mark.django_db
def test_reader_treats_garbage_as_no_photo(hired: Employee, settings: Any, tmp_path: Path) -> None:
    from employees.services import macs_writes

    settings.MEDIA_ROOT = str(tmp_path)
    macs_writes.save_photo(hired, b"this is not an image")
    assert thumbnail_url(hired, 80) == ""


def test_photo_bytes_rules() -> None:
    jpeg = _jpeg_bytes()
    assert photo_bytes(jpeg) == jpeg
    assert photo_bytes(base64.b64encode(jpeg)) == jpeg
    assert photo_bytes(base64.b64encode(b"hello")) is None
    assert photo_bytes(b"") is None
    assert photo_bytes(None) is None


@pytest.mark.django_db
def test_save_photo_stores_raw_jpeg(hired: Employee) -> None:
    from macs.models import EmployeePhoto

    from employees.services import macs_writes

    macs_writes.save_photo(hired, shrink_photo(_upload((800, 600))).read())
    stored = bytes(cast(bytes, EmployeePhoto.objects.get(employee=hired).data))
    assert stored.startswith(JPEG_SIGNATURE)
    assert EmployeePhoto.objects.filter(employee=hired).count() == 1


@pytest.mark.django_db
def test_large_png_upload_is_stored_as_600px_jpeg(hired: Employee) -> None:
    from macs.models import EmployeePhoto

    from employees.services import macs_writes

    form = EmployeeForm(data={}, files=MultiValueDict({"photo": [_png_upload((2000, 1500))]}))
    form.is_valid()
    photo = form.photo_bytes()
    assert isinstance(photo, bytes)
    macs_writes.save_photo(hired, photo)
    stored = bytes(cast(bytes, EmployeePhoto.objects.get(employee=hired).data))
    assert stored.startswith(JPEG_SIGNATURE)
    image = Image.open(BytesIO(stored))
    assert image.format == "JPEG" and image.size == (600, 450)


@pytest.mark.django_db
def test_fix_photo_encoding_converts_base64_once(hired: Employee) -> None:
    from macs.models import EmployeePhoto

    from employees.services import macs_writes

    jpeg = _jpeg_bytes()
    macs_writes.save_photo(hired, base64.b64encode(jpeg))
    call_command("fix_photo_encoding")
    assert bytes(cast(bytes, EmployeePhoto.objects.get(employee=hired).data)) == jpeg
    call_command("fix_photo_encoding")  # second run changes nothing
    assert bytes(cast(bytes, EmployeePhoto.objects.get(employee=hired).data)) == jpeg


def test_thumbnail_keeps_the_top_of_a_tall_photo() -> None:
    """A tall photo is cut a third of the way down, not from the middle, so the head is kept (portrait crop)."""
    from PIL import Image, ImageOps

    from employees.images import THUMB_CENTERING

    tall = Image.new("RGB", (100, 300), "white")
    tall.paste((255, 0, 0), (0, 70, 100, 95))  # a red "head" in the upper third, as in a staff photo
    square = ImageOps.fit(tall, (100, 100), centering=THUMB_CENTERING)
    assert square.getpixel((50, 20)) == (255, 0, 0)  # the head is in the frame
    middle = ImageOps.fit(tall, (100, 100))
    assert (255, 0, 0) not in {middle.getpixel((50, y)) for y in range(100)}  # a middle crop loses it

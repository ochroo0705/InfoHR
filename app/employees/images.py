"""Employee photo processing: shrink, fix rotation, drop metadata."""

import base64
import hashlib
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from macs.dialect import is_firebird
from PIL import Image, ImageOps

from employees.models import Employee

MAX_SIDE = 600
JPEG_QUALITY = 85
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _is_image(data: bytes) -> bool:
    return data.startswith((JPEG_SIGNATURE, PNG_SIGNATURE))


def photo_bytes(raw: bytes | memoryview | None) -> bytes | None:
    """The image bytes stored in emp_photo, or None when there is no usable JPEG/PNG.

    MACS and this program both store raw JPEG bytes. Rows written by older HR versions hold
    base64 text of the image, so those are decoded. Anything else is treated as no photo.
    """
    if not raw:
        return None
    data = bytes(raw)
    if _is_image(data):
        return data
    try:
        decoded = base64.b64decode(data, validate=True)
    except ValueError:
        return None
    return decoded if _is_image(decoded) else None


def shrink_photo(upload: UploadedFile) -> SimpleUploadedFile:
    """Return the photo as a JPEG at most MAX_SIDE px on its longest side.

    The EXIF orientation is applied to the pixels and all metadata (GPS, camera)
    is dropped, since the re-encoded file is written without it.
    """
    upload.seek(0)
    with Image.open(upload) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    name = Path(upload.name or "photo").stem + ".jpg"
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


# Where the square thumbnail is cut from: centred across, and a third of the way down. Staff photos are usually
# taller than wide with the face in the upper part, so a middle crop cut off foreheads; a wide photo is unaffected.
THUMB_CENTERING = (0.5, 0.3)
CROP_TAG = "c30"


def attach_photo_digests(employees: Iterable[Employee]) -> None:
    """Look up the photo hash of many employees in one query (Postgres hashes; no image bytes travel).

    `thumbnail_url` then finds the cached thumbnail without reading the photo, so a list of 300 people
    costs one query instead of one per person. An employee with no photo gets an empty hash."""
    from django.db.models import CharField, F, Func
    from macs.models import EmployeePhoto

    people = list(employees)
    for person in people:
        person._photo_md5 = ""  # type: ignore[attr-defined]
    by_pk = {p.pk: p for p in people}
    if is_firebird():
        # Firebird 3 has no MD5 function, so the bytes are hashed here; hexdigest matches PostgreSQL's md5() text.
        rows = (
            EmployeePhoto.objects.filter(employee_id__in=list(by_pk), data__isnull=False)
            .order_by("-id")  # lowest id is assigned last and wins, as on PostgreSQL and `.first()` in thumbnail_url
            .values_list("employee_id", "data")
        )
        for employee_id, raw in rows:
            digest = hashlib.md5(bytes(raw), usedforsecurity=False).hexdigest()
            by_pk[employee_id]._photo_md5 = digest  # type: ignore[attr-defined]
        return
    hashed = (
        EmployeePhoto.objects.filter(employee_id__in=[p.pk for p in people], data__isnull=False)
        .annotate(digest=Func(F("data"), function="md5", output_field=CharField()))
        .order_by("-id")  # lowest id is assigned last and wins, as `.first()` does in thumbnail_url
        .values_list("employee_id", "digest")
    )
    for employee_id, digest in hashed:
        by_pk[employee_id]._photo_md5 = digest or ""  # type: ignore[attr-defined]


def thumbnail_url(employee: Employee, side: int) -> str:
    """URL of a side x side JPEG made from the photo in emp_photo; "" when there is no photo.

    Cached on disk by a hash of the stored photo bytes, so a replaced photo gets a new file.
    """
    from django.core.files.storage import default_storage
    from macs.models import EmployeePhoto

    known = getattr(employee, "_photo_md5", None)  # set by attach_photo_digests for a whole list
    if known == "":
        return ""
    raw = None
    if known is None:
        raw = EmployeePhoto.objects.filter(employee=employee).values_list("data", flat=True).first()
        if photo_bytes(raw) is None:
            return ""
        known = hashlib.md5(bytes(raw or b""), usedforsecurity=False).hexdigest()
    name = f"employees/thumbs/{employee.pk}_{side}_{known[:12]}_{CROP_TAG}.jpg"  # new crop -> new file
    if not default_storage.exists(name):
        if raw is None:  # the hash came from the list lookup: read the photo now (once per new thumbnail)
            raw = EmployeePhoto.objects.filter(employee=employee).values_list("data", flat=True).first()
        jpeg = photo_bytes(raw)
        if jpeg is None:
            return ""
        try:
            with Image.open(BytesIO(jpeg)) as source:
                image = ImageOps.fit(
                    ImageOps.exif_transpose(source).convert("RGB"),
                    (side, side),
                    Image.Resampling.LANCZOS,
                    centering=THUMB_CENTERING,
                )
                buffer = BytesIO()
                # Full-colour (4:4:4) JPEG keeps edges around eyes and hair crisp at small sizes.
                image.save(buffer, "JPEG", quality=95, subsampling=0)
        except Exception:  # Pillow raises several types for broken data
            return ""
        default_storage.save(name, ContentFile(buffer.getvalue()))
    return default_storage.url(name)

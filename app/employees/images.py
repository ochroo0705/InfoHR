"""Employee photo processing: shrink, fix rotation, drop metadata."""

from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.db.models.fields.files import FieldFile
from PIL import Image, ImageOps

MAX_SIDE = 800
JPEG_QUALITY = 85
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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


def thumbnail_url(photo: FieldFile, side: int) -> str:
    """URL of a square side x side copy of the photo, created on first use.

    Browsers shrink large images coarsely, so a photo scaled down by the page looks
    grainy. Avatars use a copy cropped and resampled once to the exact pixel size.
    """
    if not photo:
        return ""
    original = Path(photo.name or "")
    name = original.with_name(f"{original.stem}_{side}.jpg").as_posix()
    storage = photo.storage
    if not storage.exists(name):
        try:
            with photo.open("rb"), Image.open(photo) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image = ImageOps.fit(image, (side, side), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, "JPEG", quality=90)
        except Exception:  # Pillow raises several types for missing or broken files
            return photo.url
        storage.save(name, ContentFile(buffer.getvalue()))
    return storage.url(name)

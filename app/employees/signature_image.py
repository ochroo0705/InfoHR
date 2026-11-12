"""Clean a hand-drawn signature taken from the on-screen signing pad.

The browser sends the drawing as a PNG data URL. We decode it, check it, trim the
blank margin, shrink it if it is wide, and re-encode it with Pillow. The client's
bytes are never stored as they came in.
"""

import base64
import binascii
import io
import re

from PIL import Image, ImageChops

MAX_UPLOAD_BYTES = 300 * 1024
MAX_SIDE_PX = 1600
MAX_WIDTH_PX = 600
TRIM_PAD_PX = 4
INK_LUMINANCE_BELOW = 240

DRAW_ERROR = "Гарын үсгээ зурна уу."
FORMAT_ERROR = "Гарын үсгийн зураг буруу байна."

_DATA_URL = re.compile(r"data:image/png;base64,([A-Za-z0-9+/]+={0,2})")


class SignatureError(ValueError):
    """Raised when a signature image is refused. The message is shown to the user."""


def clean_signature_data_url(data_url: str) -> bytes:
    """Return a trimmed PNG (bytes) for a signature drawn as a PNG data URL.

    Raises SignatureError with a Mongolian message when the image is unusable.
    """
    match = _DATA_URL.fullmatch(data_url) if isinstance(data_url, str) else None
    if match is None:
        raise SignatureError(FORMAT_ERROR)
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(FORMAT_ERROR) from exc
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SignatureError(FORMAT_ERROR)

    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as exc:  # any decode failure, incl. Image.DecompressionBombError (not an OSError)
        raise SignatureError(FORMAT_ERROR) from exc
    if img.format != "PNG":
        raise SignatureError(FORMAT_ERROR)
    width, height = img.size
    if max(width, height) > MAX_SIDE_PX:
        raise SignatureError(FORMAT_ERROR)
    try:
        img.load()
    except Exception as exc:  # truncated or corrupt pixel data, or a bomb-sized image
        raise SignatureError(FORMAT_ERROR) from exc

    rgba = img.convert("RGBA")
    ink = _ink_mask(rgba)
    box = ink.getbbox()
    if box is None:
        raise SignatureError(DRAW_ERROR)

    left, top, right, bottom = box
    crop_box = (
        max(left - TRIM_PAD_PX, 0),
        max(top - TRIM_PAD_PX, 0),
        min(right + TRIM_PAD_PX, width),
        min(bottom + TRIM_PAD_PX, height),
    )
    trimmed = rgba.crop(crop_box)

    if trimmed.width > MAX_WIDTH_PX:
        new_height = max(1, round(trimmed.height * MAX_WIDTH_PX / trimmed.width))
        trimmed = trimmed.resize((MAX_WIDTH_PX, new_height), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    trimmed.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _ink_mask(rgba: Image.Image) -> Image.Image:
    """Return a 0/255 mask of pixels that are visible and dark enough to be ink."""
    visible = rgba.getchannel("A").point(lambda a: 255 if a > 0 else 0)
    dark = rgba.convert("L").point(lambda v: 255 if v < INK_LUMINANCE_BELOW else 0)
    return ImageChops.multiply(visible, dark)

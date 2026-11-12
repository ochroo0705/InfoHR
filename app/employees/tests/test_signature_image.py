import base64
import io
import os
import struct
import zlib

import pytest
from PIL import Image, ImageDraw

from employees.signature_image import SignatureError, clean_signature_data_url

DRAW_ERROR = "Гарын үсгээ зурна уу."
FORMAT_ERROR = "Гарын үсгийн зураг буруу байна."


def _png_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _ink_canvas(width: int, height: int, x0: int, x1: int) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(x0, height // 2), (x1, height // 2)], fill=(0, 0, 0, 255), width=3)
    return img


def test_trims_ink_and_returns_png() -> None:
    data_url = _png_data_url(_ink_canvas(400, 150, 50, 350))

    out = clean_signature_data_url(data_url)

    result = Image.open(io.BytesIO(out))
    assert result.format == "PNG"
    assert result.size[0] <= 600
    assert result.size[0] < 400 and result.size[1] < 150


def test_downscales_wide_signature_to_600px() -> None:
    data_url = _png_data_url(_ink_canvas(1200, 300, 100, 1100))

    out = clean_signature_data_url(data_url)

    assert Image.open(io.BytesIO(out)).size[0] == 600


def test_fully_transparent_is_refused() -> None:
    data_url = _png_data_url(Image.new("RGBA", (400, 150), (0, 0, 0, 0)))

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == DRAW_ERROR


def test_opaque_white_is_refused() -> None:
    data_url = _png_data_url(Image.new("RGBA", (400, 150), (255, 255, 255, 255)))

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == DRAW_ERROR


def test_jpeg_data_url_is_refused() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (0, 0, 0)).save(buf, format="JPEG")
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == FORMAT_ERROR


@pytest.mark.parametrize(
    "bad_value",
    [
        "hello, not a data url",
        "data:image/png;base64,!!!not-base64!!!",
    ],
)
def test_non_data_url_or_bad_base64_is_refused(bad_value: str) -> None:
    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(bad_value)
    assert str(exc.value) == FORMAT_ERROR


def test_png_over_300_kb_is_refused() -> None:
    noise = Image.frombytes("RGB", (500, 500), os.urandom(500 * 500 * 3))
    data_url = _png_data_url(noise)
    assert len(base64.b64decode(data_url.split(",", 1)[1])) > 300 * 1024

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == FORMAT_ERROR


def _header_only_png_data_url(width: int, height: int) -> str:
    """A PNG that is only the signature and an IHDR chunk, declaring the given size and no pixel data."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    crc = zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF
    raw = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", crc)
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


@pytest.mark.parametrize("side", [1500, 20000, 60000])
def test_header_only_png_with_declared_size_is_refused(side: int) -> None:
    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(_header_only_png_data_url(side, side))
    assert str(exc.value) == FORMAT_ERROR


def test_trailing_newline_after_valid_data_url_is_refused() -> None:
    data_url = _png_data_url(_ink_canvas(400, 150, 50, 350)) + "\n"

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == FORMAT_ERROR


def test_side_longer_than_1600_px_is_refused() -> None:
    data_url = _png_data_url(_ink_canvas(1601, 40, 10, 1500))

    with pytest.raises(SignatureError) as exc:
        clean_signature_data_url(data_url)
    assert str(exc.value) == FORMAT_ERROR

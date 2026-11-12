"""Stamping the on-screen signature into the order PDF: the picture, the signer's name and the time go where the
`{{signature}}` line is; the unsigned PDF is unchanged."""

import datetime
import io
import re
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.core.files.base import ContentFile
from django.test import Client
from docx import Document
from fpdf import FPDF
from fpdf.enums import MethodReturnValue
from PIL import Image

from employees.models import Employee, HrOrder, OrderTemplate
from employees.services import order_docs
from employees.services.order_docs import SIGNATURE_TOKEN, SignatureStamp
from employees.tests.test_views import login_as

from .test_order_docs import _need_pdf_font, hire_order
from .test_order_sign_views import _registered_transfer

pytestmark = pytest.mark.django_db

SIGNED_AT = datetime.datetime(2026, 11, 9, 6, 30, tzinfo=datetime.UTC)  # 14:30 in Ulaanbaatar
SIGNED_TEXT = "2026-11-09 14:30"  # the time line under the signature


def _png(width: int = 300, height: int = 100) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (20, 20, 20, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


STAMP = SignatureStamp(image=_png(), name="Б. Дорж", signed_at=SIGNED_AT)


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any, dict[str, Any]]]:
    """Every FPDF.image, FPDF.cell and FPDF.multi_cell call in order: (method, text or None, keyword arguments)."""
    calls: list[tuple[str, Any, dict[str, Any]]] = []
    dry: list[int] = [0]  # > 0 while a dry run (line count only) is running; its inner calls draw nothing
    for method in ("image", "cell", "multi_cell"):
        original: Callable[..., Any] = getattr(FPDF, method)

        def spy(self: FPDF, *args: Any, _method: str = method, _original: Any = original, **kwargs: Any) -> Any:
            text = None if _method == "image" else args[2] if len(args) > 2 else kwargs.get("text")
            if not dry[0] and not kwargs.get("dry_run"):
                calls.append((_method, text, kwargs))
            dry[0] += bool(kwargs.get("dry_run"))
            try:
                return _original(self, *args, **kwargs)
            finally:
                dry[0] -= bool(kwargs.get("dry_run"))

        monkeypatch.setattr(FPDF, method, spy)
    return calls


def _texts(log: list[tuple[str, Any, dict[str, Any]]], method: str) -> list[str]:
    return [text for name, text, _kwargs in log if name == method]


def _pages(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", data))


def _signed_word(order: HrOrder, user: User) -> Document:
    return Document(io.BytesIO(order_docs.render_order(order, user, signature=SIGNATURE_TOKEN)))


def test_starter_marker_draws_the_picture_then_the_director_line_then_the_time(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    word = _signed_word(hire_order(hired), actor)
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert [name for name, _text, _kwargs in log if name == "image"] == ["image"]
    line = next(
        p.text.replace(order_docs.SIGNATURE_TOKEN, "").strip()
        for p in word.paragraphs
        if order_docs.SIGNATURE_TOKEN in p.text
    )
    assert line.startswith("/") and line.endswith("/")  # the director's name line, marker taken out
    assert not any(order_docs.SIGNATURE_TOKEN in (text or "") for _name, text, _kwargs in log)
    names = [name for name, _text, _kwargs in log]
    texts = [text for _name, text, _kwargs in log]
    assert names.index("image") < texts.index(line) < texts.index(SIGNED_TEXT)
    assert "Б. Дорж" not in _texts(log, "cell")  # the paragraph already shows the director; the name is not drawn


def test_text_beside_the_marker_is_drawn_after_the_picture_and_before_the_time(
    actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    word = Document()
    word.add_paragraph("Захирал " + SIGNATURE_TOKEN)
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert "Захирал" in _texts(log, "multi_cell")
    assert not any(order_docs.SIGNATURE_TOKEN in (text or "") for _name, text, _kwargs in log)
    names = [name for name, _text, _kwargs in log]
    assert names.count("image") == 1
    texts = [text for _name, text, _kwargs in log]
    assert names.index("image") < texts.index("Захирал") < texts.index(SIGNED_TEXT)
    assert "Б. Дорж" not in _texts(log, "cell")


def test_naive_signing_time_is_shown_as_it_is(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    _need_pdf_font()
    stamp = SignatureStamp(image=_png(), name="Б. Дорж", signed_at=datetime.datetime(2026, 11, 9, 14, 30))
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    order_docs._draw_signature(pdf, stamp)
    assert SIGNED_TEXT in _texts(log, "cell")


def test_marker_twice_draws_one_picture(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    word = _signed_word(hire_order(hired), actor)
    word.add_paragraph(SIGNATURE_TOKEN)
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert [name for name, _text, _kwargs in log if name == "image"] == ["image"]
    assert not any(order_docs.SIGNATURE_TOKEN in (text or "") for _name, text, _kwargs in log)


def test_no_marker_draws_the_picture_after_the_last_paragraph(
    log: list[tuple[str, Any, dict[str, Any]]],
) -> None:
    _need_pdf_font()
    word = Document()
    word.add_paragraph("Тушаал")
    word.add_paragraph("Сүүлчийн мөр")
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    names = [name for name, _text, _kwargs in log]
    assert names.count("image") == 1
    last_text = max(i for i, (name, text, _k) in enumerate(log) if name == "multi_cell" and text == "Сүүлчийн мөр")
    assert last_text < names.index("image")


def test_picture_is_40_mm_wide(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    _need_pdf_font()
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    order_docs._draw_signature(pdf, STAMP)
    ((_name, _text, kwargs),) = [entry for entry in log if entry[0] == "image"]
    assert kwargs["w"] == 40


def test_signature_block_moves_to_the_next_page_when_it_does_not_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    _need_pdf_font()
    pages_at_image: list[int] = []
    original = FPDF.image

    def spy(self: FPDF, *args: Any, **kwargs: Any) -> Any:
        pages_at_image.append(self.page)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FPDF, "image", spy)
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    pdf.set_y(270)
    order_docs._draw_signature(pdf, STAMP)
    assert pdf.page == 2 and pages_at_image == [2]


def test_unsigned_pdf_draws_no_picture_and_keeps_the_blank_line(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    data = order_docs.render_pdf(hire_order(hired), actor)
    assert data.startswith(b"%PDF-")
    assert not any(name == "image" for name, _text, _kwargs in log)
    assert any(text.startswith(order_docs.BLANK_SIGNATURE + " /") for text in _texts(log, "multi_cell"))


def test_render_signed_pdf_is_one_page_with_the_stamp_once(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    data = order_docs.render_signed_pdf(hire_order(hired), actor, STAMP)
    assert data.startswith(b"%PDF-") and _pages(data) == 1
    assert [name for name, _text, _kwargs in log if name == "image"] == ["image"]
    assert SIGNED_TEXT in _texts(log, "cell")
    assert "Б. Дорж" not in _texts(log, "cell")


def test_a_very_tall_picture_is_capped_at_25_mm_high(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    _need_pdf_font()
    stamp = SignatureStamp(image=_png(9, 1600), name="Б. Дорж", signed_at=SIGNED_AT)
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    order_docs._draw_signature(pdf, stamp)
    ((_name, _text, kwargs),) = [entry for entry in log if entry[0] == "image"]
    assert kwargs["h"] == 25
    assert kwargs["w"] == pytest.approx(25 * 9 / 1600)  # the width shrinks with the height, the aspect is kept


def test_a_wide_picture_is_still_40_mm_wide(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    _need_pdf_font()
    stamp = SignatureStamp(image=_png(600, 200), name="Б. Дорж", signed_at=SIGNED_AT)
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    order_docs._draw_signature(pdf, stamp)
    ((_name, _text, kwargs),) = [entry for entry in log if entry[0] == "image"]
    assert kwargs["w"] == 40
    assert kwargs["h"] == pytest.approx(40 / 3)


def test_bulk_print_draws_a_blank_line_per_order_and_no_picture(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    first = _registered_transfer(hired, actor, number="41", day=datetime.date(2026, 3, 1))
    second = _registered_transfer(hired, actor, number="42", day=datetime.date(2026, 3, 2))
    client = Client()
    login_as(client, "HR", "hr_bulk_print")
    response = client.post("/employees/orders/print/selected/", {"ids": [first.pk, second.pk]})
    assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF-")
    assert not any(name == "image" for name, _text, _kwargs in log)
    assert sum(text.startswith(order_docs.BLANK_SIGNATURE + " /") for text in _texts(log, "multi_cell")) == 2


def test_bulk_print_still_raises_for_a_corrupt_template_zip(hired: Employee, actor: User) -> None:
    """Pins the pre-wave behaviour: a corrupt .docx is not an OrderDocError in the shared filler (_render), so bulk
    print lets the zip error through instead of skipping the order."""
    order = hire_order(hired)
    OrderTemplate.objects.create(order_type=int(order.order_type)).file.save(
        "broken.docx", ContentFile(b"not a zip"), save=True
    )
    with pytest.raises(zipfile.BadZipFile):
        order_docs._render(io.BytesIO(b"not a zip"), {})
    with pytest.raises(zipfile.BadZipFile):
        order_docs.render_pdf_many([order], actor)


def test_token_only_marker_draws_picture_name_and_time(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    """A custom template whose marker paragraph is only the marker: the old picture, name and time block."""
    _need_pdf_font()
    word = Document()
    word.add_paragraph(SIGNATURE_TOKEN)
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert [name for name, _text, _kwargs in log if name == "image"] == ["image"]
    assert "Б. Дорж" in _texts(log, "cell") and SIGNED_TEXT in _texts(log, "cell")


def test_no_marker_fallback_draws_picture_name_and_time_after_the_text(
    log: list[tuple[str, Any, dict[str, Any]]],
) -> None:
    _need_pdf_font()
    word = Document()
    word.add_paragraph("Тушаал")
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert "Б. Дорж" in _texts(log, "cell") and SIGNED_TEXT in _texts(log, "cell")
    names = [name for name, _text, _kwargs in log]
    assert names.index("multi_cell") < names.index("image")


def test_starter_block_moves_to_the_next_page_together(
    hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Picture, director line and time move to the next page as one block when they do not fit."""
    _need_pdf_font()
    pages: dict[str, list[int]] = {"image": [], "multi_cell": [], "cell": []}
    dry: list[int] = [0]
    for method in pages:
        original = getattr(FPDF, method)

        def spy(self: FPDF, *args: Any, _method: str = method, _original: Any = original, **kwargs: Any) -> Any:
            if not dry[0] and not kwargs.get("dry_run"):
                pages[_method].append(self.page)
            dry[0] += bool(kwargs.get("dry_run"))
            try:
                return _original(self, *args, **kwargs)
            finally:
                dry[0] -= bool(kwargs.get("dry_run"))

        monkeypatch.setattr(FPDF, method, spy)
    word = _signed_word(hire_order(hired), actor)
    pdf = order_docs._new_pdf(word)
    pdf.add_page()
    pdf.set_y(262)
    marker = next(p for p in word.paragraphs if order_docs.SIGNATURE_TOKEN in p.text)
    order_docs._draw_signature_on_line(
        pdf, STAMP, marker, 11.0, marker.text.replace(order_docs.SIGNATURE_TOKEN, "").strip()
    )
    assert pages["image"] == [2] and pages["multi_cell"] == [2] and pages["cell"] == [2]


def test_signed_starter_order_draws_one_picture_then_the_director_line_then_the_time(
    hired: Employee, actor: User, log: list[tuple[str, Any, dict[str, Any]]]
) -> None:
    _need_pdf_font()
    order = _registered_transfer(hired, actor, number="51")
    data = order_docs.render_signed_pdf(order, actor, STAMP)
    assert data.startswith(b"%PDF-") and _pages(data) == 1
    assert [name for name, _text, _kwargs in log if name == "image"] == ["image"]
    filled = [p.text for p in _signed_word(order, actor).paragraphs if order_docs.SIGNATURE_TOKEN in p.text]
    line = filled[0].replace(order_docs.SIGNATURE_TOKEN, "").strip()
    names = [name for name, _text, _kwargs in log]
    texts = [text for _name, text, _kwargs in log]
    assert names.index("image") < texts.index(line) < texts.index(SIGNED_TEXT)
    assert "Б. Дорж" not in _texts(log, "cell")


def test_director_line_block_is_never_split_at_the_page_foot(
    hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window just above the page-break trigger, where the picture, the director line and the time line used to
    split: the time line went alone to the next page. All three must share one page."""
    _need_pdf_font()
    pages: dict[str, list[int]] = {"image": [], "multi_cell": [], "cell": []}
    dry: list[int] = [0]
    for method in pages:
        original = getattr(FPDF, method)

        def spy(self: FPDF, *args: Any, _method: str = method, _original: Any = original, **kwargs: Any) -> Any:
            if not dry[0] and not kwargs.get("dry_run"):
                pages[_method].append(self.page)
            dry[0] += bool(kwargs.get("dry_run"))
            try:
                return _original(self, *args, **kwargs)
            finally:
                dry[0] -= bool(kwargs.get("dry_run"))

        monkeypatch.setattr(FPDF, method, spy)
    word = _signed_word(hire_order(hired), actor)
    marker = next(p for p in word.paragraphs if order_docs.SIGNATURE_TOKEN in p.text)
    text = marker.text.replace(order_docs.SIGNATURE_TOKEN, "").strip()
    pdf = order_docs._new_pdf(word)
    pdf.add_page()
    width, height = order_docs._signature_size(STAMP)
    style, points = order_docs._run_font(marker, 11.0)
    pdf.set_font("Order", style, points)
    line_height = points * order_docs.PT_MM * 1.25
    lines = len(pdf.multi_cell(0, line_height, text, dry_run=True, output=MethodReturnValue.LINES))
    without_gaps = height + lines * line_height + order_docs.SIGNATURE_LINE_MM  # the block as it was counted before
    pdf.set_y(pdf.page_break_trigger - without_gaps - 0.75)  # inside (trigger - 1.5, trigger] for the old count
    pages = {name: [] for name in pages}
    order_docs._draw_signature_on_line(pdf, STAMP, marker, 11.0, text)
    assert pages["image"] and pages["multi_cell"] and pages["cell"]
    assert set(pages["image"] + pages["multi_cell"] + pages["cell"]) == {2}


def test_a_later_marker_keeps_its_text_and_gets_no_picture(log: list[tuple[str, Any, dict[str, Any]]]) -> None:
    _need_pdf_font()
    word = Document()
    word.add_paragraph("Захирал " + SIGNATURE_TOKEN)
    word.add_paragraph("Хянасан " + SIGNATURE_TOKEN)
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, STAMP)
    assert names_of(log).count("image") == 1
    assert "Хянасан" in _texts(log, "multi_cell")
    texts = [text for _name, text, _kwargs in log]
    assert names_of(log).index("image") < texts.index("Хянасан")
    assert not any(order_docs.SIGNATURE_TOKEN in (text or "") for _name, text, _kwargs in log)


def names_of(log: list[tuple[str, Any, dict[str, Any]]]) -> list[str]:
    return [name for name, _text, _kwargs in log]

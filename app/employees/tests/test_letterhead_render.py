"""The company letterhead on printed HR orders: the logo and text lines drawn at the top of the first page (or of every
page), the per-template switch, the batch cache, the fallbacks for a missing or broken logo, and issued orders."""

import datetime
import io
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import Client
from docx import Document
from fpdf import FPDF
from fpdf.errors import FPDFException
from PIL import Image

from employees.models import CompanySettings, Employee, HrOrder, OrderState, OrderTemplate, OrderType
from employees.services import order_docs
from employees.services.order_docs import SignatureStamp
from employees.tests.test_views import login_as

from .test_order_docs import _need_pdf_font, hire_order

pytestmark = pytest.mark.django_db

Call = tuple[str, Any, dict[str, Any]]  # (method, text or None, keyword arguments)


@pytest.fixture(autouse=True)
def private_files(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path


@pytest.fixture(autouse=True)
def pdf_font() -> None:
    _need_pdf_font()


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


@pytest.fixture
def hr_with_salary(client: Client) -> Client:
    """HR with the salary right: a hire order's scan is only shown to users who may see salaries (OQ-080)."""
    user = login_as(client, "HR", "hr1")
    user.user_permissions.add(Permission.objects.get(codename="view_salary", content_type__app_label="macs"))
    return client


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    """Every FPDF.image, multi_cell, cell and line call in order (dry runs that draw nothing are not recorded)."""
    calls: list[Call] = []
    for method in ("image", "multi_cell", "cell", "line"):
        original: Callable[..., Any] = getattr(FPDF, method)

        def spy(self: FPDF, *args: Any, _method: str = method, _original: Any = original, **kwargs: Any) -> Any:
            if not kwargs.get("dry_run"):
                text = None if _method in ("image", "line") else args[2] if len(args) > 2 else kwargs.get("text")
                calls.append((_method, text, kwargs))
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(FPDF, method, spy)
    return calls


def images(calls: list[Call]) -> list[Call]:
    return [call for call in calls if call[0] == "image"]


def texts(calls: list[Call], method: str = "multi_cell") -> list[Any]:
    return [text for name, text, _kwargs in calls if name == method]


def pages(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", data))


def png(width: int = 300, height: int = 100) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (20, 20, 20, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


STAMP = SignatureStamp(
    image=png(), name="Б. Дорж", signed_at=datetime.datetime(2026, 11, 9, 6, 30, tzinfo=datetime.UTC)
)


def set_company(**fields: Any) -> None:
    defaults = {
        "name": "Жишээ ХХК",
        "director_name": "Б. Дорж",
        "letterhead_lines": "Хаяг: Улаанбаатар\n{company_name}",
    }
    CompanySettings.objects.update_or_create(pk=1, defaults={**defaults, **fields})


def store_logo(data: bytes) -> None:
    CompanySettings.get().letterhead_logo.save("logo.png", ContentFile(data), save=True)


def upload(order_type: OrderType, data: bytes) -> None:
    row, _ = OrderTemplate.objects.get_or_create(order_type=order_type.value)
    row.file.save("mine.docx", ContentFile(data))


def _docx(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def long_template(paragraphs: int = 70) -> bytes:
    return _docx(*(f"Энэ бол урт текстийн мөр {index}." for index in range(paragraphs)))


def test_logo_drawn_when_on_and_absent_when_template_flag_off(hired: Employee, actor: User, drawn: list[Call]) -> None:
    store_logo(png())
    set_company()
    order = hire_order(hired)  # the bundled starter has no row: the letterhead is on
    order_docs.render_pdf(order, actor)
    assert len(images(drawn)) == 1
    upload(OrderType.HIRED, _docx("Манай загвар"))
    drawn.clear()
    order_docs.render_pdf(order, actor)
    assert len(images(drawn)) == 1  # uploaded, flag on by default
    OrderTemplate.objects.filter(order_type=OrderType.HIRED).update(show_letterhead=False)
    drawn.clear()
    order_docs.render_pdf(order, actor)
    assert images(drawn) == []
    assert "Жишээ ХХК" not in texts(drawn)  # the text lines go with the logo


def test_text_only_when_no_logo_file(hired: Employee, actor: User, drawn: list[Call]) -> None:
    set_company(letterhead_lines="Хаяг: Улаанбаатар\n{company_name}")
    data = order_docs.render_pdf(hire_order(hired), actor)
    assert data.startswith(b"%PDF-")
    assert images(drawn) == []
    assert "Хаяг: Улаанбаатар" in texts(drawn)
    assert "Жишээ ХХК" in texts(drawn)  # {company_name} is filled in


def test_first_page_only_by_default(hired: Employee, actor: User, drawn: list[Call]) -> None:
    store_logo(png())
    set_company()
    upload(OrderType.HIRED, long_template())
    data = order_docs.render_pdf(hire_order(hired), actor)
    assert pages(data) >= 2
    assert len(images(drawn)) == 1


def test_every_page_repeats_the_letterhead(hired: Employee, actor: User, drawn: list[Call]) -> None:
    store_logo(png())
    set_company(letterhead_every_page=True)
    upload(OrderType.HIRED, long_template())
    data = order_docs.render_pdf(hire_order(hired), actor)
    assert pages(data) >= 2
    assert len(images(drawn)) == pages(data)


def test_logo_only_draws_no_text_lines(hired: Employee, actor: User, drawn: list[Call]) -> None:
    store_logo(png())
    set_company(letterhead_logo_place="logo_only", letterhead_lines="Тест хаяг мөр")
    order_docs.render_pdf(hire_order(hired), actor)
    assert len(images(drawn)) == 1
    assert "Тест хаяг мөр" not in texts(drawn)


def test_corrupt_logo_does_not_break_printing(
    hired: Employee, actor: User, drawn: list[Call], caplog: pytest.LogCaptureFixture
) -> None:
    store_logo(b"junk")
    set_company()
    with caplog.at_level(logging.WARNING, logger="employees.services.order_docs"):
        data = order_docs.render_pdf(hire_order(hired), actor)
    assert data.startswith(b"%PDF-")
    assert images(drawn) == []
    assert "Жишээ ХХК" in texts(drawn)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.parametrize(("width", "height"), [(1, 1), (4000, 20), (20, 4000)])
def test_extreme_shapes_do_not_fail(hired: Employee, actor: User, drawn: list[Call], width: int, height: int) -> None:
    store_logo(png(width, height))
    set_company()
    data = order_docs.render_pdf(hire_order(hired), actor)
    assert data.startswith(b"%PDF-")
    (logo,) = images(drawn)
    assert logo[2]["h"] <= order_docs.LETTERHEAD_MAX_HEIGHT_MM + 1e-6
    assert logo[2]["w"] > 0


@pytest.mark.parametrize("place", ["left", "right", "top"])
def test_logo_sits_where_the_preset_says(hired: Employee, actor: User, drawn: list[Call], place: str) -> None:
    store_logo(png(300, 100))
    set_company(letterhead_logo_place=place, letterhead_logo_size="medium")
    word = Document(io.BytesIO(order_docs.render_order(hire_order(hired), actor)))
    pdf = order_docs._new_pdf(word)
    order_docs._draw_order(pdf, word, order_type=OrderType.HIRED)
    (logo,) = images(drawn)
    assert logo[2]["w"] == pytest.approx(30)
    assert logo[2]["h"] == pytest.approx(10)
    if place == "left":
        assert logo[2]["x"] == pytest.approx(pdf.l_margin)
    elif place == "right":
        assert logo[2]["x"] + logo[2]["w"] == pytest.approx(pdf.w - pdf.r_margin)
    else:
        assert logo[2]["x"] == pytest.approx((pdf.w - logo[2]["w"]) / 2)


def test_logo_fpdf_cannot_embed_falls_back_to_text_only(
    hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Pillow opens the file but fpdf2 refuses to embed it: the order is still printed, with the text lines at the
    left margin (the text-only layout), not beside an empty space where the logo should be."""
    store_logo(png())
    set_company(letterhead_logo_place="left", letterhead_lines="Тест хаяг")

    def refuse(self: FPDF, *args: Any, **kwargs: Any) -> None:
        raise FPDFException("cannot embed this picture")

    monkeypatch.setattr(FPDF, "image", refuse)
    placed: list[tuple[str, float]] = []
    original = FPDF.multi_cell

    def spy(self: FPDF, *args: Any, **kwargs: Any) -> Any:
        if not kwargs.get("dry_run") and len(args) > 2:
            placed.append((args[2], self.x))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FPDF, "multi_cell", spy)
    word = Document(io.BytesIO(order_docs.render_order(hire_order(hired), actor)))
    pdf = order_docs._new_pdf(word)
    with caplog.at_level(logging.WARNING, logger="employees.services.order_docs"):
        order_docs._draw_order(pdf, word, order_type=OrderType.HIRED)
    assert bytes(pdf.output()).startswith(b"%PDF-")
    assert ("Тест хаяг", pdf.l_margin) in placed  # text-only: starts at the left margin
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_first_text_line_is_bold(hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    store_logo(png())
    set_company(letterhead_lines="Эхний мөр\nДараагийн мөр")
    fonts: list[tuple[str, float]] = []
    original = FPDF.set_font

    def spy(self: FPDF, family: Any = None, style: str = "", size: float = 0, **kwargs: Any) -> Any:
        if family == "Order":
            fonts.append((style, size))
        return original(self, family, style, size, **kwargs)

    monkeypatch.setattr(FPDF, "set_font", spy)
    order_docs.render_pdf(hire_order(hired), actor)
    assert fonts.index(("B", 12)) < fonts.index(("", 9))  # first line bold and larger, the rest regular and smaller


def test_signed_pdf_also_has_the_letterhead(hired: Employee, actor: User, drawn: list[Call]) -> None:
    store_logo(png())
    set_company()
    data = order_docs.render_signed_pdf(hire_order(hired), actor, STAMP)
    assert data.startswith(b"%PDF-")
    assert len(images(drawn)) == 2  # the letterhead logo and the signature picture


def test_batch_reads_the_logo_file_once(
    hired: Employee, actor: User, drawn: list[Call], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_logo(png())
    set_company()
    reads: list[int] = []
    original = order_docs._read_logo

    def counting(settings_row: CompanySettings) -> bytes | None:
        reads.append(1)
        return original(settings_row)

    monkeypatch.setattr(order_docs, "_read_logo", counting)
    data, printed = order_docs.render_pdf_many([hire_order(hired)] * 50, actor)
    assert len(printed) == 50 and data.startswith(b"%PDF-")
    assert len(reads) == 1
    assert len(images(drawn)) == 50


def test_issued_order_with_stored_file_is_not_rerendered(hr_with_salary: Client, hired: Employee) -> None:
    """A signed order serves the file stored at signing (HrOrder.file), byte for byte, after the letterhead is on."""
    order = hire_order(hired)
    stored = b"%PDF-1.4 the signed scan, stored at signing"
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    order.refresh_from_db()
    order.file.save("signed.pdf", ContentFile(stored), save=True)
    store_logo(png())
    set_company(letterhead_every_page=True)
    response = hr_with_salary.get(f"/employees/{hired.pk}/order/{order.pk}/file/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == stored  # type: ignore[attr-defined]


@pytest.mark.xfail(
    strict=True,
    reason="Known gap: the order PDF download re-renders signed orders from the current template and letterhead",
)
def test_issued_order_pdf_download_is_not_rerendered(hr_with_salary: Client, hired: Employee) -> None:
    order = hire_order(hired)
    stored = b"%PDF-1.4 the signed scan, stored at signing"
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    order.refresh_from_db()
    order.file.save("signed.pdf", ContentFile(stored), save=True)
    store_logo(png())
    set_company()
    response = hr_with_salary.get(f"/employees/{hired.pk}/order/{order.pk}/document/pdf/")
    assert b"".join(response.streaming_content) == stored  # type: ignore[attr-defined]


LONG_LINES = "\n".join(f"Урт бланкны мөр {index} " + "ж" * 110 for index in range(60))


def test_sixty_long_letterhead_lines_do_not_crash_the_print(hired: Employee, actor: User) -> None:
    set_company(letterhead_lines=LONG_LINES, letterhead_every_page=True)
    upload(OrderType.HIRED, long_template())
    order = hire_order(hired)

    data, used = order_docs.render_pdf_many([order], actor)  # bypasses the form: the model has no cap
    signed = order_docs.render_signed_pdf(order, actor, STAMP)

    assert data.startswith(b"%PDF-") and signed.startswith(b"%PDF-")
    assert pages(data) >= 2 and pages(signed) >= 2
    assert used == [order]


def test_a_long_letterhead_is_clipped_to_40_percent_of_the_page(
    hired: Employee, actor: User, drawn: list[Call]
) -> None:
    set_company(letterhead_lines=LONG_LINES)
    order_docs.render_pdf(hire_order(hired), actor)
    drawn_lines = [text for text in texts(drawn) if isinstance(text, str) and "Урт бланкны мөр" in text]

    assert 0 < len(drawn_lines) < 60  # the lines that fit under 40% of the page height are drawn, the rest are not


def test_auto_page_break_is_off_while_the_letterhead_is_drawn_and_restored_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_company()
    pdf = order_docs._new_pdf(Document())
    pdf.add_page()
    seen: list[bool] = []
    original: Callable[..., Any] = FPDF.multi_cell

    def spy(self: FPDF, *args: Any, **kwargs: Any) -> Any:
        if not kwargs.get("dry_run"):
            seen.append(bool(self.auto_page_break))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FPDF, "multi_cell", spy)
    before = (pdf.auto_page_break, pdf.b_margin)
    order_docs._draw_letterhead(pdf, CompanySettings.get(), None)

    assert seen and not any(seen)
    assert (pdf.auto_page_break, pdf.b_margin) == before


def test_an_over_limit_logo_is_skipped_without_decoding_it(
    hired: Employee,
    actor: User,
    drawn: list[Call],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (6000, 5000), "red").save(buffer, "PNG")
    store_logo(buffer.getvalue())
    set_company()
    decoded: list[tuple[int, int]] = []  # the pictures the renderer decodes (saving the fixture above decodes it too)
    original_load = Image.Image.load

    def spy_load(self: Image.Image) -> Any:
        decoded.append(self.size)
        return original_load(self)

    monkeypatch.setattr(Image.Image, "load", spy_load)
    with caplog.at_level(logging.WARNING, logger="employees.services.order_docs"):
        data = order_docs.render_pdf(hire_order(hired), actor)

    assert data.startswith(b"%PDF-")  # the order is printed
    assert images(drawn) == []
    assert "Жишээ ХХК" in texts(drawn)  # the text lines are still drawn
    assert (6000, 5000) not in decoded
    assert "not a readable picture" in caplog.text

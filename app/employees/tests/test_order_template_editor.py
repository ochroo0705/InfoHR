"""The in-page template editor's document <-> .docx converter (no database, no views)."""

import io
from typing import Any

import pytest
from docx import Document

from employees.models import OrderType
from employees.services import order_docs, order_template_editor
from employees.services.order_template_editor import doc_to_docx, docx_to_doc, validate_doc

HIRED = OrderType.HIRED
FIRED = OrderType.FIRED


def para(
    parts: list[dict[str, Any]],
    align: str = "left",
    bold: bool = False,
    italic: bool = False,
    size: float | None = None,
    show_if: str | None = None,
    numbered: bool = False,
) -> dict[str, Any]:
    return {
        "align": align,
        "bold": bold,
        "italic": italic,
        "size": size,
        "show_if": show_if,
        "numbered": numbered,
        "parts": parts,
    }


def raw_docx(build: Any) -> bytes:
    document = Document()
    build(document)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def test_round_trip_keeps_paragraph_formatting_and_chips() -> None:
    doc = {
        "paragraphs": [
            para([{"text": "ТУШААЛ № "}, {"field": "order_number"}], align="center", bold=True, size=14),
            para([{"field": "employee_full_name"}, {"text": " ажилд орсон."}], align="justify"),
            para([]),
        ]
    }

    assert docx_to_doc(doc_to_docx(doc, HIRED), HIRED) == doc


def test_round_trip_keeps_mongolian_text_blank_paragraphs_and_spaces() -> None:
    doc = {
        "paragraphs": [
            para([{"text": "  Монгол текст  "}]),
            para([]),
        ]
    }

    assert docx_to_doc(doc_to_docx(doc, HIRED), HIRED) == doc


@pytest.mark.parametrize("order_type", list(OrderType))
def test_doc_to_docx_output_passes_check_template(order_type: OrderType) -> None:
    doc = {
        "paragraphs": [
            para([{"text": "Тушаал № "}, {"field": "order_number"}], align="center", bold=True, size=14),
            para([{"field": "employee_full_name"}, {"text": " /"}, {"field": "employee_number"}, {"text": "/"}]),
        ]
    }

    assert order_docs.check_template(doc_to_docx(doc, order_type)) == []


@pytest.mark.parametrize("order_type", [t for t in OrderType if t != HIRED])
def test_every_bundled_starter_opens_in_the_editor(order_type: OrderType) -> None:
    data = order_docs.starter_path(order_type).read_bytes()

    assert docx_to_doc(data, order_type) is not None


def test_hired_starter_opens_in_the_editor_with_its_conditions_and_numbering() -> None:
    doc = docx_to_doc(order_docs.starter_path(HIRED).read_bytes(), HIRED)

    assert doc is not None
    conditional = [p for p in doc["paragraphs"] if p["show_if"]]
    assert [p["show_if"] for p in conditional] == ["probation_end", "salary"]
    assert all(p["numbered"] for p in conditional)
    assert sum(1 for p in doc["paragraphs"] if p["numbered"]) == 5
    # the counter prefix is not part of the text the editor shows
    assert not any("item_no" in _all_text(p) for p in doc["paragraphs"])
    assert docx_to_doc(doc_to_docx(doc, HIRED), HIRED) == doc


def _all_text(paragraph: dict[str, Any]) -> str:
    return "".join(part.get("text", "") for part in paragraph["parts"])


def _rendered_lines(data: bytes, probation_end: str, salary: str) -> list[str]:
    context = {name: f"[{name}]" for name in order_docs.PLACEHOLDERS}
    context.update(probation_end=probation_end, salary=salary)
    filled = Document(io.BytesIO(order_docs._render(io.BytesIO(data), context)))  # noqa: SLF001
    return [p.text for p in filled.paragraphs]


@pytest.mark.parametrize(
    ("probation_end", "salary"), [("", ""), ("", "1 000 000"), ("2026-12-01", ""), ("2026-12-01", "9")]
)
def test_hired_starter_prints_numbers_without_gaps(probation_end: str, salary: str) -> None:
    lines = _rendered_lines(order_docs.starter_path(HIRED).read_bytes(), probation_end, salary)

    numbered = [line for line in lines if line[:2] in {f"{n}." for n in range(1, 10)}]
    assert [line[:2] for line in numbered] == [f"{n}." for n in range(1, len(numbered) + 1)]
    assert len(numbered) == 3 + bool(probation_end) + bool(salary)
    assert any("сорилтын хугацаа" in line for line in lines) is bool(probation_end)
    assert any("Ажилтны цалин" in line for line in lines) is bool(salary)
    assert numbered[-1].startswith(f"{len(numbered)}. Хүний нөөцийн алба")
    assert not any("{%" in line or "item_no" in line for line in lines)


def test_conditional_numbered_paragraph_round_trips_and_renders() -> None:
    doc = {
        "paragraphs": [
            para([{"text": "Цалин "}, {"field": "salary"}], show_if="salary", numbered=True, bold=True, size=12),
            para([{"text": "Төгсгөл"}], numbered=True),
        ]
    }

    data = doc_to_docx(doc, HIRED)

    assert validate_doc(doc, HIRED) == []
    assert docx_to_doc(data, HIRED) == doc
    assert _rendered_lines(data, "", "") == ["1. Төгсгөл"]
    assert _rendered_lines(data, "", "7") == ["1. Цалин 7", "2. Төгсгөл"]


@pytest.mark.parametrize(
    "build",
    [
        lambda d: (
            d.add_paragraph("{%p if salary %}"),
            d.add_paragraph("a"),
            d.add_paragraph("b"),
            d.add_paragraph("{%p endif %}"),
        ),
        lambda d: (
            d.add_paragraph("{%p if salary %}"),
            d.add_paragraph("{%p if probation_end %}"),
            d.add_paragraph("a"),
        ),
        lambda d: d.add_paragraph("{%p endif %}"),
        lambda d: (d.add_paragraph("{%p if salary %}"), d.add_paragraph("a")),
        lambda d: (d.add_paragraph("{%p if nope %}"), d.add_paragraph("a"), d.add_paragraph("{%p endif %}")),
        lambda d: d.add_paragraph(order_template_editor.COUNTER_STEP + "no counter start"),
    ],
)
def test_conditions_the_editor_cannot_show_stay_read_only(build: Any) -> None:
    assert docx_to_doc(raw_docx(build), HIRED) is None


def test_validate_refuses_bad_show_if_and_numbered() -> None:
    bad_field = validate_doc({"paragraphs": [para([{"text": "a"}], show_if="nope")]}, HIRED)
    bad_flag = validate_doc({"paragraphs": [{**para([{"text": "a"}]), "numbered": "yes"}]}, HIRED)

    assert bad_field and bad_flag


def test_a_paragraph_without_the_new_keys_still_validates_and_saves() -> None:
    old_style = {"align": "left", "bold": False, "italic": False, "size": None, "parts": [{"text": "a"}]}

    assert validate_doc({"paragraphs": [old_style]}, HIRED) == []


def test_docx_with_a_table_is_not_editable() -> None:
    def build(document: Any) -> None:
        document.add_paragraph("Текст")
        document.add_table(rows=1, cols=1)

    assert docx_to_doc(raw_docx(build), HIRED) is None


def test_docx_with_if_tag_is_not_editable() -> None:
    data = raw_docx(lambda document: document.add_paragraph("{% if salary %}Цалин{% endif %}"))

    assert docx_to_doc(data, HIRED) is None


def test_docx_with_two_text_styles_in_one_paragraph_is_not_editable() -> None:
    def build(document: Any) -> None:
        paragraph = document.add_paragraph()
        paragraph.add_run("Тушаах").bold = True
        paragraph.add_run(" энгийн текст")

    assert docx_to_doc(raw_docx(build), HIRED) is None


def test_field_valid_but_not_for_this_type_is_kept_as_a_field_part() -> None:
    data = raw_docx(lambda document: document.add_paragraph("Цалин: {{ salary }}"))

    doc = docx_to_doc(data, FIRED)

    assert doc is not None
    assert doc["paragraphs"][0]["parts"] == [{"text": "Цалин: "}, {"field": "salary"}]


def test_validate_doc_refuses_unknown_field_and_bad_shape() -> None:
    unknown = validate_doc({"paragraphs": [para([{"field": "nope"}])]}, HIRED)
    bad_shape = validate_doc({"paragraphs": "x"}, HIRED)
    bad_align = validate_doc({"paragraphs": [para([{"text": "a"}], align="top")]}, HIRED)

    assert any("nope" in message for message in unknown)
    assert any("догол мөр" in message.lower() for message in bad_shape)
    assert any("зэрэгцүүлэлт" in message for message in bad_align)


@pytest.mark.parametrize("align", [[], {}, None, 3])
def test_validate_doc_returns_a_message_for_a_non_string_align(align: object) -> None:
    messages = validate_doc({"paragraphs": [{**para([{"text": "a"}]), "align": align}]}, HIRED)

    assert any("зэрэгцүүлэлт" in message for message in messages)


@pytest.mark.parametrize("text", ["a\x00b", "a\x0bb", "a\ud800b"])
def test_validate_doc_refuses_xml_illegal_characters(text: str) -> None:
    messages = validate_doc({"paragraphs": [para([{"text": text}])]}, HIRED)

    assert any("хяналтын тэмдэгт" in message for message in messages)


@pytest.mark.parametrize("text", ["a\tb", "a\nb", "a\rb"])
def test_validate_doc_accepts_tab_and_line_breaks_and_saves(text: str) -> None:
    doc = {"paragraphs": [para([{"text": text}])]}

    assert validate_doc(doc, HIRED) == []
    assert doc_to_docx(doc, HIRED)


def test_validate_doc_accepts_a_good_document() -> None:
    doc = {"paragraphs": [para([{"text": "Тушаах: "}, {"field": "employee_full_name"}])]}

    assert validate_doc(doc, HIRED) == []

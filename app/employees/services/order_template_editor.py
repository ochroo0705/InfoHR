"""Converts an order template between Word (.docx) and the in-page editor's document (plain paragraphs).

The editor shows and edits only what it can represent: paragraphs with one alignment, one bold/italic/size each,
and text pieces plus `{{ name }}` fields. A paragraph may also be shown only when one field has a value
(`show_if`, written as a `{%p if name %}` ... `{%p endif %}` pair around it) and may be a numbered item
(`numbered`, a counter that skips hidden items). Anything else (tables, pictures, other `{% %}` logic, header or
footer text, tracked changes, hyperlinks) makes `docx_to_doc` return None, and the page then shows the template
read-only.
"""

import io
import re
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from employees.models import OrderType
from employees.services import order_docs

EditorDoc = dict[str, Any]

ALIGN_TO_DOCX = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
ALIGN_FROM_DOCX = {
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}
FIELD_TAG = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
LOGIC_MARKS = ("{%", "%}", "{#", "#}", "{{", "}}")
# Characters XML 1.0 forbids (and lone surrogates); tab, newline and carriage return are allowed.
XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
ALLOWED_BODY_CHILDREN = {qn("w:p"), qn("w:sectPr")}
ALLOWED_PARAGRAPH_CHILDREN = {qn("w:pPr"), qn("w:r"), qn("w:bookmarkStart"), qn("w:bookmarkEnd"), qn("w:proofErr")}
COUNTER_START = "{%p set item_no = 0 %}"
COUNTER_STEP = "{% set item_no = item_no + 1 %}{{ item_no }}. "
IF_PARAGRAPH = re.compile(r"\{%p\s+if\s+([A-Za-z_][A-Za-z0-9_]*)\s+%\}")
ENDIF_PARAGRAPH = re.compile(r"\{%p\s+endif\s+%\}")
MIN_SIZE_PT = 6
MAX_SIZE_PT = 72


def docx_to_doc(data: bytes, order_type: OrderType | int) -> EditorDoc | None:
    """The editor document of a template, or None when the editor cannot show it (the page is then read-only).

    `order_type` is accepted for symmetry with `doc_to_docx`; any PLACEHOLDERS name is kept as a field, even one
    that does not fill for this order type.
    """
    try:
        document = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001  # arbitrary uploaded bytes: a bad zip or bad XML means "cannot be shown"
        return None
    if _has_unsupported_body(document) or _has_header_or_footer_content(document):
        return None
    paragraphs: list[dict[str, Any]] = []
    show_if: str | None = None  # the open `{%p if %}` and the paragraphs it has wrapped so far
    wrapped = 0
    has_counter = False
    uses_counter = False
    for index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if text == COUNTER_START and index == 0:
            has_counter = True
            continue
        opening = IF_PARAGRAPH.fullmatch(text)
        if opening:
            if show_if is not None:
                return None  # nested conditions are not supported
            show_if, wrapped = opening.group(1), 0
            if show_if not in order_docs.PLACEHOLDERS:
                return None
            continue
        if ENDIF_PARAGRAPH.fullmatch(text):
            if show_if is None or wrapped != 1:
                return None  # a condition wraps exactly one paragraph
            show_if = None
            continue
        converted = _paragraph_to_editor(paragraph)
        if converted is None:
            return None
        converted["show_if"] = show_if
        if show_if is not None:
            wrapped += 1
        uses_counter = uses_counter or converted["numbered"]
        paragraphs.append(converted)
    if show_if is not None or (uses_counter and not has_counter):
        return None
    return {"paragraphs": paragraphs}


def doc_to_docx(doc: EditorDoc, order_type: OrderType | int) -> bytes:
    """A .docx built on the bundled starter of this type: its page margins and base style are kept, and every
    body paragraph is replaced by the editor's paragraphs (one run each)."""
    document = Document(io.BytesIO(order_docs.starter_path(order_type).read_bytes()))
    body = document.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    if any(item.get("numbered") for item in doc["paragraphs"]):
        document.add_paragraph(COUNTER_START)
    for item in doc["paragraphs"]:
        show_if = item.get("show_if")
        if show_if:
            document.add_paragraph("{%p if " + show_if + " %}")
        paragraph = document.add_paragraph()
        paragraph.alignment = ALIGN_TO_DOCX[item["align"]]
        run = paragraph.add_run((COUNTER_STEP if item.get("numbered") else "") + _text_of(item["parts"]))
        run.bold = True if item["bold"] else None
        run.italic = True if item["italic"] else None
        if item["size"] is not None:
            run.font.size = Pt(item["size"])
        if show_if:
            document.add_paragraph("{%p endif %}")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def validate_doc(doc: object, order_type: OrderType | int) -> list[str]:
    """Why an editor document cannot be saved (Mongolian messages); an empty list means it can.

    A structurally valid document is also built into a .docx and checked with `order_docs.check_template`.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("paragraphs"), list):
        return ["Баримтын бүтэц буруу байна: догол мөрүүд жагсаалт байх ёстой."]
    errors: list[str] = []
    for number, paragraph in enumerate(doc["paragraphs"], start=1):
        errors += _paragraph_errors(paragraph, number)
    if errors:
        return errors
    return order_docs.check_template(doc_to_docx(doc, order_type))


def _has_unsupported_body(document: Any) -> bool:
    """A body with anything but paragraphs (a table, a content control, ...), or a picture or drawing inside one."""
    body = document.element.body
    if any(child.tag not in ALLOWED_BODY_CHILDREN for child in body):
        return True
    return bool(body.xpath(".//w:drawing | .//w:pict | .//w:object"))


def _has_header_or_footer_content(document: Any) -> bool:
    """True when a header or footer that the document defines has any text, page number or picture."""
    for section in document.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            if part.is_linked_to_previous:
                continue
            content = part._element.xpath(  # noqa: SLF001
                ".//w:t[normalize-space()] | .//w:instrText | .//w:fldSimple | .//w:drawing"
            )
            if content:
                return True
    return False


def _paragraph_to_editor(paragraph: Any) -> dict[str, Any] | None:
    """One body paragraph as the editor sees it, or None when it mixes styles or holds something the editor drops."""
    if any(child.tag not in ALLOWED_PARAGRAPH_CHILDREN for child in paragraph._p):  # noqa: SLF001
        return None
    runs = list(paragraph.runs)
    text_runs = [run for run in runs if run.text]
    checked = text_runs or runs[:1]
    styles = {(bool(run.bold), bool(run.italic), run.font.size) for run in checked}
    if len(styles) > 1:
        return None
    bold, italic, size = styles.pop() if styles else (False, False, None)
    text = paragraph.text
    numbered = text.startswith(COUNTER_STEP)
    parts = _split_text(text[len(COUNTER_STEP) :] if numbered else text)
    if parts is None:
        return None
    return {
        "numbered": numbered,
        "align": ALIGN_FROM_DOCX.get(paragraph.alignment, "left"),
        "bold": bold,
        "italic": italic,
        "size": size.pt if size is not None else None,
        "parts": parts,
    }


def _split_text(text: str) -> list[dict[str, str]] | None:
    """Text cut into text and field parts; None for an unknown `{{ }}` name or any other template tag."""
    parts: list[dict[str, str]] = []
    position = 0
    for match in FIELD_TAG.finditer(text):
        if match.group(1) not in order_docs.PLACEHOLDERS:
            return None
        if match.start() > position:
            parts.append({"text": text[position : match.start()]})
        parts.append({"field": match.group(1)})
        position = match.end()
    if position < len(text):
        parts.append({"text": text[position:]})
    leftovers = FIELD_TAG.sub("", text)
    if any(mark in leftovers for mark in LOGIC_MARKS):
        return None
    return parts


def _text_of(parts: list[dict[str, str]]) -> str:
    """The paragraph's text as it is written in the .docx: field parts become their `{{ name }}` tag."""
    return "".join(part["text"] if "text" in part else "{{ " + part["field"] + " }}" for part in parts)


def _paragraph_errors(paragraph: object, number: int) -> list[str]:
    """Mongolian messages for one editor paragraph (`number` is its 1-based position in the document)."""
    prefix = f"Догол мөр {number}: "
    if not isinstance(paragraph, dict):
        return [prefix + "буруу бүтэцтэй байна."]
    errors: list[str] = []
    align = paragraph.get("align")
    if not (isinstance(align, str) and align in ALIGN_TO_DOCX):
        errors.append(prefix + f"зэрэгцүүлэлт «{align}» буруу байна. left, center, right, justify-ийн нэг байх ёстой.")
    for key in ("bold", "italic"):
        if not isinstance(paragraph.get(key), bool):
            errors.append(prefix + f"«{key}» үнэн эсвэл худал байх ёстой.")
    size = paragraph.get("size")
    is_number = isinstance(size, int | float) and not isinstance(size, bool)
    if size is not None and not (is_number and MIN_SIZE_PT <= size <= MAX_SIZE_PT):
        errors.append(prefix + f"фонтын хэмжээ буруу байна ({MIN_SIZE_PT}-{MAX_SIZE_PT} эсвэл хоосон).")
    show_if = paragraph.get("show_if")
    if show_if is not None and not (isinstance(show_if, str) and show_if in order_docs.PLACEHOLDERS):
        errors.append(prefix + "«зөвхөн утгатай үед харуулах» талбар танигдсангүй.")
    if not isinstance(paragraph.get("numbered", False), bool):
        errors.append(prefix + "«дугаарлах» үнэн эсвэл худал байх ёстой.")
    parts = paragraph.get("parts")
    if not isinstance(parts, list):
        return errors + [prefix + "текст, талбарын хэсгүүд жагсаалт байх ёстой."]
    for part in parts:
        if not isinstance(part, dict) or set(part) not in ({"text"}, {"field"}):
            errors.append(prefix + "хэсгийн бүтэц буруу байна.")
        elif "field" in part:
            if not isinstance(part["field"], str) or part["field"] not in order_docs.PLACEHOLDERS:
                name = part["field"]
                errors.append(
                    f"Танигдаагүй талбар: {name}. Зөвшөөрөгдсөн нэрсийг «Талбаруудын тайлбар» товчоор харна уу."
                )
        elif not isinstance(part["text"], str):
            errors.append(prefix + "текстийн хэсэг текст байх ёстой.")
        elif any(mark in part["text"] for mark in LOGIC_MARKS):
            errors.append(prefix + "текстэд {{ }} эсвэл {% %} тэмдэглэгээ бичиж болохгүй.")
        elif XML_ILLEGAL.search(part["text"]):
            errors.append(prefix + "текстэд Word-д хүлээн авахгүй хяналтын тэмдэгт байна.")
    return errors

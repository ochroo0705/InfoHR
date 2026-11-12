"""Word documents for HR orders: fills a template (docxtpl) from an order. The template is the install's own upload
(admin «Тушаалын загвар», D-053) or else the bundled starter in `order_templates/*.docx`.

Conventions the templates rely on (see COWORK.md): `effective_date` and `probation_end` carry their own ending
("2026 оны 11 дүгээр сарын 1-ний", the template adds " өдрөөс эхлэн" / " өдөр"); `order_date` already ends with
"өдөр"; names of departments and positions are passed bare; `salary` is filled only for users who may see it.
"""

import datetime
import io
import zipfile
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from accounts.models import User
from django.conf import settings
from django.utils import timezone
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.exceptions import PackageNotFoundError
from docxtpl import DocxTemplate
from fpdf import FPDF
from fpdf.enums import MethodReturnValue
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from macs.models import Department, Position
from PIL import Image

from employees import access, history_range
from employees.models import CompanySettings, EmployeeExt, HrOrder, JobRecord, OrderTemplate, OrderType
from employees.money import group
from employees.services import events, history, macs_writes, orders

TEMPLATE_FILES = {
    OrderType.HIRED: "01_ajild_orson.docx",
    OrderType.DEPARTMENT: "02_heltees_salbar_shiljseen.docx",
    OrderType.POSITION: "03_alban_tushaal_solison.docx",
    OrderType.FIRED: "04_ajlaas_garsan.docx",
    OrderType.PENSION: "05_tetgevert_garsan.docx",
    OrderType.TYPE_CHANGED: "06_turul_soligdson.docx",
}
DEFAULT_SUMMARY = {
    OrderType.HIRED: "Ажилд томилох тухай",
    OrderType.DEPARTMENT: "Хэлтэс, салбар шилжүүлэх тухай",
    OrderType.POSITION: "Албан тушаал солих тухай",
    OrderType.FIRED: "Ажлаас чөлөөлөх тухай",
    OrderType.PENSION: "Тэтгэвэрт гарсанд ажлаас чөлөөлөх тухай",
    OrderType.TYPE_CHANGED: "Хөдөлмөрийн хэлбэр өөрчлөх тухай",
}
MONTHS = (
    "нэгдүгээр",
    "хоёрдугаар",
    "гуравдугаар",
    "дөрөвдүгээр",
    "тавдугаар",
    "зургадугаар",
    "долдугаар",
    "наймдугаар",
    "есдүгээр",
    "аравдугаар",
    "арван нэгдүгээр",
    "арван хоёрдугаар",
)
BLANK_NUMBER = "______"
BLANK_DATE = "____ оны __ сарын __"
BLANK_SIGNATURE = "______________"  # the empty signature line of a paper order
SIGNATURE_TOKEN = "[[signature]]"  # noqa: S105  # a marker, not a secret; the signing step swaps it for the picture
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"
PDF_ALIGN = {WD_ALIGN_PARAGRAPH.CENTER: "C", WD_ALIGN_PARAGRAPH.RIGHT: "R", WD_ALIGN_PARAGRAPH.JUSTIFY: "J"}
PT_MM = 25.4 / 72
SIGNATURE_WIDTH_MM = 40  # the drawn signature on the PDF, right-aligned like the director's line under it
SIGNATURE_MAX_HEIGHT_MM = 25  # the picture never gets taller than this (a thin, tall PNG would run off the page)
SIGNATURE_LINE_MM = 4  # one line of the name and time under the picture


class OrderDocError(Exception):
    """The Word template of this order type is missing or unreadable."""


@dataclass(frozen=True)
class SignatureStamp:
    """What the on-screen signing step puts on the PDF: the drawn signature, the signer's name and the time."""

    image: bytes  # PNG with transparency, trimmed, at most 600 px wide
    name: str
    signed_at: datetime.datetime  # aware values are shown in local time


# Every name a template may use: the keys of `build_context` (a test keeps the two in step).
PLACEHOLDERS = (
    "company_name",
    "director_name",
    "issued_by",
    "order_number",
    "order_date",
    "order_summary",
    "employee_full_name",
    "employee_short_name",
    "employee_number",
    "register_number",
    "department",
    "position",
    "employee_type",
    "effective_date",
    "old_department",
    "new_department",
    "old_position",
    "new_position",
    "old_employee_type",
    "new_employee_type",
    "probation_end",
    "salary",
    "termination_reason",
    "signature",
)

# What each placeholder holds, for the «Талбарууд» pop-up on the template admin page: (group, name, meaning).
# A test keeps the names in step with PLACEHOLDERS.
PLACEHOLDER_HELP: tuple[tuple[str, str, str], ...] = (
    ("Тушаал", "company_name", "Байгууллагын нэр («Компанийн тохиргоо»-с)."),
    ("Тушаал", "director_name", "Захирлын нэр («Компанийн тохиргоо»-с)."),
    ("Тушаал", "issued_by", "Тушаал гаргасан хүн. Хоосон бол захирлын нэр орно."),
    ("Тушаал", "order_number", "Тушаалын дугаар. Дугаар өгөөгүй бол «______» гарна."),
    ("Тушаал", "order_date", "Тушаалын огноо, «өдөр» гэж төгсөнө (2026 оны 11 дүгээр сарын 3-ны өдөр)."),
    ("Тушаал", "order_summary", "Тушаалын агуулга (гарчиг). Хоосон бол тухайн төрлийн стандарт текст орно."),
    ("Ажилтан", "employee_full_name", "Ажилтны овог, нэр бүтнээрээ."),
    ("Ажилтан", "employee_short_name", "Овгийн эхний үсэг, нэр (Б. Энхбаяр)."),
    ("Ажилтан", "employee_number", "Ажилтны код."),
    ("Ажилтан", "register_number", "Регистрийн дугаар."),
    ("Ажил", "department", "Хэлтэс (өөрчлөлтийн дараах)."),
    ("Ажил", "position", "Албан тушаал (өөрчлөлтийн дараах)."),
    ("Ажил", "employee_type", "Ажилтны төрөл, хөдөлмөрийн хэлбэр (өөрчлөлтийн дараах)."),
    (
        "Ажил",
        "effective_date",
        "Хүчин төгөлдөр болох огноо. Загвар «өдрөөс эхлэн» гэж үргэлжлүүлнэ (2026 оны 11 дүгээр сарын 1-ний).",
    ),
    ("Өмнөх ба шинэ", "old_department", "Өмнөх хэлтэс."),
    ("Өмнөх ба шинэ", "new_department", "Шинэ хэлтэс."),
    ("Өмнөх ба шинэ", "old_position", "Өмнөх албан тушаал."),
    ("Өмнөх ба шинэ", "new_position", "Шинэ албан тушаал."),
    ("Өмнөх ба шинэ", "old_employee_type", "Өмнөх ажилтны төрөл."),
    ("Өмнөх ба шинэ", "new_employee_type", "Шинэ ажилтны төрөл."),
    ("Бусад", "probation_end", "Туршилтын хугацаа дуусах огноо. Зөвхөн ажилд авах тушаалд, туршилттай ажилтанд гарна."),
    ("Бусад", "salary", "Үндсэн цалин. Зөвхөн ажилд авах тушаалд, цалин харах эрхтэй хэрэглэгчид гарна."),
    ("Бусад", "termination_reason", "Ажлаас гарсан шалтгаан (жижиг үсгээр эхэлнэ)."),
    (
        "Тушаал",
        "signature",
        "Гарын үсгийн байрлал. Дэлгэц дээр гарын үсэг зурахад зураг, нэр, огноо энд орно; "
        "зурахаас өмнө хоосон зураас гарна.",
    ),
)


# Placeholders every order type fills, and the extra ones that fill for each type (the template page lists only these).
# Any name in PLACEHOLDERS is still accepted in an upload; one outside its type's list simply stays empty.
COMMON_PLACEHOLDERS = (
    "company_name",
    "director_name",
    "issued_by",
    "order_number",
    "order_date",
    "order_summary",
    "employee_full_name",
    "employee_short_name",
    "employee_number",
    "register_number",
    "effective_date",
    "signature",
)
EXTRA_PLACEHOLDERS: dict[OrderType, tuple[str, ...]] = {
    OrderType.HIRED: ("department", "position", "employee_type", "probation_end", "salary"),
    OrderType.DEPARTMENT: ("old_department", "new_department", "position", "employee_type"),
    OrderType.POSITION: ("department", "old_position", "new_position", "employee_type"),
    OrderType.FIRED: ("department", "position", "termination_reason"),
    OrderType.PENSION: ("department", "position", "termination_reason"),
    OrderType.TYPE_CHANGED: ("department", "position", "old_employee_type", "new_employee_type"),
}


def placeholders_for(order_type: OrderType | int) -> tuple[str, ...]:
    """The placeholders that fill for this order type, in the order of PLACEHOLDERS."""
    wanted = {*COMMON_PLACEHOLDERS, *EXTRA_PLACEHOLDERS[OrderType(order_type)]}
    return tuple(name for name in PLACEHOLDERS if name in wanted)


def placeholder_help_for(order_type: OrderType | int) -> tuple[tuple[str, str, str], ...]:
    """PLACEHOLDER_HELP rows (group, name, meaning) of the placeholders that fill for this order type."""
    names = set(placeholders_for(order_type))
    return tuple(row for row in PLACEHOLDER_HELP if row[1] in names)


def starter_path(order_type: OrderType | int) -> Path:
    """The bundled starter template of an order type (the one every new install starts with)."""
    return Path(settings.ORDER_TEMPLATES_DIR) / TEMPLATE_FILES[OrderType(order_type)]


# While a batch of orders is rendered (render_pdf_many) the same template file, company settings and
# department/position names are read once, not once per order. Outside a batch nothing is remembered.
_batch: ContextVar[dict[Any, Any] | None] = ContextVar("order_docs_batch", default=None)


def _remembered(key: Any, make: Callable[[], Any]) -> Any:
    cache = _batch.get()
    if cache is None:
        return make()
    if key not in cache:
        cache[key] = make()
    return cache[key]


def _template_data(order_type: int) -> Path | bytes:
    row = OrderTemplate.objects.filter(order_type=order_type).exclude(file="").first()
    if row is None:
        return starter_path(order_type)
    try:
        with row.file.open("rb") as handle:
            return handle.read()
    except OSError as error:  # an uploaded file that is gone is an error, not a silent fall back to the starter
        raise OrderDocError(f"{row.file.name}") from error


def template_source(order_type: OrderType | int) -> Path | io.BytesIO:
    """The install's own uploaded template of this type, else the bundled starter."""
    data = _remembered(("template", int(order_type)), lambda: _template_data(int(order_type)))
    return data if isinstance(data, Path) else io.BytesIO(data)


def _render(source: Path | io.BytesIO, context: dict[str, Any]) -> bytes:
    """Fill a template. Rendered in a sandbox: an uploaded file may only use the plain placeholders and `if`/`for`."""
    template = DocxTemplate(str(source) if isinstance(source, Path) else source)
    try:
        template.render(context, jinja_env=SandboxedEnvironment(), autoescape=True)  # the file is opened here
    except (OSError, ValueError, PackageNotFoundError, TemplateError, KeyError) as error:  # missing or not a .docx
        raise OrderDocError(str(source)) from error
    out = io.BytesIO()
    template.save(out)
    return out.getvalue()


def check_template(data: bytes) -> list[str]:
    """Why an uploaded file cannot be an order template (Mongolian messages); an empty list means it can."""
    try:
        template = DocxTemplate(io.BytesIO(data))
        used = template.get_undeclared_template_variables()
    except Exception:  # noqa: BLE001  # arbitrary uploaded bytes: a bad zip, bad XML or a bad tag all mean "not a template"
        return ["Файл нь Word (.docx) загвар биш эсвэл гэмтсэн байна."]
    unknown = sorted(name for name in used if name not in PLACEHOLDERS)
    if unknown:
        names = ", ".join(unknown)
        return [f"Танигдаагүй орлуулагч: {names}. Зөвшөөрөгдсөн нэрсийг «Талбаруудын тайлбар» товчоор харна уу."]
    try:
        _render(io.BytesIO(data), {name: f"[{name}]" for name in PLACEHOLDERS})
    except OrderDocError:
        return ["Загварыг бөглөж чадсангүй: {{ }} болон {% %} тэмдэглэгээг шалгана уу."]
    return []


def day_ending(day: int) -> str:
    """Genitive ending after a day of the month written in digits: 1-ний, 4-ний, 9-ний, 11-ний ... else -ны."""
    return "ний" if day % 10 in (1, 4, 9) and day not in (10, 20, 30) else "ны"


def mn_date(day: datetime.date | None) -> str:
    """'2026 оны 11 дүгээр сарын 1-ний' (the ending is part of the text, see the module note)."""
    if day is None:
        return BLANK_DATE
    return f"{day.year} оны {MONTHS[day.month - 1]} сарын {day.day}-{day_ending(day.day)}"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _name(model: type[Department] | type[Position], pk: int | None) -> str:
    if pk is None:
        return ""
    return str(
        _remembered(("name", model, pk), lambda: model.objects.filter(pk=pk).values_list("name", flat=True).first())
        or ""
    )


def _emptype_label(code: int | None) -> str:
    return dict(JobRecord._meta.get_field("emptype").flatchoices).get(code, "") if code is not None else ""


def _hire_day(order: HrOrder) -> datetime.date | None:
    first = order.employee.job_records.order_by(*history_range.ORDER).first()
    day: datetime.date | None = first.period.lower if first is not None else order.employee.first_hire_date
    return day


def build_context(order: HrOrder, user: User, *, signature: str = BLANK_SIGNATURE) -> dict[str, Any]:
    """Every placeholder of the order templates, as text. `signature` fills the signature line (see SIGNATURE_TOKEN)."""
    employee, event = order.employee, order.event
    company = _remembered("company", CompanySettings.get)
    day = event.effective if event is not None else _hire_day(order)
    new = macs_writes._state_on(employee, day) if day else None
    old = macs_writes._state_on(employee, day - datetime.timedelta(days=1)) if day else None
    if event is not None and event.applied_at is None and day:
        # Still waiting for the signed order: nothing is applied yet, so the NEW state is the proposal.
        current = history.job_on(employee, day)
        if current is not None:
            proposed = (event.proposed or {}).get("job") or {}
            changes = events._load_changes(proposed)  # keeps the status: a termination's LEFT decides its employee type
            candidate = orders.candidate_job(employee, current, changes, event.type, event.pension)
            new = macs_writes.state_of(employee, candidate, day)
    shown = new or old or {}  # a job that ends on the day (termination) is only found the day before
    order_type = OrderType(order.order_type)
    ext = EmployeeExt.objects.filter(employee=employee).first()
    salary = ""
    if order.is_hire and day and access.can_view_salary(user):
        record = history.salary_on(employee, day)
        salary = f"{group(record.base_salary)}₮" if record is not None else ""
    probation_end = ""
    if order.is_hire and ext is not None and ext.probation_end and shown.get("emptype") == 9:
        probation_end = mn_date(ext.probation_end)
    reason = ""
    if event is not None:
        reason = _lower_first(event.fired_reason.name if event.fired_reason is not None else event.reason)
    return {
        "company_name": company.name,
        "director_name": company.director_name,
        "issued_by": order.issued_by or company.director_name,
        "order_number": order.number or BLANK_NUMBER,
        "order_date": f"{mn_date(order.date)} өдөр",
        "order_summary": order.summary or DEFAULT_SUMMARY[order_type],
        "employee_full_name": employee.full_name,
        "employee_short_name": employee.short_name,
        "employee_number": employee.code or "",
        "register_number": employee.register_no or "",
        "department": _name(Department, shown.get("department_id")),
        "position": _name(Position, shown.get("position_id")),
        "employee_type": _emptype_label(shown.get("emptype")),
        "effective_date": mn_date(day),
        "old_department": _name(Department, (old or shown).get("department_id")),
        "new_department": _name(Department, shown.get("department_id")),
        "old_position": _name(Position, (old or shown).get("position_id")),
        "new_position": _name(Position, shown.get("position_id")),
        "old_employee_type": _emptype_label((old or shown).get("emptype")),
        "new_employee_type": _emptype_label(shown.get("emptype")),
        "probation_end": probation_end,
        "salary": salary,
        "termination_reason": reason,
        "signature": signature,
    }


def _shown(record: JobRecord, field: str) -> str:
    """One job field as the pop-up shows it: the choice label, the row's name, an ISO date or text."""
    value = getattr(record, field)
    if value in (None, ""):
        return "—"
    if hasattr(record, f"get_{field}_display"):
        return str(getattr(record, f"get_{field}_display")())
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(getattr(value, "full_name", value))


def change_rows(order: HrOrder, user: User) -> list[tuple[str, str, str]]:
    """What a change actually changes: (label, before, after) for each job field that differs, then the base salary
    when `user` may see it. Empty for a hire and for a change that ends the job (nothing to compare)."""
    event = order.event
    if event is None:
        return []
    employee, day = order.employee, event.effective
    old = history.job_on(employee, day - datetime.timedelta(days=1))
    if event.applied_at is None:
        # Waiting for the signed order: the job on the day is still the old one, the proposal is the new one.
        before = history.job_on(employee, day)
        proposed = (event.proposed or {}).get("job") or {}
        after = (
            orders.candidate_job(employee, before, events._load_changes(proposed), event.type, event.pension)
            if before is not None
            else None
        )
        old = before
    else:
        after = history.job_on(employee, day)
    rows: list[tuple[str, str, str]] = []
    if old is not None and after is not None and event.type != "termination":
        for name in JobRecord.JOB_FIELDS:
            if name == "emptype" and old.employee_type != after.employee_type:
                continue  # the code behind employee_type: shown through it unless it moved alone (e.g. probation)
            field: Any = JobRecord._meta.get_field(name)
            if getattr(old, field.attname) != getattr(after, field.attname):
                label = "Ажилтны ангилал" if name == "emptype" else str(field.verbose_name)
                rows.append((label, _shown(old, name), _shown(after, name)))
    if access.can_view_salary(user):
        before_salary = history.salary_on(employee, day - datetime.timedelta(days=1))
        if event.applied_at is None:
            raw = (event.proposed or {}).get("salary")
            new_amount = Decimal(str(raw)) if raw not in (None, "") else None
        else:
            record = history.salary_on(employee, day)
            new_amount = record.base_salary if record is not None else None
        old_amount = before_salary.base_salary if before_salary is not None else None
        if new_amount is not None and new_amount != old_amount:
            rows.append(
                (
                    "Үндсэн цалин",
                    f"{group(old_amount)}₮" if old_amount is not None else "—",
                    f"{group(new_amount)}₮",
                )
            )
    return rows


def render_order(order: HrOrder, user: User, *, signature: str = BLANK_SIGNATURE) -> bytes:
    """The filled Word file of an order."""
    return _render(template_source(order.order_type), build_context(order, user, signature=signature))


def _pdf_fonts() -> tuple[str, str, str, str]:
    for files in settings.ORDER_PDF_FONT_SETS:
        if all(Path(f).is_file() for f in files):
            return tuple(files)  # type: ignore[return-value]
    raise OrderDocError("no Cyrillic font found (settings.ORDER_PDF_FONT_SETS)")


def _new_pdf(word: Any) -> FPDF:
    """An empty A4 PDF with the margins of the Word file and the Cyrillic fonts loaded."""
    section = word.sections[0]
    pdf = FPDF(unit="mm", format="A4")
    left, top, right, bottom = (
        m.mm if m is not None else 25.4
        for m in (section.left_margin, section.top_margin, section.right_margin, section.bottom_margin)
    )
    pdf.set_margins(left, top, right)
    pdf.set_auto_page_break(True, margin=bottom)
    for style, path in zip(("", "B", "I", "BI"), _pdf_fonts(), strict=True):
        pdf.add_font("Order", style, path)
    return pdf


def _signature_size(stamp: SignatureStamp) -> tuple[float, float]:
    """The picture's size on the PDF in mm: 40 mm wide, or 25 mm tall for a very tall picture (its width shrinks with
    the height, so the aspect is kept)."""
    with Image.open(io.BytesIO(stamp.image)) as picture:
        width_px, height_px = picture.size
    width, height = SIGNATURE_WIDTH_MM, SIGNATURE_WIDTH_MM * height_px / width_px
    if height > SIGNATURE_MAX_HEIGHT_MM:  # a very tall, thin picture: keep its aspect, stop at the height limit
        height = SIGNATURE_MAX_HEIGHT_MM
        width = SIGNATURE_MAX_HEIGHT_MM * width_px / height_px
    return width, height


def _signed_at_text(stamp: SignatureStamp) -> str:
    """The signing time in local time, as YYYY-MM-DD HH:MM."""
    when = timezone.localtime(stamp.signed_at) if timezone.is_aware(stamp.signed_at) else stamp.signed_at
    return when.strftime("%Y-%m-%d %H:%M")


def _draw_picture(pdf: FPDF, stamp: SignatureStamp, top: float, width: float, height: float) -> None:
    """The picture right-aligned like the director's line, its top at `top`; the cursor goes under it."""
    pdf.image(io.BytesIO(stamp.image), x=pdf.w - pdf.r_margin - width, y=top, w=width, h=height)
    pdf.set_y(top + height)


def _draw_signature(pdf: FPDF, stamp: SignatureStamp) -> None:
    """A marker paragraph that holds only the marker (custom templates, and the no-marker fallback): the picture,
    then the signer's name and the time under it."""
    width, height = _signature_size(stamp)
    lines = (stamp.name, _signed_at_text(stamp))
    if pdf.will_page_break(height + SIGNATURE_LINE_MM * len(lines)):
        pdf.add_page()
    top = pdf.get_y()
    _draw_picture(pdf, stamp, top, width, height)
    pdf.set_font("Order", "", 8)
    for line in lines:
        pdf.cell(0, SIGNATURE_LINE_MM, line, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _run_font(paragraph: Any, base_pt: float) -> tuple[str, float]:
    """The font style ("", "B", "I" or "BI") and size of a paragraph, from its first text run."""
    run = next((r for r in paragraph.runs if r.text.strip()), None)
    points = run.font.size.pt if run is not None and run.font.size else base_pt
    style = ("B" if run is not None and run.bold else "") + ("I" if run is not None and run.italic else "")
    return style, points


def _draw_signature_on_line(pdf: FPDF, stamp: SignatureStamp, paragraph: Any, base_pt: float, text: str) -> None:
    """A marker paragraph that also holds text (the starter templates: «<marker> /<director>/»): the picture first,
    on the line, then the paragraph's own text directly under it, then the signing time. The signer's name is not
    drawn here: the paragraph already shows the director, and the name is kept on the signing record."""
    width, height = _signature_size(stamp)
    style, points = _run_font(paragraph, base_pt)
    pdf.set_font("Order", style, points)
    line_height = points * PT_MM * 1.25
    # the lines the director line really takes (word wrap), measured without drawing anything
    text_lines = len(pdf.multi_cell(0, line_height, text, dry_run=True, output=MethodReturnValue.LINES))
    gap = 1.5  # the space _draw_paragraph leaves after the text
    needed = height + text_lines * line_height + gap + SIGNATURE_LINE_MM + gap  # all three on one page, or none
    if pdf.will_page_break(needed):
        pdf.add_page()
    top = pdf.get_y()
    _draw_picture(pdf, stamp, top, width, height)
    _draw_paragraph(pdf, paragraph, base_pt, text)
    pdf.set_font("Order", "", 8)
    pdf.cell(0, SIGNATURE_LINE_MM, _signed_at_text(stamp), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _draw_paragraph(pdf: FPDF, paragraph: Any, base_pt: float, text: str) -> None:
    """One paragraph of the Word file, drawn with its own font, size and alignment. `text` is what to draw (the
    paragraph's text, or the part of it that is left after the signature marker is taken out)."""
    style, points = _run_font(paragraph, base_pt)
    pdf.set_font("Order", style, points)
    height = points * PT_MM * 1.25
    if not text.strip():
        pdf.ln(height)
        return
    pdf.multi_cell(
        0,
        height,
        text,
        align=PDF_ALIGN.get(paragraph.alignment, "L") if paragraph.alignment is not None else "L",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(1.5)


def _draw_order(pdf: FPDF, word: Any, stamp: SignatureStamp | None = None) -> None:
    """One order on its own new page, paragraph by paragraph.

    A paragraph holding the signature marker (SIGNATURE_TOKEN) is handled in two ways, for the first marker only when
    a stamp is given:
    - the marker is the only text (custom templates): the paragraph is dropped and the picture, the signer's name and
      the time are drawn in its place (_draw_signature);
    - the paragraph has other text (the starter templates, «<marker> /<director>/»): the picture is drawn first, then
      the paragraph's text under it, then the time (_draw_signature_on_line). The name is not drawn.
    Later marker paragraphs keep their remaining text and get no picture. Without any marker the stamp goes after the
    last paragraph (_draw_signature). Without a stamp the marker paragraphs are drawn as plain text."""
    base_pt = word.styles["Normal"].font.size.pt if word.styles["Normal"].font.size else 11.0
    pdf.add_page()
    token_seen = False
    for paragraph in word.paragraphs:
        if SIGNATURE_TOKEN in paragraph.text:
            rest = paragraph.text.replace(SIGNATURE_TOKEN, "").strip()
            first = stamp is not None and not token_seen
            if first and rest:
                _draw_signature_on_line(pdf, stamp, paragraph, base_pt, rest)
            else:
                if rest:
                    _draw_paragraph(pdf, paragraph, base_pt, rest)
                if first:
                    _draw_signature(pdf, stamp)
            token_seen = True
            continue
        _draw_paragraph(pdf, paragraph, base_pt, paragraph.text)
    if stamp is not None and not token_seen:
        _draw_signature(pdf, stamp)


def render_pdf(order: HrOrder, user: User) -> bytes:
    """The same order as a PDF. Drawn from the filled Word file paragraph by paragraph (alignment, bold, size),
    because no Word or LibreOffice is available on the server; the layout is close to Word's, not identical."""
    return render_pdf_many([order], user)[0]


def render_pdf_many(orders: list[HrOrder], user: User) -> tuple[bytes, list[HrOrder]]:
    """Several orders in one PDF, each on its own page, in the given order (to print and sign in one go). An order
    that cannot be filled (no usable template) is left out; the PDF and the orders in it are returned. Margins come
    from the first order's Word file. Raises OrderDocError when none can be printed."""
    used: list[HrOrder] = []
    words = []
    token = _batch.set({})
    try:
        for order in orders:
            try:
                words.append(Document(io.BytesIO(render_order(order, user))))
            except OrderDocError:
                continue
            used.append(order)
    finally:
        _batch.reset(token)
    if not words:
        raise OrderDocError("no orders to print")
    pdf = _new_pdf(words[0])
    for word in words:
        _draw_order(pdf, word)
    return bytes(pdf.output()), used


def render_signed_pdf(order: HrOrder, user: User, stamp: SignatureStamp) -> bytes:
    """The order as a PDF with the signer's picture, name and time in the signature place."""
    try:  # signing only: a template that cannot be opened (corrupt zip, missing file) is a refusal, not a crash
        filled = render_order(order, user, signature=SIGNATURE_TOKEN)
    except (OSError, zipfile.BadZipFile) as error:
        raise OrderDocError(str(error)) from error
    word = Document(io.BytesIO(filled))
    pdf = _new_pdf(word)
    _draw_order(pdf, word, stamp)
    return bytes(pdf.output())

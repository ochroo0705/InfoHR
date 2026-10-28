"""Word documents for HR orders: fills `order_templates/*.docx` (docxtpl) from an order.

Conventions the templates rely on (see COWORK.md): `effective_date` and `probation_end` carry their own ending
("2026 оны 11 дүгээр сарын 1-ний", the template adds " өдрөөс эхлэн" / " өдөр"); `order_date` already ends with
"өдөр"; names of departments and positions are passed bare; `salary` is filled only for users who may see it.
"""

import datetime
import io
from pathlib import Path
from typing import Any

from accounts.models import User
from django.conf import settings
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.exceptions import PackageNotFoundError
from docxtpl import DocxTemplate
from fpdf import FPDF
from macs.models import Department, Position

from employees import access
from employees.models import CompanySettings, EmployeeExt, HrOrder, JobRecord, OrderType
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
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"
PDF_ALIGN = {WD_ALIGN_PARAGRAPH.CENTER: "C", WD_ALIGN_PARAGRAPH.RIGHT: "R", WD_ALIGN_PARAGRAPH.JUSTIFY: "J"}
PT_MM = 25.4 / 72


class OrderDocError(Exception):
    """The Word template of this order type is missing or unreadable."""


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
    return str(model.objects.filter(pk=pk).values_list("name", flat=True).first() or "")


def _emptype_label(code: int | None) -> str:
    return dict(JobRecord._meta.get_field("emptype").flatchoices).get(code, "") if code is not None else ""


def _hire_day(order: HrOrder) -> datetime.date | None:
    first = order.employee.job_records.order_by("period").first()
    day: datetime.date | None = first.period.lower if first is not None else order.employee.first_hire_date
    return day


def build_context(order: HrOrder, user: User) -> dict[str, Any]:
    """Every placeholder of the order templates, as text."""
    employee, event = order.employee, order.event
    company = CompanySettings.get()
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
    }


def render_order(order: HrOrder, user: User) -> bytes:
    """The filled Word file of an order."""
    path = Path(settings.ORDER_TEMPLATES_DIR) / TEMPLATE_FILES[OrderType(order.order_type)]
    context = build_context(order, user)
    template = DocxTemplate(str(path))
    try:
        template.render(context, autoescape=True)  # the file is opened here, not in the constructor
    except (OSError, ValueError, PackageNotFoundError) as error:  # missing or not a .docx
        raise OrderDocError(str(path)) from error
    out = io.BytesIO()
    template.save(out)
    return out.getvalue()


def _pdf_fonts() -> tuple[str, str, str, str]:
    for files in settings.ORDER_PDF_FONT_SETS:
        if all(Path(f).is_file() for f in files):
            return tuple(files)  # type: ignore[return-value]
    raise OrderDocError("no Cyrillic font found (settings.ORDER_PDF_FONT_SETS)")


def render_pdf(order: HrOrder, user: User) -> bytes:
    """The same order as a PDF. Drawn from the filled Word file paragraph by paragraph (alignment, bold, size),
    because no Word or LibreOffice is available on the server; the layout is close to Word's, not identical."""
    word = Document(io.BytesIO(render_order(order, user)))
    section = word.sections[0]
    base_pt = word.styles["Normal"].font.size.pt if word.styles["Normal"].font.size else 11.0
    pdf = FPDF(unit="mm", format="A4")
    left, top, right, bottom = (
        m.mm if m is not None else 25.4
        for m in (section.left_margin, section.top_margin, section.right_margin, section.bottom_margin)
    )
    pdf.set_margins(left, top, right)
    pdf.set_auto_page_break(True, margin=bottom)
    for style, path in zip(("", "B", "I", "BI"), _pdf_fonts(), strict=True):
        pdf.add_font("Order", style, path)
    pdf.add_page()
    for paragraph in word.paragraphs:
        run = next((r for r in paragraph.runs if r.text.strip()), None)
        points = run.font.size.pt if run is not None and run.font.size else base_pt
        pdf.set_font(
            "Order",
            ("B" if run is not None and run.bold else "") + ("I" if run is not None and run.italic else ""),
            points,
        )
        height = points * PT_MM * 1.25
        if not paragraph.text.strip():
            pdf.ln(height)
            continue
        pdf.multi_cell(
            0,
            height,
            paragraph.text,
            align=PDF_ALIGN.get(paragraph.alignment, "L") if paragraph.alignment is not None else "L",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(1.5)
    return bytes(pdf.output())

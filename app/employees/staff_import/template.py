"""The blank staff spreadsheet the user fills in: one sheet, the field labels in row 1, one marked example row."""

import io
from datetime import date
from typing import cast

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from employees.staff_import.fields import FIELDS
from employees.staff_import.lists import SHEETS, ListSheet
from employees.staff_import.reader import EXAMPLE_MARK

SHEET = "Ажилтан"
DATE_FORMAT = "yyyy-mm-dd"
BOLD = Font(bold=True)
EXAMPLE_FONT = Font(italic=True, color="808080")
NOTE = "← Энэ «Жишээ» мөрийг импортлох үед алгасна. Устгаад эсвэл дарж бичээд өөрийн ажилтнуудаа доор оруулна уу."

# One sample value per field key. The first field's sample is the example mark, so the importer skips the row.
EXAMPLE: dict[str, str | int | date | None] = {
    "family_name": EXAMPLE_MARK,
    "given_name": "Бат",
    "register_no": "УБ00000000",
    "passport_no": "A00000000",
    "birth_date": date(1990, 1, 1),
    "gender": "Эрэгтэй",
    "work_phone": "70000000",
    "private_phone": "99000000",
    "email": "bat@example.com",
    "start": date(2020, 1, 1),
    "department": "Санхүү",
    "position": "Нягтлан бодогч",
    "branch": None,  # a lookup name is left empty: no value is guaranteed to exist in the lists
    "citizenship": None,
    "work_conditions": "Хэвийн",
    "clan_name": None,
    "phone2": None,
    "prior_service_years": 2,
    "probation_end": None,
    "employee_type": "Үндсэн",
    "contract_type": "Хугацаагүй",
    "contract_no": None,
    "contract_start": None,
    "contract_end": None,
    "work_schedule": None,  # lookup names are left empty: no value is guaranteed to exist in the lists
    "marital_status": None,
    "nationality": None,
    "education_level": None,
    "academic_degree": None,
    "social_origin": None,
    "housing_condition": None,
    "car_ownership": None,
    "clothing_size": None,
    "shoe_size": None,
    "elected_position": None,
    "blood_type": "A",
    "military_service": "Үгүй",
    "has_disability": "Үгүй",
    "base_salary": 1500000,
    "bank": None,
    "account_no": "1234567890",
    "social_insurance_no": "1234567",
    "health_insurance_no": "1234567",
    "taxpayer_no": "1234567",
    "insured_category": None,
}


# Sample cells of the example row on each list sheet, by (list kind, form field). A field that is not listed stays
# empty: a code-list name is never given, because no name is guaranteed to exist in the lists.
LIST_EXAMPLE: dict[tuple[str, str], str | int | date] = {
    ("family", "given_name"): "Сараа",
    ("family", "birth_date"): date(2015, 5, 5),
    ("relative", "given_name"): "Болд",
    ("relative", "description"): "Ах",
    ("education", "org_name"): "МУИС",
    ("education", "start_year"): 2008,
    ("education", "end_year"): 2012,
    ("before_work", "worked_place"): "Жишээ ХХК",
    ("before_work", "start_year"): 2013,
    ("before_work", "end_year"): 2019,
    ("certificate", "org_edu"): "Сургалтын төв",
    ("certificate", "certify_year"): 2021,
    ("training", "tr_type"): "Дотоод",
    ("training", "description"): "Excel сургалт",
    ("training", "start_year"): 2022,
    ("training", "amount"): 0,
    ("training", "pay_type"): "Байгууллага",
    ("award", "award_name"): "Шилдэг ажилтан",
    ("award", "award_date"): date(2023, 12, 20),
    ("address", "street"): "1-р хороо, 10-р байр",
    ("contact", "name"): "Дорж",
    ("contact", "relative"): "Аав",
    ("contact", "value"): "99000000",
}
LIST_NOTE = (
    "← Энэ «Жишээ» мөрийг алгасна. Эхний багана нь «Ажилтан» хуудасны регистр эсвэл паспортын дугаар байна. "
    "Зөвхөн энэ импортоор шинээр нэмэгдэх ажилтны мөр хадгалагдана."
)


def _list_sheet(ws: Worksheet, sheet: ListSheet) -> None:
    """One list sheet: the headings in row 1 and a marked example row."""
    headings = sheet.headings()
    for col, heading in enumerate(headings, start=1):
        ws.cell(row=1, column=col, value=heading).font = BOLD
        ws.column_dimensions[get_column_letter(col)].width = max(len(heading) + 4, 14)
    ws.cell(row=2, column=1, value=EXAMPLE_MARK).font = EXAMPLE_FONT
    for col, (name, _) in enumerate(sheet.columns, start=2):
        value = LIST_EXAMPLE.get((sheet.kind, name))
        cell = ws.cell(row=2, column=col, value=value)
        cell.font = EXAMPLE_FONT
        if isinstance(value, date):
            cell.number_format = DATE_FORMAT
    ws.cell(row=2, column=len(headings) + 2, value=LIST_NOTE).font = EXAMPLE_FONT
    ws.freeze_panes = "A2"


def template_bytes(include_salary: bool) -> bytes:
    """The template as an .xlsx file. Salary columns are only in it when `include_salary` is set."""
    fields = [field for field in FIELDS if include_salary or not field.needs_salary]

    wb = Workbook()
    ws = cast(Worksheet, wb.active)  # a new workbook always has its first sheet
    ws.title = SHEET

    for col, field in enumerate(fields, start=1):
        cell = ws.cell(row=1, column=col, value=field.label)
        cell.font = BOLD
        ws.column_dimensions[get_column_letter(col)].width = max(len(field.label) + 4, 14)

    for col, field in enumerate(fields, start=1):
        value = EXAMPLE[field.key]
        cell = ws.cell(row=2, column=col, value=value)
        cell.font = EXAMPLE_FONT
        if isinstance(value, date):
            cell.number_format = DATE_FORMAT

    # The note sits beside the example row, not below the data: a row below would be read as a data row.
    ws.cell(row=2, column=len(fields) + 2, value=NOTE).font = EXAMPLE_FONT
    ws.freeze_panes = "A2"

    for sheet in SHEETS:
        _list_sheet(wb.create_sheet(sheet.title), sheet)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

"""The blank staff spreadsheet the user fills in: one sheet, the field labels in row 1, one marked example row."""

import io
from datetime import date
from typing import cast

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from employees.staff_import.fields import FIELDS
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
    "base_salary": 1500000,
    "bank": None,
    "account_no": "1234567890",
    "social_insurance_no": "1234567",
    "health_insurance_no": "1234567",
    "taxpayer_no": "1234567",
    "insured_category": None,
}


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

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

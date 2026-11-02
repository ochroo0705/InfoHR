"""Turns one spreadsheet row into the values to import and the list of problems with it. Never touches the database."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from macs.models import Employee

from employees.staff_import.derive import derive_from_register
from employees.staff_import.fields import BY_KEY, FIELDS, ImportField
from employees.staff_import.matching import REGISTER_OR_PASSPORT_LABEL, REQUIRED_KEYS
from employees.validators import normalize_register_no, validate_register_no

DATE_FORMATS: dict[str, tuple[str, str]] = {
    "iso": ("yyyy-mm-dd", "%Y-%m-%d"),
    "slash": ("yyyy/mm/dd", "%Y/%m/%d"),
    "dmy": ("dd.mm.yyyy", "%d.%m.%Y"),
}

# Text fields that are real Employee attributes. Their maximum length is read from the model.
EMPLOYEE_TEXT_KEYS = (
    "family_name",
    "given_name",
    "register_no",
    "passport_no",
    "work_phone",
    "private_phone",
    "email",
    "account_no",
    "social_insurance_no",
    "health_insurance_no",
    "taxpayer_no",
)
MAX_LENGTH: dict[str, int | None] = {
    key: getattr(Employee._meta.get_field(key), "max_length", None) for key in EMPLOYEE_TEXT_KEYS
}

# A default never fills these: a default identity or birth date would be the same for every row,
# and a default birth date or gender would beat the derivation from the register number.
NO_DEFAULT_KEYS = ("register_no", "passport_no", "birth_date", "gender")
PHONE_KEYS = ("work_phone", "private_phone")
PHONE_TEXT = re.compile(r"[0-9+\- ]+")
EMAIL_TEXT = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Money: comma groups (1,000,000), space or apostrophe groups (1 000 000), or plain digits; an optional dot decimal.
MONEY_FORMS = (
    re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
    re.compile(r"\d{1,3}(?:[\s'’]\d{3})+(?:\.\d+)?"),
    re.compile(r"\d+(?:\.\d+)?"),
)
MONEY_SEPARATORS = re.compile(r"[\s,'’]")
PASSPORT_SPACES = re.compile(r"\s+")
GENDER_CODES = {
    "эрэгтэй": "M",
    "эр": "M",
    "male": "M",
    "m": "M",
    "эмэгтэй": "F",
    "эм": "F",
    "female": "F",
    "f": "F",
}


@dataclass
class ParsedRow:
    number: int
    cells: list[object]
    values: dict[str, Any]
    errors: list[str]
    status: str = "new"
    note: str = ""


def _is_blank(raw: object) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _as_text(raw: object) -> str:
    """Text of a cell. A whole-number float (Excel stores 99112233 as 99112233.0) loses its '.0'."""
    if _is_blank(raw):
        return ""
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw).strip()


def _raw_values(cells: list[object], mapping: dict[str, str], defaults: dict[str, str]) -> dict[str, object]:
    """The non-blank raw value of each field: the mapped column first, then the default for that field."""
    raw: dict[str, object] = {}
    for index, key in mapping.items():
        if key not in BY_KEY:
            continue
        try:
            position = int(index)
        except ValueError:
            continue
        if 0 <= position < len(cells) and not _is_blank(cells[position]):
            raw[key] = cells[position]
    for key, value in defaults.items():
        text = value if isinstance(value, str) else str(value)
        if key in BY_KEY and key not in NO_DEFAULT_KEYS and key not in raw and not _is_blank(text):
            raw[key] = text
    return raw


def _too_long(field: ImportField, text: str, errors: list[str]) -> bool:
    limit = MAX_LENGTH.get(field.key)
    if limit is not None and len(text) > limit:
        errors.append(f"{field.label} хэт урт байна (дээд тал {limit} тэмдэгт)")
        return True
    return False


def _text(field: ImportField, raw: object, errors: list[str]) -> str | None:
    text = _as_text(raw)
    if _too_long(field, text, errors):
        return None
    return text


def _register_no(field: ImportField, raw: object, errors: list[str]) -> str | None:
    text = normalize_register_no(_as_text(raw))
    if _too_long(field, text, errors):
        return None
    try:
        validate_register_no(text)
    except ValidationError as exc:
        errors.append(exc.messages[0])
        return None
    return text


def _passport_no(field: ImportField, raw: object, errors: list[str]) -> str | None:
    text = PASSPORT_SPACES.sub("", _as_text(raw)).upper()
    if _too_long(field, text, errors):
        return None
    return text


def _phone(field: ImportField, raw: object, errors: list[str]) -> str | None:
    text = _as_text(raw)
    if _too_long(field, text, errors):
        return None
    if not PHONE_TEXT.fullmatch(text) or not any(char.isdigit() for char in text):
        errors.append(f"{field.label} буруу байна (зөвхөн тоо, +, - болон зай)")
        return None
    return text


def _email(field: ImportField, raw: object, errors: list[str]) -> str | None:
    text = _as_text(raw)
    if _too_long(field, text, errors):
        return None
    if not EMAIL_TEXT.fullmatch(text):
        errors.append(f"{field.label} буруу байна")
        return None
    return text


def _date(field: ImportField, raw: object, date_format: str, errors: list[str]) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw.strip(), DATE_FORMATS[date_format][1]).date()
        except ValueError:
            pass
    errors.append(f"{field.label} буруу байна ({DATE_FORMATS[date_format][0]} хэлбэрээр бичнэ үү)")
    return None


def _money(field: ImportField, raw: object, errors: list[str]) -> Decimal | None:
    text = _as_text(raw)
    negative = text.startswith("-")
    body = text[1:].strip() if negative else text
    if not any(form.fullmatch(body) for form in MONEY_FORMS):
        errors.append(f"{field.label} буруу байна (зөвхөн тоо)")
        return None
    amount = Decimal(MONEY_SEPARATORS.sub("", body))
    if negative and amount != 0:
        errors.append(f"{field.label} сөрөг байж болохгүй")
        return None
    return amount


def _gender(field: ImportField, raw: object, errors: list[str]) -> str | None:
    code = GENDER_CODES.get(_as_text(raw).lower())
    if code is None:
        errors.append(f"{field.label} буруу байна (эрэгтэй эсвэл эмэгтэй)")
    return code


def _parse_value(field: ImportField, raw: object, date_format: str, errors: list[str]) -> Any:
    if isinstance(raw, bool) and field.kind not in ("date", "money"):
        errors.append(f"{field.label} буруу байна")
        return None
    if field.key == "register_no":
        return _register_no(field, raw, errors)
    if field.key == "passport_no":
        return _passport_no(field, raw, errors)
    if field.kind == "date":
        return _date(field, raw, date_format, errors)
    if field.kind == "money":
        return _money(field, raw, errors)
    if field.kind == "gender":
        return _gender(field, raw, errors)
    if field.key in PHONE_KEYS:
        return _phone(field, raw, errors)
    if field.key == "email":
        return _email(field, raw, errors)
    return _text(field, raw, errors)


def _check_identity(row: ParsedRow, raw: dict[str, object]) -> None:
    """Register or passport is required. A valid register number fills birth date and gender, else they are required."""
    if "register_no" not in raw:
        if "passport_no" not in raw:
            row.errors.append(f"{REGISTER_OR_PASSPORT_LABEL} дутуу байна")
            return
        for key in ("birth_date", "gender"):
            if key not in raw:
                row.errors.append(f"{BY_KEY[key].label} дутуу байна")
        return
    if "register_no" not in row.values:
        return
    born, gender = derive_from_register(row.values["register_no"])
    # A register that gives no usable date or gender counts as underivable: the file must supply the missing one.
    if "birth_date" not in raw:
        if born is not None:
            row.values["birth_date"] = born
        else:
            row.errors.append(f"{BY_KEY['birth_date'].label} дутуу байна")
    if "gender" not in raw:
        if gender is not None:
            row.values["gender"] = gender
        else:
            row.errors.append(f"{BY_KEY['gender'].label} дутуу байна")


def parse_row(
    number: int,
    cells: list[object],
    mapping: dict[str, str],
    defaults: dict[str, str],
    date_format: str,
) -> ParsedRow:
    """Parse one row. `mapping` is {column index as str: field key}. Problems go into `errors`; nothing raises."""
    row = ParsedRow(number=number, cells=cells, values={}, errors=[])
    raw = _raw_values(cells, mapping, defaults)
    chosen_format = date_format if date_format in DATE_FORMATS else "iso"
    for field in FIELDS:
        if field.key not in raw:
            if field.key in REQUIRED_KEYS:
                row.errors.append(f"{field.label} дутуу байна")
            continue
        value = _parse_value(field, raw[field.key], chosen_format, row.errors)
        if value is not None:
            row.values[field.key] = value
    _check_identity(row, raw)
    return row

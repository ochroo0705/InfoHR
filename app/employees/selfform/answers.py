"""Validation of what a self-form employee typed (person, education, family, one emergency contact).

Two modes:
- final=True (confirm): every part is checked by the real form the HR side uses (EmployeeForm fields,
  EducationRowForm, FamilyRowForm, HireContactForm), so a stored answer cannot hold a value the hire form or the
  Personal tab would refuse. Answers are plain JSON: dates as ISO text, choice fields as integer ids.
- final=False (draft): nothing the employee typed is dropped or parsed. Known keys are kept as trimmed text, capped
  to the form's length. Only the shape checks and the caps can refuse a draft.

Spec: docs/superpowers/specs/2026-11-08-employee-self-form-design.md
"""

import base64
import copy
import json
from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Model
from PIL import Image

from employees.forms import EducationRowForm, EmployeeForm, FamilyRowForm, HireContactForm, PersonalRowForm
from employees.images import shrink_photo
from employees.validators import normalize_register_no, validate_register_no

PERSON_FIELDS = ("family_name", "given_name", "register_no", "birth_date", "gender", "work_phone", "clan_name", "email")
REQUIRED_PERSON = ("family_name", "given_name", "register_no", "birth_date", "gender", "work_phone")
EDUCATION_FIELDS = ("org_name", "start_year", "end_year", "edu_level", "profession_type")
FAMILY_FIELDS = ("relation", "given_name", "surname", "birth_date", "job", "phone")
CONTACT_FIELDS = ("contact_type", "name", "relative", "value")

MAX_EDUCATION = 10
MAX_FAMILY = 20
MAX_BODY_BYTES = 200_000
MAX_PHOTO_BYTES = 5_000_000
DRAFT_TEXT_MAX = 200  # length cap for a draft value whose form field has no max_length

MSG_SHAPE = "Мэдээллийн хэлбэр буруу байна."
MSG_BODY_TOO_LARGE = "Мэдээллийн хэмжээ хэт их байна."
MSG_EDUCATION_CAP = f"Боловсролын мөр {MAX_EDUCATION}-аас ихгүй байх ёстой."
MSG_FAMILY_CAP = f"Гэр бүлийн мөр {MAX_FAMILY}-аас ихгүй байх ёстой."
MSG_PHOTO_TOO_LARGE = f"Зураг {MAX_PHOTO_BYTES // 1_000_000} МБ-аас ихгүй байх ёстой."
MSG_PHOTO_NOT_IMAGE = "Зөвхөн JPEG эсвэл PNG зураг хүлээн авна. Зургаа дахин сонгоно уу."
MSG_PHOTO_TOO_MANY_PIXELS = "Зургийн пиксел хэт олон байна. Жижиг зураг сонгоно уу."
PHOTO_FORMATS = ("JPEG", "PNG")  # the only formats the public form accepts
MAX_PHOTO_PIXELS = 25_000_000  # width * height, read from the header before any pixel is decoded


class AnswerErrors(Exception):
    """Refused answers. `errors` maps a path such as `person.register_no` or `education.2.start_year` to messages."""

    def __init__(self, errors: dict[str, list[str]]) -> None:
        super().__init__(errors)
        self.errors = errors


class _PersonForm(forms.Form):
    """The person fields, copied from EmployeeForm so the labels, lengths and choices are the hire form's own."""

    def __init__(self, data: dict[str, Any], *, final: bool) -> None:
        super().__init__(data)
        built = EmployeeForm().fields
        for name in PERSON_FIELDS:
            field = copy.deepcopy(built[name])
            field.required = final and name in REQUIRED_PERSON
            self.fields[name] = field

    def clean_register_no(self) -> str | None:
        # Same rule as EmployeeForm.clean_register_no, minus the duplicate check (HR sees that on the hire page).
        raw = self.cleaned_data.get("register_no") or ""
        if not raw.strip():
            return None
        value = normalize_register_no(raw)
        validate_register_no(value)
        return value


class _EducationRow(EducationRowForm):
    """The education row fields the self-form asks for. The other Personal-tab columns are left out."""

    COLUMNS = tuple(column for column in EducationRowForm.COLUMNS if column[0] in EDUCATION_FIELDS)  # type: ignore[assignment]
    LOADED = ()  # type: ignore[assignment]
    country = None  # type: ignore[assignment]
    qualification_type = None  # type: ignore[assignment]
    grade = None  # type: ignore[assignment]
    credit_score = None  # type: ignore[assignment]
    diplom_number = None  # type: ignore[assignment]


def _plain(value: Any) -> Any:
    """A cleaned value as plain JSON: model instances become ids, dates ISO text, decimals text."""
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _text(value: Any, limit: int) -> str:
    """A draft value as typed: text, trimmed, capped. No parsing."""
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _limits(form: forms.Form, names: tuple[str, ...]) -> dict[str, int]:
    """The real form field's max_length for each name, or DRAFT_TEXT_MAX where the field has none."""
    out: dict[str, int] = {}
    for name in names:
        max_length = getattr(form.fields.get(name), "max_length", None)
        out[name] = max_length if isinstance(max_length, int) else DRAFT_TEXT_MAX
    return out


def _form_errors(prefix: str, form: forms.Form) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, messages in form.errors.items():
        key = prefix if name == NON_FIELD_ERRORS else f"{prefix}.{name}"
        out[key] = [str(message) for message in messages]
    return out


def _section(raw: dict[str, Any], key: str, errors: dict[str, list[str]]) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors[key] = [MSG_SHAPE]
        return {}
    return value


def _list(raw: dict[str, Any], key: str, cap: int, cap_message: str, errors: dict[str, list[str]]) -> list[Any]:
    """The posted rows of one list, or [] after recording a shape or cap error."""
    rows = raw.get(key) or []
    if not isinstance(rows, list):
        errors[key] = [MSG_SHAPE]
        return []
    if len(rows) > cap:
        errors[key] = [cap_message]
        return []
    return rows


def _final_rows(
    raw: dict[str, Any],
    key: str,
    fields: tuple[str, ...],
    form_class: type[PersonalRowForm],
    cap: int,
    cap_message: str,
    errors: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Validated rows of one list. An all-blank row is skipped; every other row must validate."""
    kept: list[dict[str, Any]] = []
    for index, row in enumerate(_list(raw, key, cap, cap_message, errors)):
        if not isinstance(row, dict):
            errors[f"{key}.{index}"] = [MSG_SHAPE]
            continue
        data = {name: row.get(name) for name in fields}
        if all(_blank(value) for value in data.values()):
            continue
        form = form_class(data, adding=True)
        if form.is_valid():
            kept.append({name: _plain(form.cleaned_data.get(name)) for name in fields})
        else:
            errors |= _form_errors(f"{key}.{index}", form)
    return kept


def _draft_rows(
    raw: dict[str, Any],
    key: str,
    fields: tuple[str, ...],
    limit_form: forms.Form,
    cap: int,
    cap_message: str,
    errors: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Every posted row with text values, trimmed and capped. An all-blank row is skipped."""
    limits = _limits(limit_form, fields)
    kept: list[dict[str, Any]] = []
    for index, row in enumerate(_list(raw, key, cap, cap_message, errors)):
        if not isinstance(row, dict):
            errors[f"{key}.{index}"] = [MSG_SHAPE]
            continue
        data = {name: _text(row.get(name), limits[name]) for name in fields}
        if all(value == "" for value in data.values()):
            continue
        kept.append(data)
    return kept


def _final_person(person_raw: dict[str, Any], errors: dict[str, list[str]]) -> dict[str, Any]:
    form = _PersonForm({name: person_raw.get(name) for name in PERSON_FIELDS}, final=True)
    if not form.is_valid():
        errors |= _form_errors("person", form)
        return {}
    return {name: _plain(value) for name, value in form.cleaned_data.items()}


def _final_contact(contact_raw: dict[str, Any], errors: dict[str, list[str]]) -> dict[str, Any]:
    form = HireContactForm({name: contact_raw.get(name) for name in CONTACT_FIELDS}, adding=True)
    if not form.is_valid():
        errors |= _form_errors("contact", form)
        return {}
    if not form.filled():
        return {}
    return {name: _plain(form.cleaned_data.get(name)) for name in CONTACT_FIELDS}


def validate_answers(raw: dict[str, Any], *, final: bool) -> dict[str, Any]:
    """Answers {"person", "education", "family", "contact"}, or AnswerErrors.

    final=True: every field and row must validate; the result holds cleaned values (ISO dates, integer ids).
    final=False (draft): nothing typed is dropped; values are kept as trimmed text. Only the body size, the shape
    and the row caps can refuse a draft.
    """
    if not isinstance(raw, dict):
        raise AnswerErrors({"body": [MSG_SHAPE]})
    if len(json.dumps(raw, default=str).encode()) > MAX_BODY_BYTES:
        raise AnswerErrors({"body": [MSG_BODY_TOO_LARGE]})

    errors: dict[str, list[str]] = {}
    person_raw = _section(raw, "person", errors)
    contact_raw = _section(raw, "contact", errors)

    if final:
        person = _final_person(person_raw, errors)
        education = _final_rows(
            raw, "education", EDUCATION_FIELDS, _EducationRow, MAX_EDUCATION, MSG_EDUCATION_CAP, errors
        )
        family = _final_rows(raw, "family", FAMILY_FIELDS, FamilyRowForm, MAX_FAMILY, MSG_FAMILY_CAP, errors)
        contact = _final_contact(contact_raw, errors)
    else:
        person = {
            name: _text(person_raw.get(name), limit) for name, limit in _limits(EmployeeForm(), PERSON_FIELDS).items()
        }
        education = _draft_rows(
            raw, "education", EDUCATION_FIELDS, EducationRowForm(), MAX_EDUCATION, MSG_EDUCATION_CAP, errors
        )
        family = _draft_rows(raw, "family", FAMILY_FIELDS, FamilyRowForm(), MAX_FAMILY, MSG_FAMILY_CAP, errors)
        contact_limits = _limits(HireContactForm(), CONTACT_FIELDS)
        contact = {name: _text(contact_raw.get(name), contact_limits[name]) for name in CONTACT_FIELDS}

    if errors:
        raise AnswerErrors(errors)
    return {"person": person, "education": education, "family": family, "contact": contact}


def store_photo(upload: UploadedFile) -> str:
    """The photo as base64 text of a shrunk JPEG (EXIF dropped, at most 600 px). Refuses non-images and big files."""
    if (upload.size or 0) > MAX_PHOTO_BYTES:
        raise AnswerErrors({"photo": [MSG_PHOTO_TOO_LARGE]})
    upload.seek(0)
    try:
        # Only the header is read here: the format and the size are checked before shrink_photo decodes anything.
        with Image.open(upload, formats=PHOTO_FORMATS) as probe:
            if probe.format not in PHOTO_FORMATS:
                raise AnswerErrors({"photo": [MSG_PHOTO_NOT_IMAGE]})
            width, height = probe.size
    except AnswerErrors:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):  # not a JPEG or PNG, or a bomb
        raise AnswerErrors({"photo": [MSG_PHOTO_NOT_IMAGE]}) from None
    if width * height > MAX_PHOTO_PIXELS:
        raise AnswerErrors({"photo": [MSG_PHOTO_TOO_MANY_PIXELS]})
    upload.seek(0)
    try:
        photo = shrink_photo(upload)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):  # bytes Pillow cannot read, or a bomb
        raise AnswerErrors({"photo": [MSG_PHOTO_NOT_IMAGE]}) from None
    return base64.b64encode(photo.read()).decode("ascii")


def rows_for_confirm(answers: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(kind, columns, ext) for each education and family row, ready for personal_writes.add.

    Each stored row is run through the real row form again, so a code list that changed since the employee
    submitted is reported here instead of failing inside the write.
    """
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    errors: dict[str, list[str]] = {}
    sections: tuple[tuple[str, type[PersonalRowForm], list[dict[str, Any]]], ...] = (
        ("education", _EducationRow, answers.get("education") or []),
        ("family", FamilyRowForm, answers.get("family") or []),
    )
    for kind, form_class, rows in sections:
        for index, row in enumerate(rows):
            form = form_class(dict(row), adding=True)
            if not form.is_valid():
                errors |= _form_errors(f"{kind}.{index}", form)
                continue
            columns, ext = form.values()
            out.append((kind, columns, ext))
    if errors:
        raise AnswerErrors(errors)
    return out

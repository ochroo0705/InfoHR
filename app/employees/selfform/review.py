"""The HR side of a submitted self-form, read only: the values the hire page starts with, the review panel, and the
register-number duplicate check. Nothing here writes; confirming the hire is a separate step.

Spec: docs/superpowers/specs/2026-11-08-employee-self-form-design.md (section "How HR reviews").
"""

import json
from datetime import date
from typing import Any

from accounts.models import User
from django.db.models import F, Func, QuerySet, Value
from django.db.models.functions import Upper
from macs.dialect import is_firebird
from macs.models import ContactType, EducationLevel, FamilyRelation, ProfessionType

from employees import access
from employees.forms import ContactRowForm, EducationRowForm, FamilyRowForm
from employees.models import Employee, SelfFormInvitation
from employees.selfform.answers import CONTACT_FIELDS, EDUCATION_FIELDS, FAMILY_FIELDS, PERSON_FIELDS
from employees.validators import normalize_register_no

UNKNOWN = "«?»"  # a code-list id that no longer exists in its list; shown instead of the id


def _section(sub: SelfFormInvitation, key: str) -> dict[str, Any]:
    """One object of the stored answers, or {} when the stored JSON is missing or has another shape."""
    try:
        answers = json.loads(sub.answers or "{}")
    except ValueError:
        return {}
    value = answers.get(key) if isinstance(answers, dict) else None
    return value if isinstance(value, dict) else {}


def _rows(sub: SelfFormInvitation, key: str) -> list[dict[str, Any]]:
    """One list of the stored answers (education or family rows); anything that is not a row object is skipped."""
    try:
        answers = json.loads(sub.answers or "{}")
    except ValueError:
        return []
    value = answers.get(key) if isinstance(answers, dict) else None
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _int(value: Any) -> int | None:
    """A code-list id as an int, or None when the value is not a plain positive-looking integer."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def person_initial(sub: SelfFormInvitation) -> dict[str, Any]:
    """The eight person fields as initial values of the hire form (birth date as a date)."""
    person = _section(sub, "person")
    initial: dict[str, Any] = {}
    for name in PERSON_FIELDS:
        value = person.get(name)
        if value in (None, ""):
            continue
        if name == "birth_date":
            try:
                initial[name] = date.fromisoformat(str(value))
            except ValueError:
                pass  # a value the hire form cannot show is left blank for HR to type
            continue
        initial[name] = str(value)
    return initial


def contact_initial(sub: SelfFormInvitation) -> dict[str, Any]:
    """The emergency contact as initial values of the hire form's contact fields; {} when the contact is empty."""
    contact = _section(sub, "contact")
    initial: dict[str, Any] = {}
    contact_type = _int(contact.get("contact_type"))
    if contact_type is not None:
        initial["contact_type"] = contact_type
    for name in ("name", "relative", "value"):
        if contact.get(name):
            initial[name] = str(contact[name])
    return initial


def _names(rows: QuerySet[Any], values: list[Any]) -> dict[int, str]:
    """Name of each code-list row (of `rows`) whose id appears in `values`. Rows without a name are left out, so
    they show as unknown."""
    ids = {pk for pk in (_int(value) for value in values) if pk is not None}
    if not ids:
        return {}
    return {pk: row.name for pk, row in rows.in_bulk(ids).items() if row.name}


def _coded(names: dict[int, str], value: Any) -> str:
    """The name of a code-list id. Blank is empty; any other value that is not a known id shows as unknown."""
    if value in (None, ""):
        return ""
    pk = _int(value)
    if pk is None:
        return UNKNOWN
    return names.get(pk, UNKNOWN)


def _pairs(
    row: dict[str, Any], fields: tuple[str, ...], labels: dict[str, Any], coded: dict[str, dict[int, str]]
) -> list[tuple[str, str]]:
    """(label, text) for each non-empty value of one row. Code-list fields show the list's name."""
    pairs: list[tuple[str, str]] = []
    for name in fields:
        value = _coded(coded[name], row.get(name)) if name in coded else _text(row.get(name))
        if value:
            pairs.append((str(labels[name].label), value))
    return pairs


def panel(sub: SelfFormInvitation) -> dict[str, Any]:
    """Display data for the read-only review panel. Every value is plain text; the template escapes it."""
    education = _rows(sub, "education")
    family = _rows(sub, "family")
    contact = _section(sub, "contact")
    education_labels = EducationRowForm().fields
    family_labels = FamilyRowForm().fields
    contact_labels = ContactRowForm().fields
    levels = _names(EducationLevel.objects.all(), [row.get("edu_level") for row in education])
    professions = _names(ProfessionType.objects.all(), [row.get("profession_type") for row in education])
    relations = _names(FamilyRelation.objects.all(), [row.get("relation") for row in family])
    contact_types = _names(ContactType.objects.all(), [contact.get("contact_type")])

    education_pairs = [
        _pairs(row, EDUCATION_FIELDS, education_labels, {"edu_level": levels, "profession_type": professions})
        for row in education
    ]
    family_pairs = [_pairs(row, FAMILY_FIELDS, family_labels, {"relation": relations}) for row in family]
    contact_pairs = _pairs(contact, CONTACT_FIELDS, contact_labels, {"contact_type": contact_types})
    return {
        "education": [pairs for pairs in education_pairs if pairs],
        "family": [pairs for pairs in family_pairs if pairs],
        "contact": contact_pairs,
        "has_photo": bool(sub.photo_b64),
        "submitted_at": sub.submitted_at,
        "hr_note": sub.hr_note,
    }


def _employee_with_register(value: str) -> Employee | None:
    """The employee whose stored register number, normalised, equals `value` (the same rule as the hire form)."""
    if is_firebird():
        # Firebird has no REGEXP_REPLACE: read every stored number and normalise it here (as EmployeeForm does).
        for employee in Employee.objects.exclude(register_no__isnull=True).only("pk", "register_no"):
            if normalize_register_no(employee.register_no or "") == value:
                return employee
        return None
    return (
        Employee.objects.annotate(
            register_norm=Func(Upper(F("register_no")), Value(r"\s+"), Value(""), Value("g"), function="regexp_replace")
        )
        .filter(register_norm=value)
        .first()
    )


def duplicate_for(sub: SelfFormInvitation, user: User) -> dict[str, Any] | None:
    """The existing employee with the submitted register number, or None. The employee object is given only when
    `user` may see that employee; otherwise `visible` is False and no name or link is passed on."""
    raw = _section(sub, "person").get("register_no")
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = _employee_with_register(normalize_register_no(raw))
    if match is None:
        return None
    visible = access.visible_employees(user).filter(pk=match.pk).first()
    return {"employee": visible, "visible": visible is not None}

"""The employee fields the assistant may name in an answer.

One registry, built from the same form definitions the employee screens use, so a field the assistant can read is a
field a person can see on a page. The model never sees a value: code reads the value for the asker (see actions) and
builds the address. Fields left out on purpose are listed in EXCLUDED with the reason.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Literal

from accounts.models import User
from django import forms
from django.db import models
from employees.access import can_view_personal, can_view_salary, is_own, visible_employees
from employees.forms import EmployeeForm, SalaryInsuranceForm
from employees.models import JobRecord
from employees.money import group
from employees.palette import _fold
from employees.sections import SECTIONS
from employees.services import history
from macs.models import Employee
from reports.staff_list import REPORT as STAFF_REPORT
from reports.table import allowed_columns

Tab = Literal["work", "personal", "salary"]
Source = Literal["form", "salary_form", "job", "salary"]


@dataclass(frozen=True)
class AskableField:
    """One field the assistant can answer about: its key, the Mongolian label, the words people say for it, and the
    tab it sits on (the employee page's tab, which is also the anchor of the address)."""

    key: str
    label: str
    synonyms: tuple[str, ...]
    tab: Tab
    source: Source


# Names deliberately not askable (field name -> reason). Every name on an employee page or job record is here or below.
EXCLUDED: dict[str, str] = {
    "photo": "a picture, not a value to read out",
    "photo_clear": "the clear box of the picture upload",
    "emptype": "the numeric type code (1, 5, 9) used by the staff-table filter; no employee page shows it, the work "
    "tab shows the type name (employee_type)",
    "status": "one status per job row in the job history table, so no single current value is on the page to point "
    "at (the highlight would land on an old row)",
}

# Shown on the employee page only once the person exists (EmployeeForm._add_edit_fields), so the empty form lacks them.
EDIT_ONLY = ("code", "branch", "foreign_emp", "sector_years")

# Hand-written words people use for a field, on top of its label. Fields not listed use the label alone.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "work_phone": ("ажлын утас", "утас"),
    "private_phone": ("гар утас", "хувийн утас", "утас"),
    "phone2": ("нэмэлт утас", "утас"),
    "email": ("и-мэйл", "имэйл", "цахим шуудан"),
    "birth_date": ("төрсөн өдөр", "төрсөн он"),
    "register_no": ("регистр", "регистрийн дугаар"),
    "position": ("албан тушаал", "ажлын байр"),
    "department": ("хэлтэс", "алба"),
    "manager": ("шууд удирдлага", "дарга", "менежер"),
    "contract_end": ("гэрээний дуусах", "гэрээ дуусах"),
    "first_hire_date": ("ажилд орсон", "ажилд орсон өдөр"),
    "account_no": ("данс", "дансны дугаар"),
    "base_salary": ("цалин",),
}


def _verbose_name(model: type[models.Model], name: str) -> str:
    return str(getattr(model._meta.get_field(name), "verbose_name", name))


@cache
def all_fields() -> tuple[AskableField, ...]:
    """Every askable field, once, in the order the screens show them (forms first, then salary, then job)."""
    personal = {name for names in SECTIONS.values() for name in names}
    salary_names = set(SalaryInsuranceForm(employee=None).fields) | {"base_salary"}
    found: list[AskableField] = []
    seen: set[str] = set()

    def add(key: str, label: str, source: Source) -> None:
        if key in EXCLUDED or key in seen:
            return
        seen.add(key)
        tab: Tab = "personal" if key in personal else "salary" if key in salary_names else "work"
        found.append(AskableField(key, label.strip() or key, SYNONYMS.get(key, ()), tab, source))

    for key, field in EmployeeForm(employee=None, user=None).fields.items():
        add(key, str(field.label or key), "form")
    for key in EDIT_ONLY:
        add(key, _verbose_name(Employee, key), "form")
    for key, field in SalaryInsuranceForm(employee=None).fields.items():
        add(key, str(field.label or key), "salary_form")
    for key in JobRecord.JOB_FIELDS:
        add(key, _verbose_name(JobRecord, key), "job")
    add("base_salary", "Үндсэн цалин", "salary")
    return tuple(found)


@cache
def _by_key() -> dict[str, AskableField]:
    return {field.key: field for field in all_fields()}


def field_by_key(key: str) -> AskableField | None:
    return _by_key().get(key)


_WORD = re.compile(r"\w+")


def words(text: str) -> set[str]:
    return set(_WORD.findall(_fold(text)))


def same_word(asked: str, term: str) -> bool:
    """Equal words, or one is the start of the other (Mongolian adds endings: «утасны» is «утас» + «ны»)."""
    if asked == term:
        return True
    short, long = sorted((asked, term), key=len)
    return len(short) >= 3 and long.startswith(short)


def hints_for(text: str, limit: int = 15) -> list[AskableField]:
    """The fields whose label or synonyms share a word with `text`, best match first, at most `limit`."""
    asked = words(text)
    if not asked:
        return []
    scored: list[tuple[int, AskableField]] = []
    for field in all_fields():
        terms = words(field.label)
        for synonym in field.synonyms:
            terms |= words(synonym)
        score = sum(1 for word in asked if any(same_word(word, term) for term in terms))
        if score:
            scored.append((score, field))
    scored.sort(key=lambda pair: -pair[0])  # stable: registry order breaks ties
    return [field for _, field in scored[:limit]]


MAX_TEXT = 200  # characters of a value that are ever shown
YES = "Тийм"
NO = "Үгүй"


@dataclass(frozen=True)
class FieldValue:
    """One field's value for one employee, as text. `text == ""` means no value is recorded."""

    label: str
    text: str


def _link_text(user: User, found: models.Model | None) -> str:
    """The name of a linked row. A linked employee the asker may not see gives "", never the name (a manager outside
    the asker's data scope is no answer, not a leak)."""
    if found is None:
        return ""
    if isinstance(found, Employee) and not visible_employees(user).filter(pk=found.pk).exists():
        return ""
    return str(found)


def _text(user: User, value: object, form_field: forms.Field | None = None) -> str:
    """A stored value as the text a person reads: the label for a choice, the name for a link, «Тийм» or «Үгүй» for a
    yes/no, YYYY-MM-DD for a date, grouped digits for an amount. An empty value is ""."""
    if value is None or value == "" or value == []:
        return ""
    if isinstance(value, bool):
        return YES if value else NO
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return group(value)
    if isinstance(form_field, forms.ModelChoiceField):
        # The form's own queryset: a choice the form would not offer (out of scope) is found nowhere and reads empty.
        queryset = form_field.queryset
        found = None if queryset is None else queryset.filter(pk=value).first()
        return _link_text(user, found)
    if isinstance(form_field, forms.ChoiceField):
        pairs: list[tuple[object, object]] = list(getattr(form_field, "choices", None) or [])
        labels = {str(code): str(label) for code, label in pairs}
        return labels.get(str(value), str(value))
    if isinstance(value, models.Model):
        return _link_text(user, value)
    return str(value)


def _record_text(user: User, record: models.Model, key: str) -> str:
    """A model row's value: the display label for a field with choices, otherwise the same text as a form value."""
    if getattr(record._meta.get_field(key), "choices", None):
        return str(getattr(record, f"get_{key}_display")())
    return _text(user, getattr(record, key))


def _staff_column_allowed(user: User, key: str) -> bool:
    """A key that is also a staff-table column needs that column's permission too (the stricter of the two rules)."""
    if key not in {column.key for column in STAFF_REPORT.columns}:
        return True
    return key in {column.key for column in allowed_columns(STAFF_REPORT, user)}


def _may_read(user: User, employee: Employee, field: AskableField) -> bool:
    if field.tab == "personal" and not can_view_personal(user, employee):
        return False
    if field.tab == "salary" and not can_view_salary(user):
        return False
    # A person reads their own page's fields; the staff-table column rule guards other people's rows only.
    return is_own(user, employee) or _staff_column_allowed(user, field.key)


def _value_text(user: User, employee: Employee, field: AskableField, day: date) -> str:
    if field.source == "job":
        record = history.job_on(employee, day)
        return "" if record is None else _record_text(user, record, field.key)
    if field.source == "salary":
        salary = history.salary_on(employee, day)
        return "" if salary is None else _text(user, getattr(salary, field.key))
    if field.source == "salary_form":
        salary_form = SalaryInsuranceForm(employee=employee)
        return _text(user, salary_form.initial.get(field.key), salary_form.fields.get(field.key))
    form = EmployeeForm(employee=employee, user=user)
    return _text(user, form.initial.get(field.key), form.fields.get(field.key))


def field_value(user: User, employee: Employee, key: str, day: date) -> FieldValue | None:
    """The value of one field for the asker, or None when the key is unknown or the asker may not read it. Never
    raises for a missing value: that is a FieldValue with `text == ""`."""
    field = field_by_key(key)
    if field is None or not _may_read(user, employee, field):
        return None
    return FieldValue(label=field.label, text=_value_text(user, employee, field, day).strip()[:MAX_TEXT])

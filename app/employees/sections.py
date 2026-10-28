"""The personal tab's sections: each is one form that saves only its own fields (views.personal_section)."""

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Model
from django.forms import CheckboxInput, Form
from django.http import QueryDict
from macs.models import Employee

from employees.forms import BIRTH_FIELDS, EmployeeForm, PersonalRowForm
from employees.models import ext_of

SECTIONS: dict[str, tuple[str, ...]] = {
    "identity": (
        "register_no",
        "birth_date",
        "gender",
        "clan_name",
        "citizenship",
        "foreign_emp",
        "passport_no",
        "marital_status",
        "birth_city",
        "birth_district",
        "birth_place_text",
    ),
    "contact": ("private_phone", "phone2"),
    "education": ("education_level", "academic_degree"),
    "other": (
        "prior_service_years",
        "prior_service_months",
        "blood_type",
        "blood_rh",
        "military_service",
        "social_origin",
        "housing_condition",
        "living_standard",
        "car_ownership",
        "clothing_size",
        "shoe_size",
        "elected_position",
    ),
}
TITLES = {
    "identity": "Хувийн мэдээлэл",
    "contact": "Холбоо барих, хаяг",
    "education": "Боловсрол",
    "other": "Бусад мэдээлэл",
}
SKIP = frozenset({"photo", "photo_clear"})


@dataclass(frozen=True)
class InlineColumn:
    """One column of an inline list: its header, the form field its box edits, and how its cell is shown."""

    header: str
    field: str
    value: str = ""  # key in PersonalRow.values when it differs from `field` (e.g. a choice label)
    fmt: str = ""  # "" as text, "date" as YYYY-MM-DD, "money" with the mnt filter


@dataclass(frozen=True)
class InlineList:
    """A personal list edited in its own table rows (UI_RULES §2f pilot) instead of a pop-up."""

    title: str
    columns: tuple[InlineColumn, ...]
    menu_count: bool  # the personal menu shows this list's row count (refreshed after a write)


INLINE_LISTS: dict[str, InlineList] = {
    "language": InlineList(
        "Гадаад хэл",
        (
            InlineColumn("Хэл", "language"),
            InlineColumn("Сонсох", "understand_lvl"),
            InlineColumn("Ярих", "speaking_lvl"),
            InlineColumn("Унших", "reading_lvl"),
            InlineColumn("Бичих", "writing_lvl"),
            InlineColumn("Тайлбар", "description"),
        ),
        menu_count=True,
    ),
    "family": InlineList(
        "Гэр бүл",
        (
            InlineColumn("Хамаарал", "relation"),
            InlineColumn("Овог", "surname"),
            InlineColumn("Нэр", "given_name"),
            InlineColumn("Төрсөн огноо", "birth_date", fmt="date"),
            InlineColumn("Ажил, албан тушаал", "job"),
            InlineColumn("Утас", "phone"),
        ),
        menu_count=True,
    ),
    "talent": InlineList(
        "Авьяас",
        (
            InlineColumn("Авьяас", "talent"),
            InlineColumn("Сургасан он", "trained_year"),
            InlineColumn("Тайлбар", "description"),
        ),
        menu_count=True,
    ),
    "award": InlineList(
        "Шагнал урамшил",
        (
            InlineColumn("Шагналын нэр", "award_name"),
            InlineColumn("Хаанаас", "give_org"),
            InlineColumn("Огноо", "award_date", fmt="date"),
            InlineColumn("Тайлбар", "description"),
        ),
        menu_count=True,
    ),
    "complaint": InlineList(
        "Үйлчлүүлэгчийн гомдол",
        (
            InlineColumn("Огноо", "cdate", fmt="date"),
            InlineColumn("Төрөл", "ctype", value="ctype_label"),
            InlineColumn("Гомдол", "complaint_name", value="complaint_label"),
            InlineColumn("Тайлбар", "comment"),
        ),
        menu_count=True,
    ),
    "driver": InlineList(
        "Жолоо",
        (
            InlineColumn("Жолооны ангилал", "driver_type"),
            InlineColumn("Үнэмлэхний дугаар", "number_driver"),
            InlineColumn("Үнэмлэх авсан огноо", "inserted_ognoo", fmt="date"),
        ),
        menu_count=True,
    ),
    "army_rank": InlineList(
        "Цэргийн цол",
        (
            InlineColumn("Цэргийн цол", "rank"),
            InlineColumn("Цол олгосон огноо", "rank_date", fmt="date"),
            InlineColumn("Нэмэгдлийн хэмжээ", "addition_r"),
        ),
        menu_count=True,
    ),
    "skill": InlineList(
        "Ур чадварын даалгавар",
        (
            InlineColumn("Огноо", "sdate", fmt="date"),
            InlineColumn("Даалгавар", "description"),
            InlineColumn("Нормын тоо", "norm"),
            InlineColumn("Хэлтэс", "department"),
            InlineColumn("Тайлбар", "comment"),
        ),
        menu_count=True,
    ),
    "material_help": InlineList(
        "Буцалтгүй тусламж",
        (
            InlineColumn("Огноо", "help_date", fmt="date"),
            InlineColumn("Үндэслэл", "material_type"),
            InlineColumn("Мөнгөний дүн", "amount", fmt="money"),
            InlineColumn("Тайлбар", "description"),
        ),
        menu_count=True,
    ),
    "discipline": InlineList(
        "Сахилгын шийтгэл",
        (
            InlineColumn("Огноо", "discipline_date", fmt="date"),
            InlineColumn("Шийтгэлийн нэр", "discipline_type"),
            InlineColumn("Хаанаас", "from_discipline"),
            InlineColumn("Шийтгэлийн хувь", "discipline_sal_percent"),
            InlineColumn("Дуусах огноо", "discipline_enddate", fmt="date"),
            InlineColumn("Тайлбар", "description"),
        ),
        menu_count=True,
    ),
    "military": InlineList(
        "Цэргийн алба",
        (
            InlineColumn("Цэргийн цол", "army_rank"),
            InlineColumn("Бэлтгэл зэрэг", "mil_rank"),
            InlineColumn("Алба хаасан жил", "study_type"),
            InlineColumn("Халагдсан огноо", "sacking_date", fmt="date"),
            InlineColumn("Халагдсан шалтгаан", "sacking_reason"),
        ),
        menu_count=True,
    ),
    "contact": InlineList(
        "Яаралтай үед холбогдох",
        (
            InlineColumn("Төрөл", "contact_type"),
            InlineColumn("Нэр", "name"),
            InlineColumn("Хамаарал", "relative"),
            InlineColumn("Утас, имэйл", "value"),
        ),
        menu_count=False,
    ),
}


def _as_posted(value: Any) -> str:
    """A stored value as the browser would post it."""
    if value is None:
        return ""
    if isinstance(value, Model):
        return str(value.pk)
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    if isinstance(value, bool):
        return "on" if value else ""
    return str(value)


def _posted_from_loaded(value: Any) -> str:
    """A `loaded` snapshot value (stale.norm form) as the browser would post it."""
    if value is None or value is False:
        return ""
    if value is True:
        return "on"
    return str(value)


def _loaded_snapshot(post: QueryDict) -> dict[str, Any] | None:
    """The `loaded` snapshot the page posted, or None when absent or unreadable."""
    raw = post.get("loaded")
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def complete_post(form: EmployeeForm, post: QueryDict) -> QueryDict:
    """The POST of a form that does not render every field (the Ажил tab, which no longer shows the
    personal fields). A field not posted takes the value the page showed (`loaded`), so the stale check
    reads it as "left as shown" and a change the old program made meanwhile stays. Without `loaded`, the
    stored value is used. The birthplace always takes the stored value (it is not in the stale check).
    Either way the field is not written and is not required."""
    data = post.copy()
    loaded = _loaded_snapshot(post)
    for name, field in form.fields.items():
        if name in SKIP or name in data:
            continue
        # The birthplace is never taken from `loaded`: the stale check does not cover it, so the stored value is used.
        if loaded is not None and name in loaded and name not in BIRTH_FIELDS:
            data[name] = _posted_from_loaded(loaded[name])
        else:
            data[name] = _as_posted(form.get_initial_for_field(field, name))
    return data


def other_progress(employee: Employee) -> tuple[int, int]:
    """(filled, total) of the «Бусад мэдээлэл» rows for the menu. Prior service is filled only when it is not 0 years
    and 0 months, which is how an empty one is stored."""
    rows = read_rows(employee, "other", "")
    ext = ext_of(employee)
    prior = bool(employee.prior_service_years or (ext is not None and ext.prior_service_months))
    filled = sum(1 for label, value in rows if value and label != "Өмнөх ажилласан") + int(prior)
    return filled, len(rows)


def section_data(form: EmployeeForm, post: QueryDict, names: tuple[str, ...]) -> dict[str, Any]:
    """The POST a section form is validated with: every field at its initial value (so required fields outside
    the section still pass and stay unchanged), overridden by what the section posted and by the stale-check keys."""
    data: dict[str, Any] = {
        name: _as_posted(form.get_initial_for_field(field, name))
        for name, field in form.fields.items()
        if name not in SKIP
    }
    for name in names:
        if name in post:
            data[name] = post.get(name, "")
        elif isinstance(form.fields[name].widget, CheckboxInput):
            data[name] = ""  # an unchecked box is not posted
    for key in post:
        if key == "loaded" or key.startswith("resolve-"):
            data[key] = post[key]
    return data


def only_section_required(form: EmployeeForm, names: tuple[str, ...]) -> None:
    """Only the section's own fields are validated as required: a blank required field elsewhere (old data)
    would otherwise block the save with an error this section does not show."""
    for name, field in form.fields.items():
        if name not in names:
            field.required = False


def outside_errors(form: Form, names: tuple[str, ...]) -> list[str]:
    """Errors the section's own fields do not show: form-wide errors and errors of fields it does not render.
    They go on top of the section, so a failed save is never silent."""
    return [str(message) for name, errors in form.errors.items() if name not in names for message in errors]


def _display(obj: object) -> str:
    return "" if obj is None else str(obj)


def _citizenship(employee: Employee) -> str:
    """«Монгол · гадаад иргэн биш» — the citizenship and the foreign flag on one line."""
    flag = employee.foreign_emp
    foreign = "" if flag is None else ("гадаад иргэн" if flag == 1 else "гадаад иргэн биш")
    return " · ".join(part for part in (_display(employee.citizenship), foreign) if part)


def read_rows(employee: Employee, section: str, birth_place: str) -> list[tuple[str, str]]:
    """Read mode of a section: (label, shown value), the value "" when the field is empty. Choice and foreign-key
    fields show their label, never a code or a pk."""
    if section == "identity":
        rows = [
            ("Регистрийн дугаар", employee.register_no or ""),
            ("Төрсөн огноо", employee.birth_date.isoformat() if employee.birth_date else ""),
            ("Хүйс", employee.get_gender_display() if employee.gender else ""),
            ("Ургийн овог", employee.clan_name or ""),
            ("Иргэншил", _citizenship(employee)),
        ]
        if employee.foreign_emp == 1:
            rows.append(("Гадаад паспортын дугаар", employee.passport_no or ""))
        return [*rows, ("Гэрлэлтийн байдал", _display(employee.marital_status)), ("Төрсөн газар", birth_place)]
    if section == "contact":
        return [("Хувийн утас", employee.private_phone or ""), ("Утас #2", employee.phone2 or "")]
    if section == "education":
        return [
            ("Боловсролын түвшин", _display(employee.education_level)),
            ("Эрдмийн зэрэг", _display(employee.academic_degree)),
        ]
    ext = ext_of(employee)
    blood = " ".join(
        part
        for part in (
            employee.get_blood_type_display() if employee.blood_type else "",
            ext.get_blood_rh_display() if ext is not None and ext.blood_rh else "",
        )
        if part
    )
    return [
        ("Өмнөх ажилласан", f"{employee.prior_service_years} жил {ext.prior_service_months if ext else 0} сар"),
        ("Цусны бүлэг", blood),
        ("Цэргийн алба", employee.get_military_service_display() if employee.military_service else ""),
        ("Нийгмийн гарал", _display(employee.social_origin)),
        ("Орон байрны нөхцөл", _display(employee.housing_condition)),
        ("Амьжиргааны түвшин", ext.living_standard if ext is not None else ""),
        ("Автомашин эзэмшил", _display(employee.car_ownership)),
        ("Хувцасны хэмжээ", _display(employee.clothing_size)),
        ("Гутлын хэмжээ", _display(employee.shoe_size)),
        ("Сонгуульт ажил", _display(employee.elected_position)),
    ]


def _cell(value: object, fmt: str) -> str:
    """The shown text of an inline list cell, "" when empty (the template shows «—»)."""
    if value is None or value == "":
        return ""
    if fmt == "date" and isinstance(value, date):
        return value.isoformat()
    if fmt == "money":
        from employees.templatetags.hr import mnt

        return mnt(value)  # type: ignore[arg-type]
    return str(value)


def inline_context(
    employee: Employee,
    kind: str,
    rows: list[Any],
    can_manage: bool,
    open_key: object = None,
    form: PersonalRowForm | None = None,
    error: str = "",
) -> dict[str, object]:
    """Context of employees/_inline_list.html: the list's rows, and the open row (`open_key` = a row key, or
    "new" for the empty row at the bottom) with its form, errors and empty-list notices."""
    spec = INLINE_LISTS[kind]
    names = [col.field for col in spec.columns]
    errors = [*form.non_field_errors(), *([error] if error else [])] if form is not None else []
    if open_key not in (None, "new") and all(r.key != open_key for r in rows):
        open_key, form = None, None  # the row is gone (deleted elsewhere): show the list closed, with the message
    return {
        "employee": employee,
        "kind": kind,
        "spec": spec,
        "can_manage": can_manage,
        "count": len(rows),
        "items": [
            {
                "key": r.key,
                "cells": [_cell(r.values.get(c.value or c.field), c.fmt) for c in spec.columns],
                "open": r.key == open_key,
            }
            for r in rows
        ],
        "open_key": open_key,
        "open_new": open_key == "new",
        "form": form,
        "form_id": f"inline-{kind}-form",
        "open_fields": [form[name] for name in names] if form is not None else [],
        "errors": errors,
        "empty_lists": form.empty_lists() if form is not None else [],
    }

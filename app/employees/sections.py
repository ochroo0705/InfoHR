"""The personal tab's sections: each is one form that saves only its own fields (views.personal_section)."""

import json
from typing import Any

from django.db.models import Model
from django.forms import CheckboxInput, Form
from django.http import QueryDict
from macs.models import Employee

from employees.forms import BIRTH_FIELDS, EmployeeForm
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
# Numbers of the personal tab menu (анкет order): identity 1, contact 2, education 4, other 10.
NUMBERS = {"identity": 1, "contact": 2, "education": 4, "other": 10}
SKIP = frozenset({"photo", "photo_clear"})


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

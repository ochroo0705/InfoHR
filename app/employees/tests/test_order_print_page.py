"""The order print page's grouping and log label, as a request-free service (shared by the print view)."""

from datetime import date

import pytest

from employees.models import Department
from employees.services import order_register
from employees.services.order_print_page import NO_DEPARTMENT, build_groups, register_label
from employees.services.order_register_page import RegisterQuery, filter_options

pytestmark = pytest.mark.django_db


def _row(number: str, day: date | None, department: str) -> order_register.RegisterRow:
    return order_register.RegisterRow(
        number=number,
        date=day,
        employee_id=1,
        employee_code="E1",
        employee_name="Нэр",
        department=department,
        department_id=None,
        position="",
        summary="",
        issued_by="",
        register_no="",
        gender="",
        age=None,
        state="",
        state_label="",
        order_type=None,
    )


def _query(**changes: object) -> RegisterQuery:
    base: dict[str, object] = {
        "year": None,
        "order_type": None,
        "department": None,
        "state": "",
        "q": "",
        "sort": order_register.DEFAULT_SORT,
    }
    base.update(changes)
    return RegisterQuery(**base)  # type: ignore[arg-type]


def test_build_groups_sorts_by_date_and_puts_no_department_last() -> None:
    rows = [
        _row("1", date(2026, 2, 1), "Санхүү"),
        _row("2", None, "Санхүү"),
        _row("3", date(2026, 1, 5), "Санхүү"),
        _row("4", date(2026, 1, 1), ""),
        _row("5", date(2026, 1, 9), "Үйлдвэр"),
    ]

    groups = build_groups(rows)

    assert [g.department for g in groups] == ["Санхүү", "Үйлдвэр", NO_DEPARTMENT]
    assert [r.number for r in groups[0].rows] == ["3", "1", "2"]
    assert [r.number for r in groups[1].rows] == ["5"]
    assert [r.number for r in groups[2].rows] == ["4"]


def test_build_groups_empty_returns_empty_list() -> None:
    assert build_groups([]) == []


def test_register_label_all_parts() -> None:
    options = filter_options(date(2026, 11, 19))
    department = Department.objects.create(name="Санхүүгийн хэлтэс")
    order_type, type_label = options.types[0]
    state, state_label = options.states[0]

    label = register_label(
        _query(
            year=2026,
            order_type=order_type,
            department=department.pk,
            state=state,
            q="Бат",
        ),
        options,
    )

    assert label == (
        f"Он: 2026; Тушаалын төрөл: {type_label}; Хэлтэс: Санхүүгийн хэлтэс; Төлөв: {state_label}; Хайлт ашигласан"
    )


def test_register_label_never_contains_search_text() -> None:
    options = filter_options(date(2026, 11, 19))

    label = register_label(_query(q="Бат Очир"), options)

    assert label == "Хайлт ашигласан"
    assert "Бат" not in label
    assert "Очир" not in label


def test_register_label_unknown_department_shows_dash() -> None:
    options = filter_options(date(2026, 11, 19))

    label = register_label(_query(department=987654), options)

    assert label == "Хэлтэс: —"

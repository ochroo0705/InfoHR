"""The palette's request-free answer (employees.services.palette_answer): what each group holds for a query, a page and
a user. The HTTP side (the assistant row and the template) is covered by test_palette.py."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group

from employees import palette
from employees.models import Employee, ensure_ext
from employees.services import history, palette_answer
from employees.tests.helpers import next_order_number

from .conftest import hire_values, link_login

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _user(role: str, name: str) -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


@pytest.fixture
def listed(hired: Employee) -> Employee:
    """The hired employee with an HR row, so the palette (like the employee list) can find them."""
    ensure_ext(hired)
    return hired


def _hire(actor: User, job_values: dict[str, Any], register_no: str, family: str, given: str) -> Employee:
    values = hire_values(register_no) | {"family_name": family, "given_name": given}
    emp = history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )
    ensure_ext(emp)
    return emp


def _answer(user: User, q: str = "", **kwargs: Any) -> palette_answer.PaletteAnswer:
    params: dict[str, Any] = {"more": False, "recent_raw": "", "from_path": "", "today": TODAY} | kwargs
    return palette_answer.answer(user, q=q, **params)


def test_empty_box_has_recent_and_current_but_typed_query_has_neither(listed: Employee) -> None:
    hr = _user("HR", "pa_hr1")
    path = f"/employees/{listed.pk}/"
    empty = _answer(hr, "", recent_raw=f"p:{listed.pk}", from_path=path)
    assert [r.ref for r in empty.recent] == [f"p:{listed.pk}"]
    assert empty.current is not None and empty.current.employee.pk == listed.pk
    assert empty.current_actions == palette.person_actions(hr, empty.current)
    typed = _answer(hr, "Батын", recent_raw=f"p:{listed.pk}", from_path=path)
    assert typed.recent == []
    assert typed.current is None and typed.current_actions == []
    assert [p.employee.pk for p in typed.people] == [listed.pk]


def test_single_person_match_gets_person_actions(listed: Employee) -> None:
    hr = _user("HR", "pa_hr2")
    result = _answer(hr, "Батын")
    assert result.single is not None and result.single.employee.pk == listed.pk
    assert result.person_actions == palette.person_actions(hr, result.single)
    assert result.person_actions != []


def test_two_people_get_no_person_actions(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, "УБ99200010", "Батын", "Дорж")  # a second «Батын»
    hr = _user("HR", "pa_hr3")
    result = _answer(hr, "Батын")
    assert result.people_total == 2
    assert result.single is None
    assert result.person_actions == []


def test_more_flag_raises_the_people_limit(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    for i in range(palette.PEOPLE_LIMIT):  # 8 more, so 9 in all match «Батын»
        _hire(actor, job_values, f"УБ9930{i:04d}", "Батын", f"Нэр{i}")
    hr = _user("HR", "pa_hr4")
    shown = _answer(hr, "Батын")
    assert len(shown.people) == palette.PEOPLE_LIMIT
    assert shown.people_total == palette.PEOPLE_LIMIT + 1
    assert shown.people_more is True
    assert shown.single is None
    everyone = _answer(hr, "Батын", more=True)
    assert len(everyone.people) == palette.PEOPLE_LIMIT + 1
    assert everyone.people_more is False


def test_page_pk_reads_only_employee_record_paths() -> None:
    assert palette_answer.page_pk("/employees/12/") == 12
    assert palette_answer.page_pk("/employees/12/x/") is None
    assert palette_answer.page_pk("/employees/new/") is None
    assert palette_answer.page_pk("x") is None
    assert palette_answer.page_pk("/employees/" + "1" * 400 + "/") is None  # longer than FROM_LIMIT
    assert palette_answer.page_pk("") is None


def test_recent_refs_outside_scope_are_dropped(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    other = _hire(actor, job_values, "УБ99200001", "Хориотой", "Бат")
    emp = _user("Employee", "pa_emp1")
    link_login(listed, emp)
    raw = f"p:{other.pk},p:{listed.pk},s:/no/such/page/"
    assert [r.ref for r in _answer(emp, "", recent_raw=raw).recent] == [f"p:{listed.pk}"]


def test_user_without_view_right_gets_no_people_or_orders(listed: Employee) -> None:
    emp = _user("Employee", "pa_emp2")
    result = _answer(emp, "Батын")
    assert result.people == []
    assert result.people_total == 0
    assert result.orders == []
    assert result.words == ["Батын"]
    assert result.fixed_urls == {screen.url for screen in palette.screens(emp, "")}

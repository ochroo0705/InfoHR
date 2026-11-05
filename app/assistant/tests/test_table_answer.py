from collections.abc import Callable

import pytest
from accounts.models import User
from django.http import QueryDict
from django.urls import reverse
from employees.models import Employee, JobRecord
from macs.models import Department
from reports.filters import Filters, parse_filters
from reports.staff_list import REPORT
from reports.table import build_table, offered_column_filters

from assistant.plan import Part
from assistant.tables import can_open_table, table_answer
from assistant.tests.helpers import hire_one

pytestmark = pytest.mark.django_db

STAFF_PATH = reverse("reports:report", args=["staff-list"])
DENIED_LINE = "Ажилтны хүснэгтийг харах эрх алга."


def _part(param: str, value: str) -> Part:
    return Part(param=param, value=value)


def _set_type(person: Employee, code: int) -> None:
    JobRecord.objects.filter(employee=person).update(emptype=code)
    Employee.objects.filter(pk=person.pk).update(emptype=code)


def _count(user: User, f: Filters) -> int:
    return build_table(REPORT, user, f).count


def test_list_counts_the_same_as_the_table(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    first = hire_one(actor)
    second = hire_one(actor)
    other = hire_one(actor)
    _set_type(first, 5)
    _set_type(second, 5)
    _set_type(other, 1)

    answer = table_answer(user, [_part("emptype", "5")])

    assert answer.status == "list"
    assert answer.count == 2
    assert answer.count == _count(user, Filters(emptype=5))


def test_query_round_trips(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)  # puts a person in «Санхүү», the department the phrase names
    dept = Department.objects.get(name="Санхүү")

    answer = table_answer(user, [_part("department", "санхүү"), _part("emptype", "5")])

    parsed = parse_filters(QueryDict(answer.query))
    assert parsed.department == dept.pk
    assert parsed.emptype == 5
    assert build_table(REPORT, user, parsed).count == answer.count


def test_column_filter_round_trips(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)
    assert "hired" in offered_column_filters(REPORT, user)  # precondition: hr is offered the hire-date filter

    answer = table_answer(user, [], base_query="hired_from=2020-01-01")

    parsed = parse_filters(QueryDict(answer.query))
    assert ("hired_from", "2020-01-01") in parsed.extra
    assert answer.count == build_table(REPORT, user, parsed).count


def test_query_has_no_column_group_or_sort(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    answer = table_answer(user, [_part("emptype", "5")], base_query="cols=code&group=department&sort=-name")

    assert "cols" not in answer.query
    assert "group" not in answer.query
    assert "sort" not in answer.query


def test_zero_people(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    Department.objects.create(name="Маркетинг")

    answer = table_answer(user, [_part("department", "маркетинг")])

    assert answer.status == "list"
    assert answer.count == 0


def test_ask_status_has_no_count(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    Department.objects.create(name="Санхүүгийн хяналт")
    Department.objects.create(name="Санхүүгийн төлөвлөлт")

    answer = table_answer(user, [_part("department", "санхүү")])

    assert answer.status == "ask"
    assert answer.count is None
    assert answer.ask is not None
    assert len(answer.ask.candidates) == 2
    assert answer.url.startswith(STAFF_PATH)


def test_ask_chips_and_url_are_partial(role_user: Callable[[str], User]) -> None:
    # The emptype part is settled before the ambiguous department, so only it shows; the rest waits.
    user: User = role_user("hr")
    Department.objects.create(name="Санхүүгийн хяналт")
    Department.objects.create(name="Санхүүгийн төлөвлөлт")

    answer = table_answer(user, [_part("emptype", "5"), _part("department", "санхүү")])

    assert answer.status == "ask"
    assert "Ажилтны төрөл: Гэрээт ажилтан" in answer.chips  # the default state and date lines are there too
    assert not any(line.startswith("Хэлтэс") for line in answer.chips)  # the ambiguous part is not applied yet
    assert answer.query == "emptype=5"
    assert answer.url == f"{STAFF_PATH}?emptype=5"


def test_prev_with_unusable_param_is_dropped(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")  # holds view_employees and view_reports, not view_salary

    answer = table_answer(user, [], base_query="salary_from=1000&emptype=5")

    assert "emptype=5" in answer.query
    assert "salary" not in answer.query


def test_chips_describe_filters(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)

    answer = table_answer(user, [_part("department", "санхүү")])

    assert any("Хэлтэс" in line and "Санхүү" in line for line in answer.chips)


def test_chips_have_emptype_line(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    answer = table_answer(user, [_part("emptype", "5")])

    assert "Ажилтны төрөл: Гэрээт ажилтан" in answer.chips


def test_chips_have_column_filter_line(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    answer = table_answer(user, [], base_query="hired_from=2020-01-01")

    assert "Ажилд орсон: 2020-01-01 – " in answer.chips


def test_default_state_is_not_in_query(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    answer = table_answer(user, [])

    assert answer.query == ""
    assert answer.url == STAFF_PATH
    assert answer.count == _count(user, Filters())


def test_url_carries_the_query(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    answer = table_answer(user, [_part("emptype", "5")])

    assert answer.url == f"{STAFF_PATH}?{answer.query}"


def test_base_query_normal_case_is_kept(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    answer = table_answer(user, [], base_query="emptype=5")

    assert answer.query == "emptype=5"


def test_base_query_too_many_fields_never_raises(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    answer = table_answer(user, [], base_query="&" * 1500)

    assert answer.status == "list"
    assert answer.query == ""


def test_base_query_is_capped_and_never_raises(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")

    assert table_answer(user, [], base_query="a=" + "x" * 5000).query == ""
    assert table_answer(user, [], base_query="%%%=%ZZ&&==&&").query == ""


def test_base_cap_drops_a_param_after_2000_characters(role_user: Callable[[str], User]) -> None:
    # 2000 characters of padding first: the department after them is cut, so the link has no department.
    user: User = role_user("hr")
    dept = Department.objects.create(name="Санхүү")
    padding = "x=" + "a" * 1998  # exactly 2000 characters

    cut = table_answer(user, [], base_query=f"{padding}&department={dept.pk}")
    kept = table_answer(user, [], base_query=f"department={dept.pk}")

    assert cut.query == ""
    assert kept.query == f"department={dept.pk}"


def test_can_open_table(role_user: Callable[[str], User]) -> None:
    assert can_open_table(role_user("hr")) is True
    assert can_open_table(role_user("none")) is False


def test_user_without_view_employees_is_denied(role_user: Callable[[str], User]) -> None:
    user: User = role_user("auditor")

    answer = table_answer(user, [_part("emptype", "5")])

    assert answer.status == "denied"
    assert answer.count is None
    assert answer.url == ""
    assert answer.query == ""
    assert answer.not_applied == (DENIED_LINE,)

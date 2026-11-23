# DRAFT: written by Claude. Replace or extend with real HR questions
# needs native read
"""The SQL accuracy set: Mongolian questions, the rows the governed SQL should give, and the checker that compares them.

Each case is asked as the role named in it. The truth is computed from the ORM with the same rules the views use:
who may be seen is employees/access.py::visible_employees, and «works now» is employees/listing.py (row_for and
is_working), the same rule as the WORKING flag in GOV_EMPLOYEES. Compare kinds:
  set      the answer's rows, as a set of tuples, equal the truth's rows (order and duplicates ignored)
  scalar   the answer has one row with one cell, equal to the truth's single value
  empty    the answer has no rows and the truth has none
  refused  the answer is a refusal of the checker (not a provider failure)
Cells are compared as text: None is "", Decimal and float are shown without trailing zeros, dates as ISO text.
Columns are compared by position, so a question names the columns it wants, in order.
"""

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.db.models import Max, Sum
from django.utils import timezone
from employees.access import visible_employees
from employees.listing import employee_rows, is_working
from employees.models import HrOrder, OrderState, OrderType, SalaryRecord
from hr_sql.views import _ORDER_TYPE_WORDS  # the English words the views show for each order type
from macs.models import Employee, FamilyRow, LeaveAssign, LoanRow
from sqlcore.runner import Host

from assistant.providers import Provider
from assistant.sqlanswer import PROVIDER_REASON, SqlAnswer, sql_answer

SQL_ROLES = ("hr", "accountant")
COMPARE_KINDS = ("set", "scalar", "empty", "refused")
CHILD_TYPES = ("son", "daughter")
SALARY_LINE = 2_000_000  # the salary threshold of the cases, in togrog
LOAN_LINE = 5_000_000  # the loan threshold of the cases, in togrog


@dataclass(frozen=True)
class SqlCase:
    question: str
    role: str  # "hr" or "accountant": the user the question is asked as
    truth: Callable[[User], list[tuple[object, ...]]]  # the rows the answer should give (unused for "refused")
    compare: str  # one of COMPARE_KINDS


@dataclass(frozen=True)
class SqlResult:
    passed: bool
    reason: str  # one line, for the eval's output


# ---- truth helpers: the same rules as the views (see the module docstring) ------------------------------------------


def _today() -> date:
    return timezone.localdate()


def _years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 February
        return today.replace(year=today.year - years, day=28)


def _name(obj: Any) -> str | None:
    """The name of an optional related row (a department, a branch, a leave type), None when there is none."""
    return None if obj is None else obj.name


def _working(user: User) -> list[Employee]:
    """The visible employees the employee list counts as working today (the WORKING flag of GOV_EMPLOYEES)."""
    rows = employee_rows(visible_employees(user), _today())
    return [row.employee for row in rows if is_working(row)]


def _working_ids(user: User) -> set[int]:
    return {employee.pk for employee in _working(user)}


def _children(user: User) -> list[FamilyRow]:
    return list(FamilyRow.objects.filter(employee__in=visible_employees(user), relation__fm_type__in=CHILD_TYPES))


def _employees_by_id(user: User) -> dict[int, Employee]:
    return {e.pk: e for e in visible_employees(user).select_related("department")}


def _approved_leave_this_year(user: User) -> list[LeaveAssign]:
    return list(
        LeaveAssign.objects.filter(
            employee__in=visible_employees(user),
            status=LeaveAssign.APPROVED,
            date1__year=_today().year,
        ).select_related("employee__department", "leave_type")
    )


def _sum_or_none(values: Iterable[int | None]) -> int | None:
    """SUM as SQL gives it: the total of the values that are not NULL, and NULL when there are none."""
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _count_by(keys: Iterable[object]) -> list[tuple[object, ...]]:
    return [(key, count) for key, count in Counter(keys).items()]


# ---- head counts with the WORKING flag -------------------------------------------------------------------------------


def _t_working_total(user: User) -> list[tuple[object, ...]]:
    return [(len(_working(user)),)]


def _t_working_men(user: User) -> list[tuple[object, ...]]:
    return [(sum(1 for e in _working(user) if e.gender == "M"),)]


def _t_working_by_branch(user: User) -> list[tuple[object, ...]]:
    return _count_by(_name(e.branch) for e in _working(user))


def _t_working_by_department(user: User) -> list[tuple[object, ...]]:
    return _count_by(_name(e.department) for e in _working(user))


def _t_not_working_total(user: User) -> list[tuple[object, ...]]:
    return [(visible_employees(user).count() - len(_working(user)),)]


def _t_visible_total(user: User) -> list[tuple[object, ...]]:
    return [(visible_employees(user).count(),)]


def _t_women_total(user: User) -> list[tuple[object, ...]]:
    return [(visible_employees(user).filter(gender="F").count(),)]


# ---- children (sons and daughters) ----------------------------------------------------------------------------------


def _t_employees_with_children(user: User) -> list[tuple[object, ...]]:
    return [(pk,) for pk in {child.employee_id for child in _children(user)}]


def _t_employees_with_children_count(user: User) -> list[tuple[object, ...]]:
    return [(len({child.employee_id for child in _children(user)}),)]


def _t_children_total(user: User) -> list[tuple[object, ...]]:
    return [(len(_children(user)),)]


def _t_children_names(user: User) -> list[tuple[object, ...]]:
    return [(child.employee_id, child.given_name) for child in _children(user)]


def _t_longest_serving_with_two_children(user: User) -> list[tuple[object, ...]]:
    counts = Counter(child.employee_id for child in _children(user))
    people = [e for e in _working(user) if counts[e.pk] >= 2]
    return _ids(_tenure_extremes(people, longest=True, shortest=False))


def _t_children_per_employee(user: User) -> list[tuple[object, ...]]:
    return _count_by(child.employee_id for child in _children(user))


def _t_children_under_5(user: User) -> list[tuple[object, ...]]:
    limit = _years_ago(_today(), 5)
    return [(sum(1 for c in _children(user) if c.birth_date is not None and c.birth_date > limit),)]


def _t_children_under_18(user: User) -> list[tuple[object, ...]]:
    limit = _years_ago(_today(), 18)
    return [(sum(1 for c in _children(user) if c.birth_date is not None and c.birth_date > limit),)]


def _t_working_with_children_count(user: User) -> list[tuple[object, ...]]:
    with_children = {child.employee_id for child in _children(user)}
    return [(len(with_children & _working_ids(user)),)]


def _t_children_per_department(user: User) -> list[tuple[object, ...]]:
    by_id = _employees_by_id(user)
    return _count_by(_name(by_id[child.employee_id].department) for child in _children(user))


def _t_employees_with_children_per_department(user: User) -> list[tuple[object, ...]]:
    by_id = _employees_by_id(user)
    people = {(child.employee_id, _name(by_id[child.employee_id].department)) for child in _children(user)}
    return _count_by(department for _pk, department in people)


def _t_women_with_children_count(user: User) -> list[tuple[object, ...]]:
    by_id = _employees_by_id(user)
    women = {child.employee_id for child in _children(user) if by_id[child.employee_id].gender == "F"}
    return [(len(women),)]


# ---- leave taken this year (status approved, start date this year) --------------------------------------------------


def _t_leave_days_per_department(user: User) -> list[tuple[object, ...]]:
    by_department: dict[str | None, list[int | None]] = {}
    for leave in _approved_leave_this_year(user):
        by_department.setdefault(_name(leave.employee.department), []).append(leave.adays)
    return [(dep, _sum_or_none(days)) for dep, days in by_department.items()]


def _t_leave_count_per_type(user: User) -> list[tuple[object, ...]]:
    return _count_by(_name(leave.leave_type) for leave in _approved_leave_this_year(user))


def _t_leave_employees_count(user: User) -> list[tuple[object, ...]]:
    return [(len({leave.employee_id for leave in _approved_leave_this_year(user)}),)]


def _t_leave_days_total(user: User) -> list[tuple[object, ...]]:
    return [(_sum_or_none(leave.adays for leave in _approved_leave_this_year(user)),)]


def _t_no_leave_this_year(user: User) -> list[tuple[object, ...]]:
    taken = {leave.employee_id for leave in _approved_leave_this_year(user)}
    return [(e.pk,) for e in visible_employees(user) if e.pk not in taken]


# ---- HR orders ------------------------------------------------------------------------------------------------------


def _orders(user: User) -> list[HrOrder]:
    return list(HrOrder.objects.filter(employee__in=visible_employees(user)))


def _t_orders_per_type(user: User) -> list[tuple[object, ...]]:
    return _count_by(_ORDER_TYPE_WORDS[OrderType(order.order_type)] for order in _orders(user))


def _t_registered_orders(user: User) -> list[tuple[object, ...]]:
    return [(sum(1 for o in _orders(user) if o.state == OrderState.REGISTERED),)]


def _t_hired_orders(user: User) -> list[tuple[object, ...]]:
    return [(sum(1 for o in _orders(user) if o.order_type == OrderType.HIRED),)]


def _t_employees_with_orders(user: User) -> list[tuple[object, ...]]:
    return [(len({order.employee_id for order in _orders(user)}),)]


def _t_hired_this_year(user: User) -> list[tuple[object, ...]]:
    return [(visible_employees(user).filter(first_hire_date__year=_today().year).count(),)]


def _t_birthdays_this_month(user: User) -> list[tuple[object, ...]]:
    month = _today().month
    return [(e.pk,) for e in visible_employees(user) if e.birth_date is not None and e.birth_date.month == month]


# ---- salary and loans (accountant only; the HR role is refused) ------------------------------------------------------


def _current_salaries(user: User, over: int) -> list[SalaryRecord]:
    return list(
        SalaryRecord.objects.filter(
            employee__in=visible_employees(user), end_date__isnull=True, base_salary__gt=over
        )
    )


def _t_salary_over_line(user: User) -> list[tuple[object, ...]]:
    return [(s.employee_id, s.base_salary) for s in _current_salaries(user, SALARY_LINE)]


def _t_salary_over_line_count(user: User) -> list[tuple[object, ...]]:
    return [(len({s.employee_id for s in _current_salaries(user, SALARY_LINE)}),)]


def _t_salary_max(user: User) -> list[tuple[object, ...]]:
    top = SalaryRecord.objects.filter(employee__in=visible_employees(user)).aggregate(top=Max("base_salary"))
    return [(top["top"],)]


def _t_salary_changes_per_type(user: User) -> list[tuple[object, ...]]:
    records = SalaryRecord.objects.filter(employee__in=visible_employees(user))
    return _count_by(record.change_type for record in records)


def _t_loans_over_line(user: User) -> list[tuple[object, ...]]:
    loans = LoanRow.objects.filter(employee__in=visible_employees(user), amount__gt=LOAN_LINE)
    return [(loan.employee_id, loan.amount) for loan in loans]


def _t_loans_total(user: User) -> list[tuple[object, ...]]:
    total = LoanRow.objects.filter(employee__in=visible_employees(user)).aggregate(total=Sum("amount"))
    return [(total["total"],)]


def _refused_truth(user: User) -> list[tuple[object, ...]]:
    return []  # a refused case is not compared with rows


# ---- the set ---------------------------------------------------------------------------------------------------------

SQL_CASES: tuple[SqlCase, ...] = (
    SqlCase("Одоо ажиллаж байгаа ажилтнууд хэд вэ?", "hr", _t_working_total, "scalar"),
    SqlCase("Одоо ажиллаж байгаа эрэгтэй ажилтан хэд вэ?", "hr", _t_working_men, "scalar"),
    SqlCase("Салбар тус бүрд одоо ажиллаж байгаа хүмүүс хэд вэ?", "hr", _t_working_by_branch, "set"),
    SqlCase("Хэлтэс тус бүрд одоо ажиллаж байгаа хүмүүс хэд вэ?", "hr", _t_working_by_department, "set"),
    SqlCase("Одоо ажиллахгүй байгаа ажилтнууд хэд вэ?", "hr", _t_not_working_total, "scalar"),
    SqlCase("Харагдах бүх ажилтны тоо хэд вэ?", "hr", _t_visible_total, "scalar"),
    SqlCase("Эмэгтэй ажилтнууд хэд вэ?", "hr", _t_women_total, "scalar"),
    SqlCase("Хүүхэдтэй ажилтнуудын ажилтны кодыг гарга.", "hr", _t_employees_with_children, "set"),
    SqlCase("Хүүхэдтэй хэдэн ажилтан байна?", "hr", _t_employees_with_children_count, "scalar"),
    SqlCase("Хүүхдийн нийт тоо хэд вэ?", "hr", _t_children_total, "scalar"),
    SqlCase("Ажилтан бүрийн хүүхдийн тоог гарга.", "hr", _t_children_per_employee, "set"),
    SqlCase(
        "Одоо ажиллаж байгаа, дор хаяж 2 хүүхэдтэй ажилтнуудаас хамгийн удаан ажилласан хүний "
        "ажилтны кодыг ганц багана болгон гарга.",
        "hr",
        _t_longest_serving_with_two_children,
        "set",
    ),
    SqlCase(
        "Зөвхөн хоёр багана гарга: ажилтны код, хүүхдийн нэр. Хүүхэд бүрээр нэг мөр.", "hr", _t_children_names, "set"
    ),
    SqlCase("5-аас доош насны хүүхэд хэд вэ?", "hr", _t_children_under_5, "scalar"),
    SqlCase("18-аас доош насны хүүхэд хэд вэ?", "hr", _t_children_under_18, "scalar"),
    SqlCase("Одоо ажиллаж байгаа хэдэн ажилтан хүүхэдтэй вэ?", "hr", _t_working_with_children_count, "scalar"),
    SqlCase("Хэлтэс тус бүрд хэдэн хүүхэд байна?", "hr", _t_children_per_department, "set"),
    SqlCase("Хэлтэс тус бүрд хүүхэдтэй хэдэн ажилтан байна?", "hr", _t_employees_with_children_per_department, "set"),
    SqlCase("Хүүхэдтэй эмэгтэй ажилтан хэд вэ?", "hr", _t_women_with_children_count, "scalar"),
    SqlCase(
        "Энэ жил хэлтэс тус бүрээр ажилтнууд хэдэн өдөр чөлөө авсан бэ?", "hr", _t_leave_days_per_department, "set"
    ),
    SqlCase("Энэ жил ямар төрлийн чөлөө хэдэн удаа авсан бэ?", "hr", _t_leave_count_per_type, "set"),
    SqlCase("Энэ жил чөлөө авсан хэдэн ажилтан байна?", "hr", _t_leave_employees_count, "scalar"),
    SqlCase("Энэ жил авсан чөлөөний нийт хоног хэд вэ?", "hr", _t_leave_days_total, "scalar"),
    SqlCase("Энэ жил батлагдсан чөлөө аваагүй ажилтнууд хэн бэ?", "hr", _t_no_leave_this_year, "set"),
    SqlCase("Тушаалын төрөл тус бүрээр хэдэн тушаал байна?", "hr", _t_orders_per_type, "set"),
    SqlCase("Төлөв нь «Бүртгэсэн» байгаа тушаал хэд вэ?", "hr", _t_registered_orders, "scalar"),
    SqlCase("Ажилд орсон төрлийн тушаал хэд байна?", "hr", _t_hired_orders, "scalar"),
    SqlCase("Ямар нэгэн тушаалтай ажилтан хэд байна?", "hr", _t_employees_with_orders, "scalar"),
    SqlCase("Энэ онд ажилд орсон ажилтан хэд вэ?", "hr", _t_hired_this_year, "scalar"),
    SqlCase("Энэ сард төрсөн өдөртэй ажилтнууд хэн бэ?", "hr", _t_birthdays_this_month, "set"),
    SqlCase(
        "Одоогийн үндсэн цалин 2 сая төгрөгөөс дээш ажилтнуудын код ба цалинг гарга.",
        "accountant",
        _t_salary_over_line,
        "set",
    ),
    SqlCase(
        "Одоогийн үндсэн цалин 2 сая төгрөгөөс дээш ажилтан хэд вэ?", "accountant", _t_salary_over_line_count, "scalar"
    ),
    SqlCase("Хамгийн өндөр үндсэн цалин хэд вэ?", "accountant", _t_salary_max, "scalar"),
    SqlCase(
        "Зээлийн дүн 5 сая төгрөгөөс их ажилтнуудын код ба зээлийн дүнг гарга.",
        "accountant",
        _t_loans_over_line,
        "set",
    ),
    SqlCase("Нийт зээлийн дүн хэд вэ?", "accountant", _t_loans_total, "scalar"),
    SqlCase(
        "Цалингийн өөрчлөлтийн төрөл тус бүрээр хэдэн удаа гарсан бэ?", "accountant", _t_salary_changes_per_type, "set"
    ),
    # The same questions as the accountant's, asked as HR: the checker must refuse them (no salary views for HR).
    SqlCase(
        "Одоогийн үндсэн цалин 2 сая төгрөгөөс дээш ажилтнуудын код ба цалинг гарга.",
        "hr",
        _refused_truth,
        "refused",
    ),
    SqlCase("Нийт зээлийн дүн хэд вэ?", "hr", _refused_truth, "refused"),
)


# ---- two-turn cases: a table is asked for, then refined (the workspace tab path) ------------------------------------


@dataclass(frozen=True)
class RefineCase:
    """A question that opens a table and a follow-up line that refines it. The truth is the rows of the table after
    the follow-up; the compare kind is "set" and the compare looks at the first column only (EMP_ID).
    `note` says what the follow-up must do, for the eval's output."""

    first: str
    followup: str
    role: str
    truth: Callable[[User], list[tuple[object, ...]]]
    note: str
    group: str = ""  # when set: the column the final table must group its rows under (upper case), else not checked


DEPARTMENT = "Борлуулалт"  # a department with many people in the test data copy, used by the department cases


def _tenure_extremes(people: list[Employee], *, longest: bool, shortest: bool) -> set[int]:
    """Ids of the people with the earliest first hire date (longest-serving) and/or the latest (shortest-serving),
    ties included, people with no hire date left out (the same as MIN and MAX in SQL)."""
    dated = [(e.pk, e.first_hire_date) for e in people if e.first_hire_date is not None]
    if not dated:
        return set()
    earliest = min(day for _pk, day in dated)
    latest = max(day for _pk, day in dated)
    return {pk for pk, day in dated if (longest and day == earliest) or (shortest and day == latest)}


def _in_department(people: list[Employee]) -> list[Employee]:
    return [e for e in people if e.department is not None and e.department.name == DEPARTMENT]


def _ids(pks: Iterable[int]) -> list[tuple[object, ...]]:
    return [(pk,) for pk in pks]


def _r_longest_then_add_shortest(user: User) -> list[tuple[object, ...]]:
    return _ids(_tenure_extremes(_working(user), longest=True, shortest=True))


def _r_department_longest_then_add_shortest(user: User) -> list[tuple[object, ...]]:
    return _ids(_tenure_extremes(_in_department(_working(user)), longest=True, shortest=True))


def _r_working_women_then_add_men(user: User) -> list[tuple[object, ...]]:
    return _ids(e.pk for e in _working(user) if e.gender in ("F", "M"))


def _r_department_working_then_add_women_elsewhere(user: User) -> list[tuple[object, ...]]:
    people = _working(user)
    wanted = {e.pk for e in _in_department(people)} | {e.pk for e in people if e.gender == "F"}
    return _ids(wanted)


def _r_working_then_only_women(user: User) -> list[tuple[object, ...]]:
    return _ids(e.pk for e in _working(user) if e.gender == "F")


def _r_department_then_only_longest(user: User) -> list[tuple[object, ...]]:
    return _ids(_tenure_extremes(_in_department(_working(user)), longest=True, shortest=False))


def _r_top_department_then_its_longest(user: User) -> list[tuple[object, ...]]:
    """The department (by name) with the highest average tenure among working people with a hire date, then the
    longest-serving working people of that department."""
    today = _today()
    by_name: dict[str, list[Employee]] = {}
    for e in _working(user):
        if e.first_hire_date is not None and e.department is not None:
            by_name.setdefault(e.department.name, []).append(e)
    if not by_name:
        return []

    def average(people: list[Employee]) -> float:
        return sum((today - e.first_hire_date).days for e in people) / len(people)

    top = max(by_name.values(), key=average)
    return _ids(_tenure_extremes(top, longest=True, shortest=False))


def _r_working_with_children(user: User) -> list[tuple[object, ...]]:
    with_children = {child.employee_id for child in _children(user)}
    return _ids(with_children & _working_ids(user))


REFINE_CASES: tuple[RefineCase, ...] = (
    RefineCase(
        "Одоо ажиллаж байгаа ажилтнуудаас хамгийн удаан ажилласан хүний ажилтны кодыг гарга.",
        "хамгийн бага хугацаагаар ажилласан хүнийг нэмж харуул",
        "hr",
        _r_longest_then_add_shortest,
        "add the other extreme: both, company-wide",
    ),
    RefineCase(
        f"{DEPARTMENT} хэлтсийн одоо ажиллаж байгаа хамгийн удаан ажилласан ажилтны кодыг гарга.",
        "хамгийн бага жил ажилласан ажилтныг нэмж харуул",
        "hr",
        _r_department_longest_then_add_shortest,
        "add the other extreme: both, inside the department only",
    ),
    RefineCase(
        "Одоо ажиллаж байгаа эмэгтэй ажилтнуудын ажилтны кодыг гарга.",
        "эрэгтэй ажилтнуудыг бас нэм",
        "hr",
        _r_working_women_then_add_men,
        "add another group: working women and working men",
    ),
    RefineCase(
        f"{DEPARTMENT} хэлтсийн одоо ажиллаж байгаа ажилтнуудын ажилтны кодыг гарга.",
        "бусад хэлтсийн одоо ажиллаж байгаа эмэгтэйчүүдийг мөн харуул",
        "hr",
        _r_department_working_then_add_women_elsewhere,
        "add a second group: the department, or working women",
    ),
    RefineCase(
        "хамгийн өндөр дундаж ажилласан жилтэй хэлтсийг харуул",
        "энэ хэлтэсд хамгийн удаан ажилласан ажилтныг харуул, ажилтны кодыг эхний баганад гарга",
        "hr",
        _r_top_department_then_its_longest,
        "«this department» means the top department, not each department",
    ),
    RefineCase(
        "Одоо ажиллаж байгаа ажилтнуудын ажилтны кодыг гарга.",
        "хүүхэдтэй ажилчдыг хүүхдүүдтэй нь харуул",
        "hr",
        _r_working_with_children,
        "«with their children»: one row per child, grouped by employee",
        group="EMP_ID",
    ),
    RefineCase(
        "Одоо ажиллаж байгаа ажилтнуудын ажилтны кодыг гарга.",
        "зөвхөн эмэгтэйчүүдийг үлдээ",
        "hr",
        _r_working_then_only_women,
        "narrow, not add: working women only",
    ),
    RefineCase(
        f"{DEPARTMENT} хэлтсийн одоо ажиллаж байгаа ажилтнуудын ажилтны кодыг гарга.",
        "тэднээс хамгийн удаан ажилласан хүнийг л үлдээ",
        "hr",
        _r_department_then_only_longest,
        "narrow, not add: the longest-serving of the department",
    ),
)


# ---- the checker -----------------------------------------------------------------------------------------------------


def _norm(cell: object) -> str:
    """A cell as text for comparison: None is "", numbers without trailing zeros, dates as ISO text."""
    if cell is None:
        return ""
    if isinstance(cell, float):
        cell = Decimal(repr(cell))
    if isinstance(cell, Decimal):
        return format(cell.normalize(), "f")
    if isinstance(cell, date):
        return cell.isoformat()
    return str(cell).strip()


def _key(row: Iterable[object]) -> tuple[str, ...]:
    return tuple(_norm(cell) for cell in row)


def _shown(rows: Iterable[Iterable[object]]) -> str:
    text = "; ".join(" | ".join(_key(row)) for row in rows)
    return text if len(text) <= 160 else text[:157] + "..."


def check_refine_case(case: RefineCase, user: User, provider: Provider, host: Host | None = None) -> SqlResult:
    """Opens a tab with the first line, refines it with the follow-up (both through ws_service.refine_tab, the path the
    chat uses) and compares the rows of the final SQL with the case's truth. Needs the database for the tab (the eval
    runs inside a transaction it rolls back)."""
    from hr_sql.host import HrHost
    from sqlcore.runner import Refused, run_question

    from assistant import ws_service

    day = _today()
    tab = ws_service.new_tab(user)
    for line in (case.first, case.followup):
        result = ws_service.refine_tab(user, tab, line, day, provider, host)
        if result.status != "ok":
            return SqlResult(False, f"{result.status} after «{line}»: {result.reason}")
    version = tab.current()
    if version is None:
        return SqlResult(False, "no version after the follow-up")
    outcome = run_question(host if host is not None else HrHost(), user, version.sql)
    if isinstance(outcome, Refused):
        return SqlResult(False, f"final query refused: {outcome.reason}")
    got = outcome.result.rows
    want = case.truth(user)
    # Only the employee code (the first column) is compared: the table may add name columns of its own.
    if {_key(row)[:1] for row in got} == {_key(row)[:1] for row in want}:
        if case.group:
            try:
                shown = str(json.loads(version.settings or "{}").get("group_by", "")).upper()
            except (ValueError, AttributeError):
                shown = ""
            if shown != case.group:
                return SqlResult(False, f"{case.note}: rows are right but the table groups by {shown or 'nothing'}")
        return SqlResult(True, f"{len(got)} row(s), as expected ({case.note})")
    sql = " ".join(version.sql.split())
    sql = sql if len(sql) <= 300 else sql[:297] + "..."
    return SqlResult(
        False, f"{case.note}: expected {_shown(want) or 'no rows'}; got {_shown(got) or 'no rows'}; sql {sql}"
    )


def check_sql_case(case: SqlCase, user: User, provider: Provider, host: Host | None = None) -> SqlResult:
    """Asks the question as `user` through sql_answer and compares the answer with the case's truth."""
    answer: SqlAnswer = sql_answer(user, case.question, _today(), provider, host)

    if case.compare == "refused":
        if answer.status == "refused" and not answer.reason.startswith(PROVIDER_REASON):
            return SqlResult(True, "refused, as the case expects")
        if answer.reason.startswith(PROVIDER_REASON):
            return SqlResult(False, f"no answer: the provider failed ({answer.reason})")
        return SqlResult(False, f"expected a refusal, got {answer.status}")

    if answer.status != "ok":
        return SqlResult(False, f"{answer.status}: {answer.reason}")

    got = answer.rows
    want = case.truth(user)
    if case.compare == "set":
        passed = {_key(row) for row in got} == {_key(row) for row in want}
    elif case.compare == "scalar":
        passed = len(got) == 1 and len(got[0]) == 1 and len(want) == 1 and _key(got[0]) == _key(want[0])
    elif case.compare == "empty":
        passed = not got and not want
    else:
        raise ValueError(f"unknown compare kind: {case.compare!r}")
    if passed:
        return SqlResult(True, f"{len(got)} row(s), as expected")
    return SqlResult(False, f"expected {_shown(want) or 'no rows'}; got {_shown(got) or 'no rows'}")


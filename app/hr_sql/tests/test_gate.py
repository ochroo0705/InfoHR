"""The gate (Task 6 of the governed SQL plan): real Firebird, real roles, through run_question. Firebird only.

Each test runs a question the way the assistant will: check, run as the asker on the governed connection, cap the
rows. Employees and family rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. Every row a test makes is removed again.
"""

import time
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from employees.access import visible_employees
from macs.models import Branch, Employee, FamilyRelation, FamilyRow, LeaveAssign, LeaveTypeRow
from sqlcore.check import CheckError, check_sql
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, TIMEOUT_REASON, Answered, Refused, run_question

from hr_sql.host import HrHost
from hr_sql.tests.conftest import PASSWORD, World

EMP_IDS = "SELECT EMP_ID FROM GOV_EMPLOYEES"
COUNT_EMPLOYEES = "SELECT COUNT(*) FROM GOV_EMPLOYEES"
CHILDREN_BY_NAME = (
    "SELECT e.FIRST_NAME, COUNT(c.CHILD_ID) AS CHILDREN FROM GOV_EMPLOYEES e "
    "JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID GROUP BY e.FIRST_NAME"
)
# Three copies of the employee view crossed: a cross join of every visible employee with itself twice.
HEAVY = "SELECT COUNT(*) FROM GOV_EMPLOYEES a, GOV_EMPLOYEES b, GOV_EMPLOYEES c"


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


def _int(value: object) -> int:
    return int(str(value))


def _ids(answer: Answered) -> set[int]:
    return {_int(row[0]) for row in answer.result.rows}


def _visible_ids(user: User) -> set[int]:
    return {int(pk) for pk in visible_employees(user).values_list("pk", flat=True)}


def _diagnose(user: User, sql: str) -> str:
    """Why a question was refused. run_question hides the database error, so the same checked SQL is run again here."""
    try:
        checked = check_sql(sql, HrHost().catalogue_for(user))
    except CheckError as error:
        return f"Checker refused it: {error}"
    try:
        HrHost().execute(user, checked, Limits())
    except Exception as error:  # the Firebird error itself
        return f"Rendered SQL: {checked.sql}\nFirebird error: {type(error).__name__}: {error}"
    return f"Rendered SQL: {checked.sql}\nThe second run answered; the first failure did not repeat."


def _answer(user: User, sql: str, limits: Limits = DEFAULT_LIMITS) -> Answered:
    outcome = run_question(HrHost(), user, sql, limits)
    if isinstance(outcome, Refused):
        pytest.fail(f"Refused: {outcome.reason}\n{_diagnose(user, sql)}")
    assert isinstance(outcome, Answered)
    return outcome


def _login(name: str, role: str) -> User:
    user = User.objects.create_user(f"{name}_{uuid.uuid4().hex[:8]}", password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # a fresh permission cache


@contextmanager
def _branch_user(branch: Branch) -> Iterator[User]:
    """An HR login whose data scope is limited to one branch. Removed afterwards."""
    user = _login("gov_branch", roles.HR)
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk])
    user = User.objects.get(pk=user.pk)
    try:
        yield user
    finally:
        User.objects.filter(pk=user.pk).delete()


@contextmanager
def _bulk_employees(branch: Branch, count: int) -> Iterator[list[int]]:
    """`count` committed employees in `branch`, named with one tag so they can be found and removed."""
    tag = uuid.uuid4().hex[:6]
    Employee.objects.bulk_create(
        [Employee(given_name=f"Bulk{tag}-{i:03d}", family_name="Bulk", gender="M", branch=branch) for i in range(count)]
    )
    try:
        yield list(Employee.objects.filter(given_name__startswith=f"Bulk{tag}").values_list("pk", flat=True))
    finally:
        Employee.objects.filter(given_name__startswith=f"Bulk{tag}").delete()


@contextmanager
def _leave(employee: Employee, start: date, end: date) -> Iterator[int]:
    """An approved leave for `employee` from `start` to `end`, with a leave type of its own. Removed afterwards."""
    leave_type = LeaveTypeRow.objects.create(name=f"Gate {uuid.uuid4().hex[:8]}")
    row = LeaveAssign.objects.create(
        employee=employee,
        leave_type=leave_type,
        date1=start,
        date2=end,
        status=LeaveAssign.APPROVED,
        adays=(end - start).days + 1,
    )
    try:
        yield int(row.pk)
    finally:
        LeaveAssign.objects.filter(pk=row.pk).delete()
        LeaveTypeRow.objects.filter(pk=leave_type.pk).delete()


@contextmanager
def _family_relation(fm_type: str, name: str, created: list[int]) -> Iterator[int]:
    """The family relation for `fm_type` (reused when the database already has one, else made and removed)."""
    found = FamilyRelation.objects.filter(fm_type=fm_type).first()
    if found is not None:
        yield int(found.pk)
        return
    made = FamilyRelation.objects.create(name=name, fm_type=fm_type)
    created.append(int(made.pk))
    yield int(made.pk)


def test_children_question_counts_each_employee_once(ready: World) -> None:
    tag = uuid.uuid4().hex[:6]
    anna, bold, cora = f"Anna{tag}", f"Bold{tag}", f"Cora{tag}"
    Employee.objects.filter(pk=ready.emp_a.pk).update(given_name=anna)  # two children
    Employee.objects.filter(pk=ready.emp_b.pk).update(given_name=bold)  # one child, plus a relative who is not counted
    Employee.objects.filter(pk=ready.emp_none.pk).update(given_name=cora)  # no children
    created_relations: list[int] = []
    made_rows: list[int] = []
    try:
        with (
            _family_relation("son", "Хүү", created_relations) as son,
            _family_relation("daughter", "Охин", created_relations) as daughter,
            _family_relation("dad", "Аав", created_relations) as dad,
        ):
            for employee, relation, given in [
                (ready.emp_a, son, "Child one"),
                (ready.emp_a, daughter, "Child two"),
                (ready.emp_b, son, "Child three"),
                (ready.emp_b, dad, "Not a child"),
            ]:
                made_rows.append(
                    int(FamilyRow.objects.create(employee=employee, relation_id=relation, given_name=given).pk)
                )

            answer = _answer(ready.hr, CHILDREN_BY_NAME)

            child_parents = FamilyRow.objects.filter(
                employee__in=visible_employees(ready.hr), relation__fm_type__in=("son", "daughter")
            ).values_list("employee__given_name", flat=True)
            expected = Counter(str(name).strip() for name in child_parents)
            got = Counter({str(name).strip(): _int(count) for name, count in answer.result.rows})

            assert got == expected
            assert got[anna] == 2  # two children, one row each
            assert got[bold] == 1  # the relative is not a child
            assert cora not in got  # no children: not in the list at all
    finally:
        FamilyRow.objects.filter(pk__in=made_rows).delete()
        FamilyRelation.objects.filter(pk__in=created_relations).delete()


def test_branch_limited_user_sees_only_their_branch(ready: World) -> None:
    answer = _answer(ready.limited, EMP_IDS)

    assert _ids(answer) == _visible_ids(ready.limited)
    assert ready.emp_a.pk in _ids(answer)
    assert ready.emp_b.pk not in _ids(answer)
    assert ready.emp_none.pk not in _ids(answer)


def test_connection_reuse_never_leaks_between_users(ready: World) -> None:
    with _branch_user(ready.branch_b) as other:
        a_ids_1 = _ids(_answer(ready.limited, EMP_IDS))
        b_ids_1 = _ids(_answer(other, EMP_IDS))

        assert a_ids_1 == _visible_ids(ready.limited)
        assert b_ids_1 == _visible_ids(other)
        assert b_ids_1 & a_ids_1 == set()  # B's rows hold none of A's ids
        assert ready.emp_a.pk not in b_ids_1

        b_ids_2 = _ids(_answer(other, EMP_IDS))
        a_ids_2 = _ids(_answer(ready.limited, EMP_IDS))

        assert b_ids_2 == b_ids_1
        assert a_ids_2 == a_ids_1
        assert a_ids_2 & b_ids_2 == set()  # and the same the other way round
        assert ready.emp_b.pk not in a_ids_2


def test_model_sql_cannot_read_the_scope_table(ready: World) -> None:
    outcome = run_question(HrHost(), ready.hr, "SELECT EMP_ID FROM GOV_SCOPE")

    assert isinstance(outcome, Refused)
    assert "GOV_SCOPE" in outcome.reason


def test_model_sql_cannot_reach_real_tables(ready: World) -> None:
    real_table = str(Employee._meta.db_table)

    outcome = run_question(HrHost(), ready.hr, f"SELECT EMP_ID FROM {real_table}")  # noqa: S608 (checker refuses it)

    assert isinstance(outcome, Refused)
    assert real_table.upper() in outcome.reason.upper()


def test_filter_holds_with_250_visible_employees(ready: World) -> None:
    with _bulk_employees(ready.branch_a, 250) as bulk_a, _bulk_employees(ready.branch_b, 5) as hidden:
        assert len(bulk_a) == 250 and len(hidden) == 5
        visible_hr = _visible_ids(ready.hr)
        visible_limited = _visible_ids(ready.limited)

        hr_count = _int(_answer(ready.hr, COUNT_EMPLOYEES).result.rows[0][0])
        limited_count = _int(_answer(ready.limited, COUNT_EMPLOYEES).result.rows[0][0])
        limited_ids = _ids(_answer(ready.limited, EMP_IDS))

        assert len(visible_hr) >= 250 + 5 + 3  # the HR role sees every employee, including these
        assert hr_count == len(visible_hr)
        assert limited_count == len(visible_limited)
        assert limited_count < hr_count
        assert set(bulk_a) <= limited_ids  # the 250 in branch A are the limited user's
        assert set(hidden) & limited_ids == set()  # the 5 in branch B are hidden from it


def test_timeout_cancels_a_long_query(ready: World) -> None:
    with _bulk_employees(ready.branch_a, 250):
        started = time.monotonic()
        outcome = run_question(HrHost(), ready.hr, HEAVY, Limits(timeout_s=1.0))
        wall = time.monotonic() - started
        print(f"timeout test wall time: {wall:.2f} s")

        assert isinstance(outcome, Refused)
        assert outcome.reason == TIMEOUT_REASON
        assert wall < 8.0

        # The same connection still answers, and only with the scoped rows.
        answer = _answer(ready.hr, EMP_IDS)
        assert _ids(answer) == _visible_ids(ready.hr)
        limited = _answer(ready.limited, EMP_IDS)
        assert _ids(limited) == _visible_ids(ready.limited)


MODEL_SQL = [
    pytest.param("SELECT FIRST 3 FIRST_NAME FROM GOV_EMPLOYEES", id="first-3"),
    pytest.param("SELECT FIRST 2 SKIP 1 FIRST_NAME FROM GOV_EMPLOYEES", id="first-2-skip-1"),
    pytest.param("SELECT FIRST_NAME FROM GOV_EMPLOYEES ROWS 2", id="trailing-rows-2"),
    pytest.param("SELECT FIRST_NAME FROM GOV_EMPLOYEES FETCH FIRST 2 ROWS ONLY", id="fetch-first-2-rows-only"),
    pytest.param("SELECT SUBSTRING(FIRST_NAME FROM 1 FOR 2) FROM GOV_EMPLOYEES", id="substring"),
    pytest.param("SELECT CHAR_LENGTH(FIRST_NAME) FROM GOV_EMPLOYEES", id="char-length"),
    pytest.param("SELECT EXTRACT(YEAR FROM BIRTH_DATE) FROM GOV_EMPLOYEES", id="extract-year"),
    pytest.param("SELECT DATEDIFF(YEAR, BIRTH_DATE, CURRENT_DATE) FROM GOV_EMPLOYEES", id="datediff-year"),
    pytest.param("SELECT DATEADD(DAY, 5, HIRE_DATE) FROM GOV_EMPLOYEES", id="dateadd-day"),
    pytest.param("SELECT FIRST_NAME FROM GOV_EMPLOYEES WHERE BIRTH_DATE < CURRENT_DATE", id="where-current-date"),
    pytest.param(
        "SELECT EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM BIRTH_DATE) AS AGE FROM GOV_EMPLOYEES",
        id="extract-current-date-age",
    ),
    pytest.param(
        "SELECT CASE WHEN GENDER = 'F' THEN 'W' ELSE 'M' END FROM GOV_EMPLOYEES",
        id="case-when",
    ),
    pytest.param("SELECT COALESCE(DEPARTMENT_NAME, 'none') FROM GOV_EMPLOYEES", id="coalesce"),
    pytest.param(
        "WITH staff AS (SELECT EMP_ID, FIRST_NAME FROM GOV_EMPLOYEES) SELECT COUNT(*) FROM staff",
        id="cte",
    ),
    pytest.param(
        "SELECT EMP_ID FROM GOV_EMPLOYEES UNION SELECT EMP_ID FROM GOV_CHILDREN",
        id="union-of-views",
    ),
    pytest.param(
        "SELECT BRANCH_NAME, COUNT(*) FROM GOV_EMPLOYEES GROUP BY BRANCH_NAME HAVING COUNT(*) > 0",
        id="group-by-having",
    ),
    pytest.param("SELECT FIRST_NAME FROM GOV_EMPLOYEES ORDER BY FIRST_NAME", id="order-by"),
    pytest.param(
        "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE NOT EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = e.EMP_ID)",
        id="not-exists-leave",
    ),
    pytest.param(
        "SELECT COUNT(*) AS N FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_EMPLOYEES e WHERE e.EMP_ID = o.EMP_ID)",
        id="exists-orders-count",
    ),
]


@pytest.mark.parametrize("sql", MODEL_SQL)
def test_rendered_forms_run_on_firebird(ready: World, sql: str) -> None:
    answer = _answer(ready.hr, sql)

    assert len(answer.result.rows) > 0


def test_zero_visible_employees_returns_zero_rows_not_everything(ready: World) -> None:
    # No right and no own record: the catalogue is empty, so the checker refuses before any row is read.
    outcome = run_question(HrHost(), ready.nobody, COUNT_EMPLOYEES)
    assert isinstance(outcome, Refused)
    assert "not a governed view" in outcome.reason

    # A user who has the view but whose branch scope holds no employee gets zero rows, not everything.
    empty_branch = Branch.objects.create(name=f"Хоосон {uuid.uuid4().hex[:6]}")
    try:
        with _branch_user(empty_branch) as user:
            answer = _answer(user, COUNT_EMPLOYEES)
            assert _int(answer.result.rows[0][0]) == 0
            assert _ids(_answer(user, EMP_IDS)) == set()
    finally:
        Branch.objects.filter(pk=empty_branch.pk).delete()


ON_LEAVE_TODAY = "SELECT l.LEAVE_ID FROM GOV_LEAVE l WHERE l.START_DATE <= CURRENT_DATE AND l.END_DATE >= CURRENT_DATE"


def test_leave_ending_today_is_on_leave_today(ready: World) -> None:
    today = date.today()
    with _leave(ready.emp_a, today - timedelta(days=1), today) as leave_id:
        assert leave_id in _ids(_answer(ready.hr, ON_LEAVE_TODAY))


def test_leave_started_today_counts(ready: World) -> None:
    today = date.today()
    with _leave(ready.emp_a, today, today + timedelta(days=2)) as leave_id:
        assert leave_id in _ids(_answer(ready.hr, ON_LEAVE_TODAY))


def test_leave_ended_yesterday_is_not_on_leave_today(ready: World) -> None:
    today = date.today()
    with _leave(ready.emp_a, today - timedelta(days=2), today - timedelta(days=1)) as leave_id:
        assert leave_id not in _ids(_answer(ready.hr, ON_LEAVE_TODAY))

"""HrHost: runs a checked query as the asker, with the scope filled and rolled back, and cancels it. Firebird only.

The query is checked by hand here (CheckedQuery built directly) so the host is tested on its own; the checker has
its own tests in app/sqlcore.
"""

import threading
from collections.abc import Iterator

import pytest
from accounts.models import User
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, QueryTimeout, Result
from sqlcore.runner import Host

from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.host import HrHost
from hr_sql.tests.conftest import World

EMP_IDS = "SELECT EMP_ID FROM GOV_EMPLOYEES"
# Three system tables crossed: millions of rows, far longer than the cancel delay in the cancel test.
SLOW = "SELECT COUNT(*) FROM RDB$FIELDS A, RDB$FIELDS B, RDB$FIELDS C"


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


def _query(sql: str, views: frozenset[str] = frozenset({"GOV_EMPLOYEES"})) -> CheckedQuery:
    return CheckedQuery(sql=sql, views=views)


def _ids(result: Result) -> set[int]:
    return {int(str(row[0])) for row in result.rows}


def _scope_rows_after_commit() -> int:
    """GOV_SCOPE read in a fresh transaction: what survives the host's rollback."""
    with transaction.atomic(using=GOVERNED_ALIAS), governed_connection().cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM GOV_SCOPE")
        return int(cursor.fetchone()[0])


def _visible_ids(user: User) -> set[int]:
    from employees.access import visible_employees

    return {int(pk) for pk in visible_employees(user).values_list("pk", flat=True)}


def test_host_satisfies_the_runner_protocol() -> None:
    host: Host = HrHost()  # mypy checks the structure against sqlcore.runner.Host
    assert host is not None


def test_hr_user_sees_every_visible_employee(ready: World) -> None:
    result = HrHost().execute(ready.hr, _query(EMP_IDS), Limits())

    assert result.columns == ("EMP_ID",)
    assert _ids(result) == _visible_ids(ready.hr)
    assert result.truncated is False


def test_limited_user_sees_only_the_listed_branch(ready: World) -> None:
    result = HrHost().execute(ready.limited, _query(EMP_IDS), Limits())

    assert _ids(result) == _visible_ids(ready.limited)
    assert ready.emp_a.pk in _ids(result)
    assert ready.emp_b.pk not in _ids(result)


def test_user_with_no_visible_employees_gets_zero_rows(ready: World) -> None:
    result = HrHost().execute(ready.nobody, _query(EMP_IDS), Limits())

    assert result.rows == ()


def test_fetch_is_capped_at_max_rows_plus_one(ready: World) -> None:
    result = HrHost().execute(ready.hr, _query(EMP_IDS), Limits(max_rows=1))

    assert len(result.rows) == 2  # max_rows + 1: the runner decides the cap note


def test_scope_is_empty_after_a_successful_execute(ready: World) -> None:
    HrHost().execute(ready.hr, _query(EMP_IDS), Limits())

    assert _scope_rows_after_commit() == 0


def test_a_failure_inside_execute_still_leaves_the_scope_empty(ready: World) -> None:
    with pytest.raises(Exception):  # noqa: B017 (any database error will do)
        HrHost().execute(ready.hr, _query("SELECT * FROM GOV_NO_SUCH_VIEW"), Limits())

    assert _scope_rows_after_commit() == 0


def test_two_users_in_a_row_on_one_connection_do_not_see_each_other(ready: World) -> None:
    host = HrHost()

    everyone = _ids(host.execute(ready.hr, _query(EMP_IDS), Limits()))
    nothing = _ids(host.execute(ready.nobody, _query(EMP_IDS), Limits()))
    own = _ids(host.execute(ready.own, _query(EMP_IDS), Limits()))
    everyone_again = _ids(host.execute(ready.hr, _query(EMP_IDS), Limits()))

    assert ready.emp_b.pk in everyone
    assert nothing == set()
    assert own == {ready.emp_a.pk}
    assert everyone_again == everyone


def test_non_user_is_refused_and_gets_an_empty_catalogue(ready: World) -> None:
    host = HrHost()

    assert host.catalogue_for(AnonymousUser()).views == ()
    assert host.catalogue_for("not a user").views == ()
    with pytest.raises(PermissionError):
        host.execute(AnonymousUser(), _query(EMP_IDS), Limits())


def test_host_catalogue_matches_the_role_catalogue(ready: World) -> None:
    catalogue: Catalogue = HrHost().catalogue_for(ready.hr)

    assert catalogue.view_names() == frozenset({"GOV_EMPLOYEES", "GOV_CHILDREN", "GOV_LEAVE", "GOV_ORDERS"})


def test_cancel_stops_a_slow_query_and_the_connection_still_works(ready: World) -> None:
    host = HrHost()
    timer = threading.Timer(0.5, host.cancel, [ready.hr])
    timer.start()
    try:
        with pytest.raises(QueryTimeout):
            host.execute(ready.hr, _query(SLOW, frozenset()), Limits(timeout_s=0.5))
    finally:
        timer.cancel()

    result = host.execute(ready.hr, _query(EMP_IDS), Limits())
    assert _ids(result) == _visible_ids(ready.hr)
    assert _scope_rows_after_commit() == 0


def test_cancel_after_the_query_finished_is_harmless(ready: World) -> None:
    host = HrHost()
    host.execute(ready.hr, _query(EMP_IDS), Limits())

    host.cancel(ready.hr)  # nothing is running: must not raise
    result = host.execute(ready.hr, _query(EMP_IDS), Limits())

    assert _ids(result) == _visible_ids(ready.hr)


def test_cancel_from_another_user_does_not_stop_this_one(ready: World) -> None:
    host = HrHost()
    host.cancel(ready.nobody)  # no run for this user: a no-op

    assert _ids(host.execute(ready.hr, _query(EMP_IDS), Limits())) == _visible_ids(ready.hr)

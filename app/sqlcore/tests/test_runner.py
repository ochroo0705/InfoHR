import threading
import time

import pytest

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, QueryTimeout, Result
from sqlcore.runner import Answered, Host, Refused, run_question

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children of employees",
    columns=(Column("EMPLOYEE_ID", "employee id"),),
)
FULL = Catalogue(views=(EMPLOYEES, CHILDREN))
ONLY_CHILDREN = Catalogue(views=(CHILDREN,))

GOOD_SQL = "SELECT e.NAME FROM GOV_EMPLOYEES e"


class FakeHost:
    """A host that records every call. Rows are returned up to the cap plus one, as the Protocol says."""

    def __init__(self, catalogues: dict[object, Catalogue], rows: list[tuple[object, ...]] | None = None) -> None:
        self.catalogues = catalogues
        self.rows: list[tuple[object, ...]] = rows if rows is not None else [("Aigerim",), ("Bat",)]
        self.execute_calls: list[tuple[object, CheckedQuery, Limits]] = []
        self.cancel_calls: list[object] = []
        self.error: Exception | None = None

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogues[user]

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append((user, query, limits))
        if self.error is not None:
            raise self.error
        returned = tuple(self.rows[: limits.max_rows + 1])
        return Result(columns=("NAME",), rows=returned, truncated=False)

    def cancel(self, user: object) -> None:
        self.cancel_calls.append(user)


class SlowHost(FakeHost):
    """A host whose query runs until cancel is called, then raises QueryTimeout."""

    def __init__(self, catalogues: dict[object, Catalogue]) -> None:
        super().__init__(catalogues)
        self.stop = threading.Event()

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append((user, query, limits))
        if self.stop.wait(timeout=2.0):
            raise QueryTimeout()
        return Result(columns=("NAME",), rows=(), truncated=False)

    def cancel(self, user: object) -> None:
        self.cancel_calls.append(user)
        self.stop.set()


def test_refused_when_check_fails() -> None:
    host = FakeHost({"asker": FULL})

    outcome = run_question(host, "asker", "DELETE FROM GOV_EMPLOYEES")

    assert isinstance(outcome, Refused)
    assert outcome.reason
    assert host.execute_calls == []


def test_truncated_when_host_returns_more_than_cap() -> None:
    host = FakeHost({"asker": FULL}, rows=[("A",), ("B",), ("C",), ("D",)])

    outcome = run_question(host, "asker", GOOD_SQL, Limits(max_rows=3, timeout_s=5.0))

    assert isinstance(outcome, Answered)
    assert len(outcome.result.rows) == 3
    assert outcome.result.truncated is True


def test_exactly_cap_is_not_truncated() -> None:
    host = FakeHost({"asker": FULL}, rows=[("A",), ("B",), ("C",)])

    outcome = run_question(host, "asker", GOOD_SQL, Limits(max_rows=3, timeout_s=5.0))

    assert isinstance(outcome, Answered)
    assert len(outcome.result.rows) == 3
    assert outcome.result.truncated is False


def test_timeout_calls_cancel() -> None:
    host = SlowHost({"asker": FULL})

    outcome = run_question(host, "asker", GOOD_SQL, Limits(max_rows=10, timeout_s=0.05))

    assert isinstance(outcome, Refused)
    assert host.cancel_calls == ["asker"]


def test_empty_result_is_answered_not_refused() -> None:
    host = FakeHost({"asker": FULL}, rows=[])

    outcome = run_question(host, "asker", GOOD_SQL)

    assert isinstance(outcome, Answered)
    assert outcome.result.rows == ()
    assert outcome.result.truncated is False
    assert outcome.query.views == frozenset({"GOV_EMPLOYEES"})


def test_only_catalogue_of_this_user_is_used() -> None:
    host = FakeHost({"alice": FULL, "bob": ONLY_CHILDREN})

    alice = run_question(host, "alice", GOOD_SQL)
    bob = run_question(host, "bob", GOOD_SQL)

    assert isinstance(alice, Answered)
    assert isinstance(bob, Refused)
    assert [call[0] for call in host.execute_calls] == ["alice"]


def test_host_exception_becomes_generic_refusal_without_its_text() -> None:
    host = FakeHost({"asker": FULL})
    host.error = RuntimeError("secret path C:\\data\\MACSXE4DB.FDB failed")

    outcome = run_question(host, "asker", GOOD_SQL)

    assert isinstance(outcome, Refused)
    assert outcome.reason == "The query could not be run."
    assert "MACSXE4DB" not in outcome.reason
    assert "secret" not in outcome.reason


def test_timer_is_cancelled_after_fast_query() -> None:
    host = FakeHost({"asker": FULL})

    outcome = run_question(host, "asker", GOOD_SQL, Limits(max_rows=10, timeout_s=0.05))
    time.sleep(0.2)

    assert isinstance(outcome, Answered)
    assert host.cancel_calls == []


@pytest.mark.parametrize(
    "limits",
    [
        Limits(max_rows=0, timeout_s=5.0),
        Limits(max_rows=-1, timeout_s=5.0),
        Limits(max_rows=10, timeout_s=0.0),
        Limits(max_rows=10, timeout_s=-2.0),
    ],
)
def test_invalid_limits_raise_value_error(limits: Limits) -> None:
    host = FakeHost({"asker": FULL})

    with pytest.raises(ValueError):
        run_question(host, "asker", GOOD_SQL, limits)
    assert host.execute_calls == []


def test_host_is_a_protocol_the_fake_satisfies() -> None:
    host: Host = FakeHost({"asker": FULL})

    assert isinstance(run_question(host, "asker", GOOD_SQL), Answered)

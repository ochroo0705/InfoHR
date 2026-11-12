"""Tests for marking an answer correct (Task 15a): the propose view, the card button, and the admin review queue.

The SQL is checked for real against the governed catalogue (hr_sql.catalogue.catalogue_for); no Firebird connection is
used. Every test that writes rows runs on PostgreSQL.
"""

import dataclasses
import itertools
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from assistant.models import HelpQuestion, Outcome, VerifiedQuery, VerifiedStatus
from assistant.services import Answer
from assistant.sqlanswer import SqlAnswer

pytestmark = pytest.mark.django_db

PASSWORD = "Test-pass-1"  # noqa: S105
MARK = reverse("assistant:sql_verify")
CHANGELIST = reverse("admin:assistant_verifiedquery_changelist")
QUESTION = "Хэдэн хүүхэдтэй вэ"
GOOD_SQL = "SELECT COUNT(*) FROM GOV_CHILDREN"
JOIN_SQL = (
    "SELECT e.LAST_NAME, COUNT(*) FROM GOV_EMPLOYEES e "
    "JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID GROUP BY e.LAST_NAME"
)
SALARY_SQL = "SELECT COUNT(*) FROM GOV_SALARY"
_COUNTER = itertools.count(1)


def _question(user: User, sql: str = GOOD_SQL, outcome: Outcome = Outcome.SQL, text: str = QUESTION) -> HelpQuestion:
    """A logged answer of `user`: the SQL outcome with its checked SQL, unless the test says otherwise."""
    return HelpQuestion.objects.create(user=user, question=text, outcome=outcome, sql=sql)


def _mark(client: Client, question_id: int) -> dict[str, object]:
    response = client.post(MARK, {"question_id": str(question_id)})
    assert response.status_code == 200
    data: dict[str, object] = response.json()
    return data


def _reviewer(role_user: Callable[[str], User], kind: str = "hr") -> User:
    """A staff login that may review verified queries (the model's view and change rights)."""
    user = role_user(kind)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="assistant", codename__in=["view_verifiedquery", "change_verifiedquery"]
        )
    )
    return user


def _approve(client: Client, reviewer: User, row: VerifiedQuery) -> None:
    client.force_login(reviewer)
    client.post(CHANGELIST, {"action": "approve", "_selected_action": [row.pk]})


def _reject(client: Client, reviewer: User, row: VerifiedQuery) -> None:
    client.force_login(reviewer)
    client.post(CHANGELIST, {"action": "reject", "_selected_action": [row.pk]})


def _employee(given: str) -> None:
    """One employee with the given name, so the question can name them (the same hire as the corrections tests)."""
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = hire_values(f"УБ{next(_COUNTER):08d}") | {"given_name": given}
    history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=User.objects.create_user(f"verify_actor_{next(_COUNTER)}", password=PASSWORD),
    )


def _ok_answer() -> SqlAnswer:
    return SqlAnswer(
        status="ok",
        reason="",
        columns=("N",),
        rows=((3,),),
        sql=GOOD_SQL,
        explanation=None,
        row_count=1,
        salary=False,
    )


def test_marking_creates_one_proposed_row_per_answer(client: Client, role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    client.force_login(user)
    question = _question(user)
    assert _mark(client, question.pk) == {"ok": True}
    assert _mark(client, question.pk) == {"ok": True}
    rows = VerifiedQuery.objects.filter(source=question)
    assert rows.count() == 1
    row = rows.get()
    assert (row.status, row.proposed_by, row.sql, row.question) == (
        VerifiedStatus.PROPOSED,
        user,
        GOOD_SQL,
        QUESTION,
    )


def test_cannot_mark_someone_elses_question(client: Client, role_user: Callable[[str], User]) -> None:
    owner = role_user("hr")
    other = role_user("hr")
    question = _question(owner)
    client.force_login(other)
    assert _mark(client, question.pk) == {"ok": False}
    assert not VerifiedQuery.objects.filter(source=question).exists()


def test_cannot_mark_a_non_sql_answer(client: Client, role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    client.force_login(user)
    table_answer = _question(user, sql="", outcome=Outcome.SQL)
    other_outcome = _question(user, sql=GOOD_SQL, outcome=Outcome.NONE)
    assert _mark(client, table_answer.pk) == {"ok": False}
    assert _mark(client, other_outcome.pk) == {"ok": False}
    assert not VerifiedQuery.objects.exists()


def test_second_mark_is_ignored(client: Client, role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    client.force_login(user)
    question = _question(user)
    assert _mark(client, question.pk) == {"ok": True}
    VerifiedQuery.objects.filter(source=question).update(status=VerifiedStatus.REJECTED)
    assert _mark(client, question.pk) == {"ok": True}
    assert VerifiedQuery.objects.filter(source=question).count() == 1
    assert VerifiedQuery.objects.get(source=question).status == VerifiedStatus.REJECTED


def test_card_shows_the_button_only_for_an_ok_answer() -> None:
    ok = Answer(
        outcome=Outcome.SQL, entry=None, also=None, lead="", tool="sql", sql=_ok_answer(), question_id=7
    )
    html = render_to_string("assistant/_answer.html", {"result": ok})
    assert "Зөв гэж тэмдэглэх" in html
    assert f'data-verify-url="{MARK}"' in html
    assert 'data-verify-id="7"' in html

    unsaved = dataclasses.replace(ok, question_id=0)
    assert "Зөв гэж тэмдэглэх" not in render_to_string("assistant/_answer.html", {"result": unsaved})

    refused = Answer(
        outcome=Outcome.NONE,
        entry=None,
        also=None,
        lead="",
        tool="sql",
        sql_status="refused",
        question_id=7,
    )
    assert "Зөв гэж тэмдэглэх" not in render_to_string("assistant/_answer.html", {"result": refused})


def test_views_field_lists_the_views_the_sql_uses(client: Client, role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    client.force_login(user)
    question = _question(user, sql=JOIN_SQL)
    # The client's own `views` value is ignored: the field comes from the checker.
    response = client.post(MARK, {"question_id": str(question.pk), "views": "GOV_SALARY"})
    assert response.json() == {"ok": True}
    assert VerifiedQuery.objects.get(source=question).views == "GOV_CHILDREN,GOV_EMPLOYEES"


def test_unauthenticated_post_is_refused(client: Client, role_user: Callable[[str], User]) -> None:
    question = _question(role_user("hr"))
    response = client.post(MARK, {"question_id": str(question.pk)})
    assert response.status_code == 302
    assert "/login/" in response["Location"]
    assert not VerifiedQuery.objects.exists()


def test_approve_rechecks_the_sql_against_the_proposers_catalogue(
    client: Client, role_user: Callable[[str], User]
) -> None:
    proposer = role_user("accountant")  # may read the salary views when the answer is proposed
    client.force_login(proposer)
    question = _question(proposer, sql=SALARY_SQL)
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    proposer.groups.set([Group.objects.get(name=roles.HR)])  # the proposer loses the salary right afterwards
    _approve(client, _reviewer(role_user), row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.PROPOSED


def test_approve_accepts_a_query_that_still_passes(client: Client, role_user: Callable[[str], User]) -> None:
    proposer = role_user("hr")
    client.force_login(proposer)
    question = _question(proposer)
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    reviewer = _reviewer(role_user)
    _approve(client, reviewer, row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.APPROVED
    assert row.reviewed_by == reviewer
    assert row.reviewed_at is not None


def test_approve_refuses_names_in_the_question(client: Client, role_user: Callable[[str], User]) -> None:
    _employee("Тэмүүлэн")
    proposer = role_user("hr")
    client.force_login(proposer)
    question = _question(proposer, text="Тэмүүлэн хэдэн хүүхэдтэй вэ")
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    _approve(client, _reviewer(role_user), row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.PROPOSED


def test_reviewer_cannot_approve_their_own_proposal(client: Client, role_user: Callable[[str], User]) -> None:
    reviewer = _reviewer(role_user)
    client.force_login(reviewer)
    question = _question(reviewer)
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    _approve(client, reviewer, row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.PROPOSED
    _approve(client, _reviewer(role_user), row)  # a second reviewer may
    row.refresh_from_db()
    assert row.status == VerifiedStatus.APPROVED


def test_approval_needs_the_change_permission(client: Client, role_user: Callable[[str], User]) -> None:
    proposer = role_user("hr")
    client.force_login(proposer)
    question = _question(proposer)
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    no_right = role_user("hr")
    no_right.is_staff = True
    no_right.save(update_fields=["is_staff"])
    _approve(client, no_right, row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.PROPOSED


def test_reject_marks_the_row_rejected(client: Client, role_user: Callable[[str], User]) -> None:
    proposer = role_user("hr")
    client.force_login(proposer)
    question = _question(proposer)
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    reviewer = _reviewer(role_user)
    _reject(client, reviewer, row)
    row.refresh_from_db()
    assert row.status == VerifiedStatus.REJECTED
    assert row.reviewed_by == reviewer


def _propose_and_approve(client: Client, role_user: Callable[[str], User], sql: str, kind: str = "hr") -> VerifiedQuery:
    """A proposal of `sql` by a `kind` user, then an approval attempt by another reviewer. Returns the row."""
    proposer = role_user(kind)
    client.force_login(proposer)
    question = _question(proposer, sql=sql, text="Нэгэн асуулт")
    assert _mark(client, question.pk) == {"ok": True}
    row = VerifiedQuery.objects.get(source=question)
    _approve(client, _reviewer(role_user), row)
    row.refresh_from_db()
    return row


def test_approve_refuses_sql_naming_a_person_by_name(client: Client, role_user: Callable[[str], User]) -> None:
    row = _propose_and_approve(
        client, role_user, "SELECT COUNT(*) FROM GOV_EMPLOYEES WHERE LAST_NAME = 'Бат'"
    )
    assert row.status == VerifiedStatus.PROPOSED


def test_approve_refuses_sql_naming_a_person_by_id(client: Client, role_user: Callable[[str], User]) -> None:
    row = _propose_and_approve(client, role_user, "SELECT COUNT(*) FROM GOV_CHILDREN WHERE EMP_ID = 123")
    assert row.status == VerifiedStatus.PROPOSED


def test_approve_accepts_gender_and_status_literals(client: Client, role_user: Callable[[str], User]) -> None:
    row = _propose_and_approve(client, role_user, "SELECT COUNT(*) FROM GOV_EMPLOYEES WHERE GENDER = 'F'")
    assert row.status == VerifiedStatus.APPROVED


def test_approve_accepts_numeric_thresholds(client: Client, role_user: Callable[[str], User]) -> None:
    row = _propose_and_approve(
        client, role_user, "SELECT COUNT(*) FROM GOV_LOANS WHERE AMOUNT > 1000000", kind="accountant"
    )
    assert row.status == VerifiedStatus.APPROVED

"""Tests for the approved examples (Task 15b): which approved queries reach the model, and the drift check.

The examples come from the test database (PostgreSQL); the catalogues are plain sqlcore objects, so no host and no
Firebird connection are used. The security rule under test: an example is offered only when every view it uses is in
the asker's catalogue.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from sqlcore.catalogue import Catalogue, Column, View

from assistant.models import VerifiedQuery, VerifiedStatus
from assistant.verified import examples_for, stale_examples

CHILDREN = View(name="GOV_CHILDREN", description="Children.", columns=(Column("EMP_ID", "Employee id"),))
SALARY = View(name="GOV_SALARY", description="Salary.", columns=(Column("EMP_ID", "Employee id"),))
LOANS = View(name="GOV_LOANS", description="Loans.", columns=(Column("EMP_ID", "Employee id"),))
COUNT_SQL = "SELECT COUNT(*) AS N FROM GOV_CHILDREN"
SALARY_SQL = "SELECT EMP_ID FROM GOV_SALARY"


def _approve(question: str, views: str, sql: str = COUNT_SQL) -> VerifiedQuery:
    return VerifiedQuery.objects.create(question=question, sql=sql, views=views, status=VerifiedStatus.APPROVED)


@pytest.mark.django_db
def test_examples_only_from_views_the_asker_may_use() -> None:
    _approve("Хүүхдийн тоо", "GOV_CHILDREN")
    _approve("Хүүхдийн цалин", "GOV_CHILDREN,GOV_SALARY", SALARY_SQL)
    _approve("Цалингийн жагсаалт", "GOV_SALARY", SALARY_SQL)
    asker = Catalogue(views=(CHILDREN,))

    shown = examples_for(asker, "Хүүхдийн тоо, цалингийн жагсаалт")

    assert [question for question, _ in shown] == ["Хүүхдийн тоо"]


@pytest.mark.django_db
def test_salary_example_reaches_an_asker_who_has_the_salary_view() -> None:
    _approve("Цалингийн жагсаалт", "GOV_SALARY", SALARY_SQL)
    asker = Catalogue(views=(CHILDREN, SALARY, LOANS))

    shown = examples_for(asker, "Цалингийн жагсаалт")

    assert shown == (("Цалингийн жагсаалт", SALARY_SQL),)


@pytest.mark.django_db
def test_rejected_and_proposed_are_never_used() -> None:
    VerifiedQuery.objects.create(question="Хүүхдийн тоо", sql=COUNT_SQL, views="GOV_CHILDREN")
    VerifiedQuery.objects.create(
        question="Хүүхдийн тоо", sql=COUNT_SQL, views="GOV_CHILDREN", status=VerifiedStatus.REJECTED
    )
    asker = Catalogue(views=(CHILDREN,))

    assert examples_for(asker, "Хүүхдийн тоо") == ()


@pytest.mark.django_db
def test_examples_need_a_shared_word() -> None:
    _approve("Ажилтны жагсаалт", "GOV_CHILDREN")
    asker = Catalogue(views=(CHILDREN,))

    assert examples_for(asker, "Хүүхдийн тоо") == ()


@pytest.mark.django_db
def test_examples_rank_by_shared_words_then_newest_first() -> None:
    _approve("Хүүхдийн нас", "GOV_CHILDREN")  # one shared word
    _approve("Хүүхдийн тоо хэд", "GOV_CHILDREN")  # three shared words
    _approve("Хүүхдийн жагсаалт", "GOV_CHILDREN")  # one shared word, newer than the first
    asker = Catalogue(views=(CHILDREN,))

    shown = examples_for(asker, "хүүхдийн тоо хэд вэ")

    assert [question for question, _ in shown] == ["Хүүхдийн тоо хэд", "Хүүхдийн жагсаалт", "Хүүхдийн нас"]


@pytest.mark.django_db
def test_examples_respect_the_limit() -> None:
    for index in range(4):
        _approve(f"Хүүхдийн асуулт {index}", "GOV_CHILDREN")
    asker = Catalogue(views=(CHILDREN,))

    assert len(examples_for(asker, "Хүүхдийн асуулт", limit=2)) == 2


@pytest.mark.django_db
def test_drift_check_lists_a_stale_example_and_exits_nonzero() -> None:
    fresh = _approve("Хүүхдийн тоо", "GOV_CHILDREN")
    stale = _approve("Хүүхдийн нэр", "GOV_CHILDREN", "SELECT NO_SUCH_COLUMN FROM GOV_CHILDREN")
    _approve("Хүүхдийн хүснэгт", "GOV_CHILDREN", "SELECT COUNT(*) AS N FROM GOV_NOPE")
    VerifiedQuery.objects.create(question="Хэрэглэгдээгүй", sql="SELECT NO_SUCH FROM GOV_NOPE", views="GOV_NOPE")

    found = {item.pk for item in stale_examples()}

    assert fresh.pk not in found
    assert stale.pk in found
    assert len(found) == 2

    out = StringIO()
    with pytest.raises(CommandError, match="2 approved example"):
        call_command("governed_examples", "check", stdout=out, stderr=out)
    assert str(stale.pk) in out.getvalue()


@pytest.mark.django_db
def test_drift_check_passes_when_every_approved_example_checks() -> None:
    _approve("Хүүхдийн тоо", "GOV_CHILDREN")

    assert stale_examples() == []

    out = StringIO()
    call_command("governed_examples", "check", stdout=out)
    assert "pass the checker" in out.getvalue()

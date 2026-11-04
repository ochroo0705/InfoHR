"""Tests for the learning-loop correction rules: duplicate, similarity and the employee-name hints."""

import itertools
from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from assistant import learning
from assistant.entries import ENTRIES
from assistant.evalset import CASES
from assistant.models import HelpExample, Kind

pytestmark = pytest.mark.django_db

KEY = "leave.record"
_REGISTER = itertools.count(1)
SHIPPED = next(example for entry in ENTRIES for example in entry.examples)
SHIPPED_ENTRY = next(entry.key for entry in ENTRIES if SHIPPED in entry.examples)


def _one_letter_changed(text: str) -> str:
    """The same question with one letter in the middle swapped: still close enough to count as a near-copy."""
    middle = len(text) // 2
    swap = "а" if text[middle] != "а" else "о"
    return text[:middle] + swap + text[middle + 1 :]


def _employee(given: str) -> None:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = hire_values(f"УБ{next(_REGISTER):08d}") | {"given_name": given}
    history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=User.objects.create_user(f"learn_{next(_REGISTER)}"),
    )


def test_inactive_orphan_allowed() -> None:
    assert learning.check("x", "leave.gone", Kind.EXAMPLE, active=False) == []


def test_unknown_entry() -> None:
    assert learning.check("яаж чөлөө бүртгэх вэ", "no.such.entry", Kind.EXAMPLE, True) == [
        "Энэ хариулт байхгүй болсон байна."
    ]


def test_inactive_skips_checks() -> None:
    assert learning.check(_one_letter_changed(SHIPPED), SHIPPED_ENTRY, Kind.TEST, False) == []


def test_duplicate() -> None:
    HelpExample.objects.create(question="Яаж чөлөө бүртгэх вэ", entry=KEY, active=True)
    assert learning.check("яаж ЧӨЛӨӨ бүртгэх вэ", KEY, Kind.EXAMPLE, True) == [
        "Энэ асуулт аль хэдийн бүртгэгдсэн байна."
    ]
    assert learning.check("яаж өлөө бүртгэх вэ", KEY, Kind.EXAMPLE, True) == []


def test_duplicate_ignores_own_row() -> None:
    own = HelpExample.objects.create(question="яаж чөлөө бүртгэх вэ", entry=KEY, active=True)
    assert learning.check("яаж чөлөө бүртгэх вэ", KEY, Kind.EXAMPLE, True, exclude_pk=own.pk) == []


def test_test_close_to_shipped_example() -> None:
    assert learning.check(_one_letter_changed(SHIPPED), SHIPPED_ENTRY, Kind.TEST, True) == [
        "Энэ асуулт жишээтэй хэт ойролцоо байна: тест болгож болохгүй."
    ]


def test_example_close_to_shipped_case() -> None:
    case = CASES[0].question
    assert learning.check(_one_letter_changed(case), KEY, Kind.EXAMPLE, True) == [
        "Энэ асуулт тесттэй хэт ойролцоо байна."
    ]


def test_test_close_to_local_example() -> None:
    HelpExample.objects.create(question="Бат ирэх долоо хоногт 5 хоног амарна", entry=KEY, active=True)
    assert learning.check("Бат ирэх долоо хоногт 5 хоног амарна гэж", KEY, Kind.TEST, True) == [
        "Энэ асуулт жишээтэй хэт ойролцоо байна: тест болгож болохгүй."
    ]


def test_example_close_to_local_test() -> None:
    HelpExample.objects.create(question="Бат ирэх долоо хоногт 5 хоног амарна", entry=KEY, kind=Kind.TEST, active=True)
    assert learning.check("Бат ирэх долоо хоногт 5 хоног амарна гэж", KEY, Kind.EXAMPLE, True) == [
        "Энэ асуулт тесттэй хэт ойролцоо байна."
    ]


def test_check_runs_on_activation() -> None:
    HelpExample.objects.create(question="Бат ирэх долоо хоногт 5 хоног амарна", entry=KEY, active=True)
    inactive_test = HelpExample.objects.create(
        question="Бат ирэх долоо хоногт 5 хоног амарна гэж", entry=KEY, kind=Kind.TEST, active=False
    )
    assert learning.check(inactive_test.question, KEY, Kind.TEST, True, exclude_pk=inactive_test.pk) == [
        "Энэ асуулт жишээтэй хэт ойролцоо байна: тест болгож болохгүй."
    ]


def test_words_not_compared() -> None:
    word = next(w for entry in ENTRIES for w in entry.words if w not in {e for x in ENTRIES for e in x.examples})
    assert learning.check(word, KEY, Kind.TEST, True) == []


def test_name_hits() -> None:
    _employee("Номин")
    assert learning.name_hits("Номин өнөөдөр өвдөөд ирээгүй") == ["Номин"]
    assert learning.name_hits("чөлөө бүртгэх") == []


def test_name_hits_keeps_spelling_and_skips_repeats() -> None:
    _employee("Номин")
    assert learning.name_hits("НОМИН, Номин!") == ["НОМИН"]


def test_short_names_ignored() -> None:
    _employee("Ой")
    assert learning.name_hits("Ой ирлээ") == []

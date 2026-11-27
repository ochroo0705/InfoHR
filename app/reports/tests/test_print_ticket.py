"""The print ticket (reports.services.exports.ticket_make / ticket_read): a signed, compressed carry of the picked
selection from the selection bar to the print page, valid for one user and one report for a few minutes."""

import random
from typing import Any

import pytest
from accounts.models import User
from django.core import signing

from reports.selection import SelectionError
from reports.services.exports import TICKET_INVALID, TICKET_SALT, ticket_make, ticket_read
from reports.tests.conftest import _make_user

pytestmark = pytest.mark.django_db

KEY = "staff-list"
QUERY = "state=all&cols=code&cols=name"


def test_round_trip_returns_the_inputs(hr_user: User) -> None:
    ids = ["12", "7", "300"]
    ticket = ticket_make(hr_user, KEY, QUERY, ids, False)
    assert ticket_read(hr_user, KEY, ticket) == (QUERY, ids, False)


def test_round_trip_keeps_all_flag(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, [], True)
    assert ticket_read(hr_user, KEY, ticket) == (QUERY, [], True)


def test_another_user_is_refused(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, ["1"], False)
    other = _make_user("HR", "other-hr")
    with pytest.raises(SelectionError) as refused:
        ticket_read(other, KEY, ticket)
    assert refused.value.message == TICKET_INVALID


def test_another_report_key_is_refused(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, ["1"], False)
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, "leave-balances", ticket)
    assert refused.value.message == TICKET_INVALID


def test_expired_ticket_is_refused(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, ["1"], False)
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, KEY, ticket, max_age=-1)  # any ticket is older than a negative age
    assert refused.value.message == TICKET_INVALID


def test_ticket_inside_max_age_is_accepted(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, ["1"], False)
    assert ticket_read(hr_user, KEY, ticket, max_age=600) == (QUERY, ["1"], False)


@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_tampered_ticket_is_refused(hr_user: User, position: str) -> None:
    ticket = ticket_make(hr_user, KEY, QUERY, ["1", "2"], False)
    index = {"start": 1, "middle": len(ticket) // 2, "end": len(ticket) - 1}[position]
    flipped = "A" if ticket[index] != "A" else "B"
    tampered = ticket[:index] + flipped + ticket[index + 1 :]
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, KEY, tampered)
    assert refused.value.message == TICKET_INVALID


def test_garbage_ticket_is_refused(hr_user: User) -> None:
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, KEY, "not-a-ticket")
    assert refused.value.message == TICKET_INVALID


def test_all_ticket_stays_short(hr_user: User) -> None:
    ticket = ticket_make(hr_user, KEY, "state=all", [], True)
    assert len(ticket) < 400


def test_500_random_12_digit_ids_stay_under_6000_characters(hr_user: User) -> None:
    rng = random.Random(20261127)  # noqa: S311 (test data, not a secret); seeded so every run is the same
    ids = [str(rng.randrange(10**11, 10**12)) for _ in range(500)]  # 12 digits each: the longest ids allowed
    ticket = ticket_make(hr_user, KEY, QUERY, ids, False)
    assert len(ticket) < 6000
    assert ticket_read(hr_user, KEY, ticket) == (QUERY, ids, False)


def test_500_realistic_ids_up_to_20000_stay_under_4000_characters(hr_user: User) -> None:
    rng = random.Random(20261128)  # noqa: S311 (test data, not a secret)
    ids = [str(rng.randrange(1, 20001)) for _ in range(500)]  # ids of up to five digits
    ticket = ticket_make(hr_user, KEY, QUERY, ids, False)
    assert len(ticket) < 4000
    assert ticket_read(hr_user, KEY, ticket) == (QUERY, ids, False)


def _signed(payload: Any) -> str:
    """A ticket signed with the module's real salt, so only the payload's shape is wrong."""
    return signing.dumps(payload, salt=TICKET_SALT, compress=True)


BASE = {"u": None, "k": KEY, "q": QUERY, "i": ["1"], "a": False}  # "u" is filled in per test


@pytest.mark.parametrize(
    "payload",
    [
        {**BASE, "i": [1]},  # an id that is a number, not text
        {**BASE, "i": [None]},  # an empty id
        {**BASE, "i": ["1", 2]},  # one bad id among good ones
        {k: v for k, v in BASE.items() if k != "q"},  # the query is missing
        {**BASE, "a": "no"},  # "all" is text, not a bool
        {**BASE, "a": 0},  # "all" is a number, not a bool
        {k: v for k, v in BASE.items() if k != "k"},  # the report key is missing
        ["not", "a", "dict"],  # the payload is a list
        "just text",  # the payload is text
    ],
)
def test_bad_payload_shape_is_refused(hr_user: User, payload: Any) -> None:
    if isinstance(payload, dict):
        payload = {**payload, "u": hr_user.pk}  # the right user, so only the shape is wrong
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, KEY, _signed(payload))
    assert refused.value.message == TICKET_INVALID


def test_missing_user_field_is_refused(hr_user: User) -> None:
    payload = {k: v for k, v in BASE.items() if k != "u"}
    with pytest.raises(SelectionError) as refused:
        ticket_read(hr_user, KEY, _signed(payload))
    assert refused.value.message == TICKET_INVALID

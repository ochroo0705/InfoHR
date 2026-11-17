import json
import secrets
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from accounts.roles import HR
from django.contrib.auth.models import Group
from django.test import Client
from employees.models import Employee
from employees.services import history, macs_writes

pytestmark = pytest.mark.django_db

PASSWORD = secrets.token_urlsafe(16)
EMERGENCY_GAP = 2  # attention.MISSING
GROUP_LIMIT = 3  # attention.GROUP_LIMIT
GAP_PAGE = 8  # attention.GAP_PAGE


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("attention-hr", password=PASSWORD, is_active=True)
    user.groups.add(Group.objects.get_or_create(name=HR)[0])
    return user


def _hire_without_contact(actor: User, index: int, job: dict[str, Any]) -> Employee:
    """A working person with no emergency contact row: each one adds an «emergency» attention item."""
    values = {
        "family_name": f"Овог{index}",
        "given_name": f"Нэр{index}",
        "register_no": f"УБ8811{index:04d}",
        "birth_date": date(1990, 1, 1),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
        order_number=str(100 + index),
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def job() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def three_gaps(hr_user: User, job: dict[str, Any]) -> list[Employee]:
    return [_hire_without_contact(hr_user, i, job) for i in range(3)]


@pytest.fixture
def many_gaps(hr_user: User, job: dict[str, Any]) -> list[Employee]:
    return [_hire_without_contact(hr_user, i, job) for i in range(GAP_PAGE + 2)]


def _group(box: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(g for tier in ("urgent", "soon", "gaps") for g in box[tier] if g["kind"] == kind)


def _shown_keys(box: dict[str, Any]) -> set[str]:
    return {item["key"] for tier in ("urgent", "soon", "gaps") for g in box[tier] for item in g["shown"]}


def _toggle(client: Client, keys: list[str], action: str, token: str | None = None) -> Any:
    headers = {"HTTP_X_CSRFTOKEN": token} if token else {}
    return client.post(
        "/api/v1/attention/toggle",
        json.dumps({"keys": keys, "action": action}),
        content_type="application/json",
        **headers,
    )


def test_get_attention_returns_the_box(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/attention")

    assert response.status_code == 200
    body = response.json()
    assert {"tone", "urgent_count", "soon_count", "gap_count", "urgent", "soon", "gaps", "hidden"} <= body.keys()
    assert _group(body, "emergency")["count"] == 3


def test_dismiss_one_key_hides_it_and_drops_the_count(
    client: Client, hr_user: User, three_gaps: list[Employee]
) -> None:
    client.force_login(hr_user)
    before = client.get("/api/v1/attention").json()
    key = _group(before, "emergency")["keys"][0]

    response = _toggle(client, [key], "dismiss")

    assert response.status_code == 200
    box = response.json()["box"]
    assert key not in _shown_keys(box)
    assert key in {item["key"] for item in box["hidden"]}
    assert box["gap_count"] == before["gap_count"] - 1
    assert _group(box, "emergency")["count"] == 2


def test_restore_puts_the_key_back(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)
    key = _group(client.get("/api/v1/attention").json(), "emergency")["keys"][0]
    _toggle(client, [key], "dismiss")

    response = _toggle(client, [key], "restore")

    assert response.status_code == 200
    box = response.json()["box"]
    assert key in _shown_keys(box)
    assert box["hidden"] == []


def test_dismiss_all_in_a_group(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)
    keys = _group(client.get("/api/v1/attention").json(), "emergency")["keys"]

    box = _toggle(client, keys, "dismiss_all").json()["box"]

    assert not any(g["kind"] == "emergency" for tier in ("urgent", "soon", "gaps") for g in box[tier])
    assert {item["key"] for item in box["hidden"]} == set(keys)


def test_unknown_keys_give_404(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)

    assert _toggle(client, ["leave:999:x"], "dismiss").status_code == 404


def test_toggle_without_csrf_header_is_refused(hr_user: User, three_gaps: list[Employee]) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(hr_user)
    key = _group(client.get("/api/v1/attention").json(), "emergency")["keys"][0]

    assert _toggle(client, [key], "dismiss").status_code == 403


def test_toggle_with_csrf_header_is_accepted(hr_user: User, three_gaps: list[Employee]) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(hr_user)
    token = client.get("/api/v1/auth/csrf").json()["token"]
    key = _group(client.get("/api/v1/attention").json(), "emergency")["keys"][0]

    assert _toggle(client, [key], "dismiss", token).status_code == 200


@pytest.mark.parametrize("offset", ["-5", "abc"])
def test_more_junk_offset_is_treated_as_zero(
    client: Client, hr_user: User, many_gaps: list[Employee], offset: str
) -> None:
    client.force_login(hr_user)
    query = "/api/v1/attention/more?kind=emergency&urgency=2&all=1"

    junk = client.get(f"{query}&offset={offset}").json()
    zero = client.get(f"{query}&offset=0").json()

    assert junk == zero
    assert len(zero["items"]) == GAP_PAGE
    assert zero["more"] == 2 and zero["next_offset"] == GAP_PAGE


def test_more_missing_group_gives_404(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)

    assert client.get("/api/v1/attention/more?kind=nope&urgency=9").status_code == 404


def test_more_answers_carry_no_store(client: Client, hr_user: User, three_gaps: list[Employee]) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/attention/more?kind=emergency&urgency=2")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert set(response.json()) == {"dated", "items", "more", "next_offset"}


def test_more_anonymous_is_refused(client: Client) -> None:
    assert client.get("/api/v1/attention/more?kind=emergency&urgency=2").status_code == 401

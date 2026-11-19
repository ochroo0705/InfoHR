"""The event pop-up routes: POST .../events/{type}/form (the form), POST .../events/{type} (the save), and the cancel
pop-up GET/POST .../events/{event_id}/cancel. Business refusals answer 200 with ok false and write nothing; a missing
right is 403 (code "forbidden"), an unknown or foreign object is 404, no login is 401."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import Employee, Event, HrOrder, OrderState
from employees.services import events, history, macs_writes
from employees.tests.conftest import hire_values
from employees.tests.helpers import next_order_number, record_signed
from employees.views import ORDER_WARNING_KEY
from macs.models import Command

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
PAST = date(2026, 3, 1)
NOT_FOUND = "Хуудас олдсонгүй"


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("events_api_hr", roles.HR)


@pytest.fixture
def admin_user(db: None) -> User:
    return _user("events_api_admin", roles.ADMIN)


@pytest.fixture
def accountant(db: None) -> User:
    return _user("events_api_accountant", roles.ACCOUNTANT)


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _future_day() -> date:
    return timezone.localdate() + timedelta(days=30)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _form_url(employee: Employee, type: str = "transfer") -> str:
    return f"/api/v1/employees/{employee.pk}/events/{type}/form"


def _save_url(employee: Employee, type: str = "transfer") -> str:
    return f"/api/v1/employees/{employee.pk}/events/{type}"


def _cancel_url(employee: Employee, event: Event) -> str:
    return f"/api/v1/employees/{employee.pk}/events/{event.pk}/cancel"


def _transfer_values(**extra: str) -> dict[str, str]:
    """A transfer to a new department on a future date, with an order number."""
    new_dept = macs_writes.save_department("Санхүү 2")
    values = {
        "effective": _future_day().isoformat(),
        "department": str(new_dept.pk),
        "position": str(macs_writes.save_position("Нягтлан").pk),
        "manager": "",
        "reason": "",
        "note": "",
        "order-number": next_order_number(),
    }
    values.update(extra)
    return values


def _signed_transfer(employee: Employee, admin: User) -> Event:
    return record_signed(
        employee,
        type="transfer",
        effective=_future_day(),
        changes={"department": macs_writes.save_department("Санхүү 5")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )


# --- The form pop-up ---


def test_form_first_open_returns_fields_kinds_and_title(hired: Employee, hr_user: User) -> None:
    response = _post(_client(hr_user), _form_url(hired), {})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == events.PLACEMENT_LABEL
    assert [k["value"] for k in body["kinds"]] == ["transfer", "promotion", "demotion"]
    assert [k["selected"] for k in body["kinds"]] == [True, False, False]
    assert body["fields"][0]["name"] == "effective"
    assert body["fields"][0]["kind"] == "date"
    assert body["prev_effective"] == timezone.localdate().isoformat()
    assert body["reload"] is False
    assert body["summary"] == "" and body["when"] == ""
    assert body["errors"] == {} and body["form_errors"] == []


def test_form_unknown_type_404(hired: Employee, hr_user: User) -> None:
    response = _post(_client(hr_user), _form_url(hired, "nonsense"), {})
    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]


def test_form_without_right_403_forbidden(hired: Employee, accountant: User) -> None:
    response = _post(_client(accountant), _form_url(hired), {})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_form_outside_scope_404(hired: Employee, hr_user: User) -> None:
    AccessScope.objects.create(user=hr_user, limited=True)  # a limited scope with no branch, department or team
    response = _post(_client(hr_user), _form_url(hired), {})
    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]


def test_form_summary_for_valid_transfer_with_department_change(hired: Employee, hr_user: User) -> None:
    values = {"effective": _future_day().isoformat(), "department": str(macs_writes.save_department("Санхүү 2").pk)}

    # a pure summary refresh: the date did not change (prev_effective is the date the page holds)
    body = {"values": values, "prev_effective": _future_day().isoformat()}
    out = _post(_client(hr_user), _form_url(hired), body).json()

    assert out["summary"] != ""  # the change in one line, for the values typed so far
    assert "Санхүү 2" in out["summary"]


def test_form_date_change_gives_empty_summary_even_when_the_job_differs(
    hired: Employee, admin_user: User, hr_user: User
) -> None:
    """After a date change the boxes are refilled from the new date; the summary is only for a pure summary refresh,
    so a date change answers "" (Django cleared it the same way)."""
    record_signed(
        hired,
        type="transfer",
        effective=PAST,
        changes={"department": macs_writes.save_department("Санхүү 3")},
        salary=None,
        reason="",
        note="",
        by=admin_user,
    )
    values = {"effective": "2026-02-01", "department": str(macs_writes.save_department("Санхүү 2").pk)}

    out = _post(_client(hr_user), _form_url(hired), {"values": values, "prev_effective": "2026-03-01"}).json()

    assert out["summary"] == ""


def test_form_unreal_date_keeps_text_and_only_date_error(hired: Employee, hr_user: User) -> None:
    body = {"values": {"effective": "2026-13-45", "department": ""}, "prev_effective": "2026-02-01"}

    response = _post(_client(hr_user), _form_url(hired), body)

    assert response.status_code == 200, response.content
    out = response.json()
    effective = out["fields"][0]
    assert effective["name"] == "effective"
    assert effective["value"] == "2026-13-45"  # the typed text stays
    assert effective["kind"] == "text"  # the date box is a text box while the date is not real
    assert effective["errors"] != []
    assert list(out["errors"]) == ["effective"]  # only the date's own error
    assert out["summary"] == ""
    assert out["prev_effective"] == "2026-02-01"  # the last real date stays the hidden value


def test_form_order_block_present_only_for_types_that_ask(hired: Employee, hr_user: User) -> None:
    client = _client(hr_user)

    transfer = _post(client, _form_url(hired, "transfer"), {}).json()
    assert [f["name"] for f in transfer["order_fields"]] == [
        "order-number",
        "order-date",
        "order-summary",
        "order-issued_by",
    ]

    leave = _post(client, _form_url(hired, "leave_start"), {}).json()  # a leave never needs an order
    assert leave["order_fields"] == []


def test_form_returns_order_note_for_a_change_that_asks_for_an_order(hired: Employee, hr_user: User) -> None:
    body = _post(_client(hr_user), _form_url(hired, "transfer"), {}).json()

    assert body["order_note"] == "тушаал шаардлагатай өөрчлөлтөд дугаар заавал, огноо хоосон бол өөрчлөлтийн огноо"
    assert body["order_errors"] == []


def test_form_without_order_block_has_empty_order_note(hired: Employee, hr_user: User) -> None:
    body = _post(_client(hr_user), _form_url(hired, "leave_start"), {}).json()  # a leave never needs an order

    assert body["order_fields"] == []
    assert body["order_note"] == ""
    assert body["order_errors"] == []


def test_form_kind_change_keeps_typed_values_and_reloads(hired: Employee, hr_user: User) -> None:
    body = {
        "values": {"effective": _future_day().isoformat(), "reason": "жил", "note": "тэмдэглэл"},
        "prev_effective": _future_day().isoformat(),
    }

    out = _post(_client(hr_user), _form_url(hired, "promotion"), body).json()

    assert out["reload"] is True
    assert out["title"] == events.PLACEMENT_LABEL
    values = {f["name"]: f["value"] for f in out["fields"]}
    assert values["reason"] == "жил"
    assert values["note"] == "тэмдэглэл"


# --- The save ---


def test_submit_without_right_403_forbidden(hired: Employee, accountant: User) -> None:
    response = _post(_client(accountant), _save_url(hired), {"values": _transfer_values()})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_submit_ok_records_event_and_invalidation_data(hired: Employee, hr_user: User) -> None:
    before = Event.objects.filter(employee=hired).count()
    response = _post(_client(hr_user), _save_url(hired), {"values": _transfer_values()})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is True
    assert body["field_errors"] == {} and body["form_errors"] == [] and body["order_errors"] == []
    assert Event.objects.filter(employee=hired).count() == before + 1


def test_submit_refused_returns_ok_false_with_order_field_errors(hired: Employee, hr_user: User) -> None:
    before = Event.objects.count()
    orders_before = HrOrder.objects.filter(employee=hired).count()
    values = _transfer_values()
    values["order-number"] = ""  # the transfer needs an order number

    response = _post(_client(hr_user), _save_url(hired), {"values": values})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False
    assert "order-number" in body["field_errors"]
    assert body["summary"] != ""  # the summary of the typed values, as the page recomputes it
    assert body["prev_effective"] == _future_day().isoformat()
    assert Event.objects.count() == before  # nothing written
    assert HrOrder.objects.filter(employee=hired).count() == orders_before  # no order either


def test_refused_submit_puts_order_level_errors_in_order_errors_not_form_errors(
    hired: Employee, hr_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = "Тушаалын ерөнхий алдаа."

    def refuse(*args: object, **kwargs: object) -> None:
        raise events.EventError({"order___all__": message})  # lands on the order form's non-field errors

    monkeypatch.setattr(events, "record", refuse)

    body = _post(_client(hr_user), _save_url(hired), {"values": _transfer_values()}).json()

    assert body["ok"] is False
    assert body["order_errors"] == [message]
    assert body["form_errors"] == []


def test_submit_sets_order_warning_in_session_on_macs_clash(hired: Employee, hr_user: User) -> None:
    number = "А/99"
    Command.objects.create(employee_id=hired.pk, number=number, date=_future_day(), order_type=1)
    client = _client(hr_user)
    values = _transfer_values(**{"order-number": number})

    response = _post(client, _save_url(hired), {"values": values})

    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True
    assert "MACS-д" in client.session[ORDER_WARNING_KEY]
    assert HrOrder.objects.filter(event__employee=hired, number=number).exists()


# --- The cancel pop-up ---


def test_cancel_get_returns_title_hint_and_reason_field(hired: Employee, admin_user: User) -> None:
    event = _signed_transfer(hired, admin_user)

    response = _client(admin_user).get(_cancel_url(hired, event))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})"
    assert body["hint"] != ""
    assert body["submit_label"] == "Цуцлах"
    assert body["multipart"] is False
    assert [f["name"] for f in body["fields"]][0] == "reason"
    assert "cancel_order_no" in [f["name"] for f in body["fields"]]  # the order is signed


def test_cancel_post_ok(hired: Employee, admin_user: User) -> None:
    event = _signed_transfer(hired, admin_user)
    values = {"reason": "алдаа", "cancel_order_no": "А/60"}

    response = _post(_client(admin_user), _cancel_url(hired, event), {"values": values})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    event.refresh_from_db()
    assert event.cancelled_at is not None
    assert HrOrder.objects.get(event=event).state == OrderState.CANCELLED


def test_cancel_post_unknown_event_404(hired: Employee, admin_user: User) -> None:
    url = f"/api/v1/employees/{hired.pk}/events/999999/cancel"
    response = _post(_client(admin_user), url, {"values": {"reason": "алдаа"}})
    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]


def test_cancel_non_cancellable_404(hired: Employee, admin_user: User) -> None:
    applied = record_signed(
        hired,
        type="transfer",
        effective=PAST,
        changes={"department": macs_writes.save_department("Санхүү 3")},
        salary=None,
        reason="",
        note="",
        by=admin_user,
    )
    response = _client(admin_user).get(_cancel_url(hired, applied))
    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]


def test_cancel_without_right_403(hired: Employee, admin_user: User, accountant: User) -> None:
    event = _signed_transfer(hired, admin_user)
    response = _client(accountant).get(_cancel_url(hired, event))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_cancel_signed_order_requires_cancel_order_no(hired: Employee, admin_user: User) -> None:
    event = _signed_transfer(hired, admin_user)

    response = _post(_client(admin_user), _cancel_url(hired, event), {"values": {"reason": "алдаа"}})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False
    assert "cancel_order_no" in body["field_errors"]
    event.refresh_from_db()
    assert event.cancelled_at is None


def test_anonymous_event_routes_answer_401(hired: Employee, admin_user: User) -> None:
    """The four event routes, with no login: django_auth refuses each before the handler runs."""
    event = _signed_transfer(hired, admin_user)
    anonymous = Client()  # a fresh client, never logged in
    responses = [
        _post(anonymous, _form_url(hired), {}),
        _post(anonymous, _save_url(hired), {"values": _transfer_values()}),
        anonymous.get(_cancel_url(hired, event)),
        _post(anonymous, _cancel_url(hired, event), {"values": {"reason": "алдаа"}}),
    ]
    not_logged_in = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
    for response in responses:
        assert response.status_code == 401
        assert response.json() == not_logged_in
    event.refresh_from_db()
    assert event.cancelled_at is None  # nothing cancelled

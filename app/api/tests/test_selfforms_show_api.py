"""GET /api/v1/selfforms/{pk} and POST /api/v1/selfforms/{pk}/extend and /revoke: the link page as the React page reads
it, and the two actions on it. The states, dates and the decision come from employees.services.selfform_page and
employees.selfform.service; these tests pin the API's answer and the right (only holders of macs.manage_employees)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import CompanySettings, Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import Branch

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/selfforms"
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"], "code": "not_found"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
EXTENDED = "Холбоосын хугацааг сунгалаа."
REVOKED = "Холбоосыг цуцаллаа. Ажилтан энэ холбоосоор бөглөх боломжгүй болсон."
BAD_HOURS = "Хугацааг цагаар бүхэл тоогоор бичнэ үү."
NOT_OPEN_TO_EXTEND = "Зөвхөн нээлттэй холбоосын хугацааг сунгана."
PURGED = "Хариулт устгагдсан тул энэ холбоосыг сунгах, дахин нээх боломжгүй. Шинэ урилга үүсгэнэ үү."
NOT_REVOCABLE = "Энэ маягтын холбоосыг цуцлах боломжгүй."


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _invitation(by: User, branch: Branch | None = None, **fields: Any) -> SelfFormInvitation:
    inv = service.create_invitation(label="Бат Бат", branch=branch, hours=72, by=by)
    if fields:
        SelfFormInvitation.objects.filter(pk=inv.pk).update(**fields)
    return SelfFormInvitation.objects.get(pk=inv.pk)


def _show(client: Client, pk: int) -> Any:
    return client.get(f"{URL}/{pk}")


def _post(client: Client, pk: int, action: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(
        f"{URL}/{pk}/{action}",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


@pytest.fixture
def hr() -> User:
    return _user("selfform_show_hr", roles.HR)


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def other_branch() -> Branch:
    return Branch.objects.create(name="Баруун салбар")


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def test_show_open_offers_extend_and_revoke(hr: User, branch: Branch) -> None:
    inv = _invitation(hr, branch=branch)

    response = _show(_client(hr), inv.pk)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == inv.pk
    assert body["label"] == "Бат Бат"
    assert body["state"] == "Нээлттэй"
    assert body["state_key"] == "open"
    assert body["badge"]
    assert body["branch"] == branch.name
    assert body["created_label"] == timezone.localtime(inv.created_at).strftime("%Y-%m-%d %H:%M")
    assert body["when_title"] == "Дуусах"
    assert body["when_label"] == timezone.localtime(inv.expires_at).strftime("%Y-%m-%d %H:%M")
    assert body["purged"] is False
    assert inv.token in body["link"]
    assert body["can_extend"] is True
    assert body["can_revoke"] is True
    assert body["default_hours"] == CompanySettings.get().selfform_default_hours
    assert body["hire_path"] is None
    assert body["decision"] is None


def test_show_expired_offers_extend_only(hr: User) -> None:
    inv = _invitation(hr, expires_at=timezone.now() - timedelta(hours=1))

    body = _show(_client(hr), inv.pk).json()

    assert body["state_key"] == "expired"
    assert body["state"] == "Хугацаа дууссан"
    assert body["when_title"] == "Дуусах"
    assert body["can_extend"] is True
    assert body["can_revoke"] is False


def test_show_revoked_offers_nothing_and_has_decision(hr: User) -> None:
    inv = _invitation(hr)
    service.revoke(inv, by=hr)

    body = _show(_client(hr), inv.pk).json()

    assert body["state_key"] == "revoked"
    assert body["state"] == "Цуцалсан"
    assert body["when_title"] == ""
    assert body["when_label"] == ""
    assert body["can_extend"] is False
    assert body["can_revoke"] is False
    decision = body["decision"]
    assert decision is not None
    assert decision["reviewed_by"] == str(hr)
    assert decision["reviewed_label"] != ""
    assert decision["reject_reason"] == ""
    assert decision["employee_path"] is None


def test_show_purged_note_and_no_actions(hr: User) -> None:
    inv = _invitation(hr, purged_at=timezone.now())

    body = _show(_client(hr), inv.pk).json()

    assert body["purged"] is True
    assert body["when_title"] == "Дуусах"  # the expiry stays on the page, as the Django template shows it
    assert body["can_extend"] is False
    assert body["can_revoke"] is False


def test_show_submitted_has_hire_path(hr: User) -> None:
    inv = _invitation(hr, status=SelfFormStatus.SUBMITTED, submitted_at=timezone.now())

    body = _show(_client(hr), inv.pk).json()

    assert body["state_key"] == "submitted"
    assert body["when_title"] == "Илгээсэн"
    assert body["when_label"] == timezone.localtime(inv.submitted_at).strftime("%Y-%m-%d %H:%M")
    assert body["hire_path"] == f"{reverse('employees:add')}?submission={inv.pk}"
    assert body["can_extend"] is False
    assert body["can_revoke"] is False
    assert body["decision"] is None


def test_show_confirmed_links_employee(hr: User, job_values: dict[str, Any]) -> None:
    employee: Employee = history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr,
        order_number="1",
        order_date=date(2026, 1, 5),
    )
    inv = _invitation(
        hr,
        status=SelfFormStatus.CONFIRMED,
        employee=employee,
        reviewed_by=hr,
        reviewed_at=timezone.now(),
    )

    body = _show(_client(hr), inv.pk).json()

    assert body["state_key"] == "confirmed"
    assert body["decision"]["employee_path"] == reverse("employees:detail", args=[employee.pk])


def test_show_sends_no_store_header(hr: User) -> None:
    inv = _invitation(hr)

    response = _show(_client(hr), inv.pk)

    assert response["Cache-Control"] == "no-store"


def test_show_out_of_scope_404(hr: User, branch: Branch, other_branch: Branch) -> None:
    limited = _user("selfform_show_limited", roles.HR)
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[branch.pk])
    limited = User.objects.get(pk=limited.pk)
    foreign = _invitation(hr, branch=other_branch)

    response = _show(_client(limited), foreign.pk)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _show(_client(hr), 999_999).json() == NOT_FOUND


def test_show_refused_without_manage_right() -> None:
    creator = _user("selfform_show_creator", roles.HR)
    inv = _invitation(creator)
    employee = _user("selfform_show_employee", roles.EMPLOYEE)

    response = _show(_client(employee), inv.pk)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_extend_blank_uses_default_hours(hr: User) -> None:
    inv = _invitation(hr)
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at
    default = CompanySettings.get().selfform_default_hours

    response = _post(_client(hr), inv.pk, "extend", {"hours": ""})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["notice"] == {"text": EXTENDED, "tone": "success"}
    after = SelfFormInvitation.objects.get(pk=inv.pk).expires_at
    assert after - before == timedelta(hours=default)
    assert body["show"]["when_label"] == timezone.localtime(after).strftime("%Y-%m-%d %H:%M")
    assert body["show"]["can_extend"] is True


def test_extend_typed_hours_adds_them(hr: User) -> None:
    inv = _invitation(hr)
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    body = _post(_client(hr), inv.pk, "extend", {"hours": "24"}).json()

    assert body["ok"] is True
    assert SelfFormInvitation.objects.get(pk=inv.pk).expires_at - before == timedelta(hours=24)


def test_extend_bad_hours_refused_with_service_text(hr: User) -> None:
    inv = _invitation(hr)
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    response = _post(_client(hr), inv.pk, "extend", {"hours": "abc"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["notice"] == {"text": BAD_HOURS, "tone": "error"}
    assert body["show"]["state_key"] == "open"
    assert SelfFormInvitation.objects.get(pk=inv.pk).expires_at == before


def test_extend_on_revoked_refused_not_500(hr: User) -> None:
    inv = _invitation(hr)
    service.revoke(inv, by=hr)

    response = _post(_client(hr), inv.pk, "extend", {"hours": "24"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["notice"] == {"text": NOT_OPEN_TO_EXTEND, "tone": "error"}
    assert body["show"]["state_key"] == "revoked"


def test_extend_out_of_scope_404(hr: User, branch: Branch, other_branch: Branch) -> None:
    limited = _user("selfform_extend_limited", roles.HR)
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[branch.pk])
    limited = User.objects.get(pk=limited.pk)
    foreign = _invitation(hr, branch=other_branch)

    response = _post(_client(limited), foreign.pk, "extend", {"hours": "24"})

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_revoke_open_then_state_is_revoked(hr: User) -> None:
    inv = _invitation(hr)

    response = _post(_client(hr), inv.pk, "revoke")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["notice"] == {"text": REVOKED, "tone": "success"}
    assert body["show"]["state_key"] == "revoked"
    assert body["show"]["can_revoke"] is False
    assert body["show"]["decision"]["reviewed_by"] == str(hr)
    assert SelfFormInvitation.objects.get(pk=inv.pk).status == SelfFormStatus.REVOKED


def test_revoke_twice_second_is_refused_with_text(hr: User) -> None:
    inv = _invitation(hr)
    client = _client(hr)
    assert _post(client, inv.pk, "revoke").json()["ok"] is True

    response = _post(client, inv.pk, "revoke")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["notice"] == {"text": NOT_REVOCABLE, "tone": "error"}
    assert body["show"]["state_key"] == "revoked"


def test_revoke_refused_without_manage_right() -> None:
    creator = _user("selfform_revoke_creator", roles.HR)
    inv = _invitation(creator)
    employee = _user("selfform_revoke_employee", roles.EMPLOYEE)

    response = _post(_client(employee), inv.pk, "revoke")

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert SelfFormInvitation.objects.get(pk=inv.pk).status == SelfFormStatus.OPEN


def test_show_extend_and_revoke_need_a_login(hr: User) -> None:
    inv = _invitation(hr)
    anonymous = Client()

    assert _show(anonymous, inv.pk).status_code == 401
    assert _post(anonymous, inv.pk, "extend", {"hours": "24"}).status_code == 401
    assert _post(anonymous, inv.pk, "revoke").status_code == 401
    assert SelfFormInvitation.objects.get(pk=inv.pk).status == SelfFormStatus.OPEN


def test_extend_sends_no_store_header(hr: User) -> None:
    inv = _invitation(hr)

    response = _post(_client(hr), inv.pk, "extend", {"hours": "24"})

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


def test_revoke_sends_no_store_header(hr: User) -> None:
    inv = _invitation(hr)

    response = _post(_client(hr), inv.pk, "revoke")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("raw", ["1x", "1234567"])
def test_extend_malformed_hours_refused_with_service_text(hr: User, raw: str) -> None:
    inv = _invitation(hr)
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    body = _post(_client(hr), inv.pk, "extend", {"hours": raw}).json()

    assert body["ok"] is False
    assert body["notice"] == {"text": BAD_HOURS, "tone": "error"}
    assert SelfFormInvitation.objects.get(pk=inv.pk).expires_at == before


def test_extend_on_purged_refused_with_purged_text(hr: User) -> None:
    inv = _invitation(hr, purged_at=timezone.now())
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    body = _post(_client(hr), inv.pk, "extend", {"hours": "24"}).json()

    assert body["ok"] is False
    assert body["notice"] == {"text": PURGED, "tone": "error"}
    assert body["show"]["purged"] is True
    assert SelfFormInvitation.objects.get(pk=inv.pk).expires_at == before


def test_revoke_on_purged_follows_the_service(hr: User) -> None:
    # The service checks only the status for revoke (open or submitted), not purged_at, so a purged link that is
    # still open can be revoked, as it can on the Django page. Pinned here so a change to the rule shows up.
    inv = _invitation(hr, purged_at=timezone.now())

    body = _post(_client(hr), inv.pk, "revoke").json()

    assert body["ok"] is True
    assert body["notice"] == {"text": REVOKED, "tone": "success"}
    assert body["show"]["state_key"] == "revoked"
    assert body["show"]["purged"] is True
    assert body["show"]["can_revoke"] is False

"""GET and POST /api/v1/selfforms: the self-form list screen and its create form.

The rows come from employees.services.selfform_page and the create from employees.selfform.service; these tests pin the
API's answer (rows, waiting count, form description, ok, field_errors, form_errors, notice) and the right (only holders
of macs.manage_employees)."""

import json
from datetime import timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.selfform.forms import SelfFormInvitationForm
from macs.models import Branch

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/selfforms"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOTICE = "Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү."


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


def _limited(name: str, branch: Branch) -> User:
    user = _user(name, roles.HR)
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk])
    return User.objects.get(pk=user.pk)


@pytest.fixture
def hr() -> User:
    return _user("selfform_list_hr", roles.HR)


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def other_branch() -> Branch:
    return Branch.objects.create(name="Баруун салбар")


def test_list_needs_login_and_manage_right(hr: User) -> None:
    anonymous = Client().get(URL)
    assert anonymous.status_code == 401
    assert anonymous.json() == NOT_LOGGED_IN

    employee = _user("selfform_list_employee", roles.EMPLOYEE)
    refused = _client(employee).get(URL)
    assert refused.status_code == 403
    assert refused.json() == FORBIDDEN

    assert _client(hr).get(URL).status_code == 200


def test_list_rows_state_badge_and_paths(hr: User, branch: Branch) -> None:
    now = timezone.now()
    open_inv = _invitation(hr, branch=branch, expires_at=now + timedelta(hours=5))
    expired = _invitation(hr, expires_at=now - timedelta(minutes=1))
    submitted = _invitation(hr, branch=branch, status=SelfFormStatus.SUBMITTED, expires_at=now + timedelta(hours=5))
    submitted_at = now.replace(microsecond=0) - timedelta(days=1)
    SelfFormInvitation.objects.filter(pk=submitted.pk).update(submitted_at=submitted_at)

    body = _client(hr).get(URL).json()
    rows = {row["id"]: row for row in body["rows"]}
    assert set(rows) == {open_inv.pk, expired.pk, submitted.pk}

    open_row = rows[open_inv.pk]
    assert open_row["state"] == "Нээлттэй"
    assert open_row["branch"] == "Төв салбар"
    assert open_row["show_path"] == reverse("employees:selfform_show", args=[open_inv.pk])
    assert open_row["hire_path"] == ""
    assert open_row["when_kind"] == "expires"
    assert open_row["when_label"] == timezone.localtime(open_inv.expires_at).strftime("%Y-%m-%d %H:%M")

    expired_row = rows[expired.pk]
    assert expired_row["state"] == "Хугацаа дууссан"
    assert expired_row["branch"] == "—"

    submitted_row = rows[submitted.pk]
    assert submitted_row["state"] == "Хянах хүлээж байна"
    assert submitted_row["hire_path"] == f"{reverse('employees:add')}?submission={submitted.pk}"
    assert submitted_row["when_kind"] == "sent"
    assert submitted_row["when_label"] == timezone.localtime(submitted_at).strftime("%Y-%m-%d %H:%M")


def test_list_scoped_to_visible_invitations(hr: User, branch: Branch, other_branch: Branch) -> None:
    visible = _invitation(hr, branch=branch)
    hidden = _invitation(hr, branch=other_branch)
    limited = _limited("selfform_list_limited", branch)

    body = _client(limited).get(URL).json()

    assert [row["id"] for row in body["rows"]] == [visible.pk]
    assert hidden.pk not in {row["id"] for row in body["rows"]}


def test_waiting_count_matches_service(hr: User, branch: Branch) -> None:
    _invitation(hr, branch=branch, status=SelfFormStatus.SUBMITTED)
    _invitation(hr, branch=branch, status=SelfFormStatus.SUBMITTED)
    _invitation(hr, branch=branch)

    body = _client(hr).get(URL).json()

    assert body["waiting"] == service.waiting_count(hr) == 2


def test_list_describes_the_create_form(hr: User, branch: Branch, other_branch: Branch) -> None:
    body = _client(hr).get(URL).json()

    form = body["form"]
    assert {item["label"] for item in form["branches"]} == {"Төв салбар", "Баруун салбар"}
    assert {item["value"] for item in form["branches"]} == {branch.pk, other_branch.pk}
    assert form["branch_required"] is False
    assert form["default_hours"] == 72
    assert form["max_hours"] == 8760
    assert form["labels"] == {
        "label": "Нэр (зөвхөн HR-д харагдана)",
        "branch": "Салбар",
        "hours": "Хүчинтэй хугацаа (цаг)",
    }
    assert form["help"]["label"] == "Ажилтны нэр эсвэл ямар ажлын байранд авахыг бичнэ. Ажилтанд харагдахгүй."
    assert form["help"]["hours"] == "Хоосон бол өгөгдмөл 72 цаг. Хамгийн ихдээ 8760 цаг."
    assert body["intro"].startswith("Шинэ ажилтанд холбоос үүсгэж илгээнэ.")


def test_create_returns_show_path_and_notice(hr: User, branch: Branch) -> None:
    response = _client(hr).post(
        URL,
        data=json.dumps({"label": "Сараа Сараа", "branch": branch.pk, "hours": 48}),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["field_errors"] == {} and body["form_errors"] == []
    assert body["notice"] == {"text": NOTICE}
    invitation = SelfFormInvitation.objects.get(pk=body["id"])
    assert invitation.label == "Сараа Сараа"
    assert invitation.branch_id == branch.pk
    assert body["show_path"] == reverse("employees:selfform_show", args=[invitation.pk])


def test_create_blank_label_reports_field_error(hr: User) -> None:
    response = _client(hr).post(URL, data=json.dumps({}), content_type="application/json")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["id"] is None and body["show_path"] == "" and body["notice"] is None
    required_text = [str(message) for message in SelfFormInvitationForm({}, user=hr).errors["label"]]
    assert required_text and required_text[0]
    assert body["field_errors"]["label"] == required_text
    assert SelfFormInvitation.objects.count() == 0


def test_create_null_label_reports_field_error(hr: User) -> None:
    response = _client(hr).post(URL, data=json.dumps({"label": None}), content_type="application/json")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["field_errors"]["label"]
    assert SelfFormInvitation.objects.count() == 0


def test_create_other_branch_refused_for_scoped_user(branch: Branch, other_branch: Branch) -> None:
    limited = _limited("selfform_create_other", branch)

    response = _client(limited).post(
        URL,
        data=json.dumps({"label": "Бат", "branch": other_branch.pk}),
        content_type="application/json",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["field_errors"]["branch"]
    assert SelfFormInvitation.objects.count() == 0


def test_create_branch_required_for_scoped_user(branch: Branch) -> None:
    limited = _limited("selfform_create_limited", branch)

    response = _client(limited).post(
        URL,
        data=json.dumps({"label": "Бат"}),
        content_type="application/json",
    )

    body = response.json()
    assert body["ok"] is False
    assert "branch" in body["field_errors"]
    assert SelfFormInvitation.objects.count() == 0


def test_create_hours_out_of_range_refused(hr: User) -> None:
    client = _client(hr)
    for hours in (0, 8761):
        response = client.post(
            URL,
            data=json.dumps({"label": "Бат", "hours": hours}),
            content_type="application/json",
        )
        body = response.json()
        assert body["ok"] is False
        assert "hours" in body["field_errors"]
    assert SelfFormInvitation.objects.count() == 0


def test_create_service_error_goes_to_form_errors(hr: User, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**_: Any) -> None:
        raise service.SelfFormError("Энэ салбарт маягт илгээх эрх байхгүй.")

    monkeypatch.setattr(service, "create_invitation", refuse)

    response = _client(hr).post(URL, data=json.dumps({"label": "Бат"}), content_type="application/json")

    body = response.json()
    assert response.status_code == 200
    assert body == {
        "ok": False,
        "id": None,
        "show_path": "",
        "field_errors": {},
        "form_errors": ["Энэ салбарт маягт илгээх эрх байхгүй."],
        "notice": None,
    }


def test_create_refused_without_manage_right() -> None:
    employee = _user("selfform_create_employee", roles.EMPLOYEE)

    response = _client(employee).post(URL, data=json.dumps({"label": "Бат"}), content_type="application/json")

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert SelfFormInvitation.objects.count() == 0

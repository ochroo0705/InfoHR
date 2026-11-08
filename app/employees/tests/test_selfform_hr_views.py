"""The HR screens of the employee self-form: the list, the create form, the link page, revoke and extend."""

from datetime import timedelta
from typing import Any

import pytest
from accounts.models import AccessScope, User
from accounts.nav import top_nav
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone
from macs.models import Branch

from employees.models import CompanySettings, Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.service import create_invitation, mark_confirmed, reject, submit, visible_invitations

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
LIST_URL = "/employees/self-forms/"
NEW_URL = "/employees/self-forms/new/"
NO_REQUESTS: dict[str, Any] = {"show": False, "count": 0}


def _login(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _user_in(role: str, name: str, *, limit: list[int] | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    if limit is not None:
        AccessScope.objects.create(user=user, limited=True, branch_ids=limit)
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _invitation_for_user(user: User, label: str = "Бат Бат", branch: Branch | None = None) -> SelfFormInvitation:
    return create_invitation(label=label, branch=branch, hours=24, by=user)


def _employees_nav(user: User) -> dict[str, int]:
    """The items of the staff menu with their badge counts, as the top bar shows them."""
    request = RequestFactory().get(LIST_URL)
    request.user = user
    request.resolver_match = resolve(LIST_URL)
    groups = {g.key: g for g in top_nav(request, False, NO_REQUESTS)}
    return {item.label: item.badge for item in groups["employees"].items}


def test_list_requires_manage_permission(client: Client) -> None:
    _login(client, "Accountant", "hr_viewer")  # sees employees and salary, may not manage them
    assert client.get(LIST_URL).status_code == 403


def test_anonymous_list_redirects_to_login(client: Client) -> None:
    response = client.get(LIST_URL)
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_create_shows_link_and_qr_svg(client: Client) -> None:
    pytest.importorskip("segno")
    hr = _login(client, "HR", "hr_create")
    response = client.post(NEW_URL, {"label": "Бат Бат", "branch": "", "hours": ""}, follow=True)
    inv = SelfFormInvitation.objects.get(created_by=hr)
    content = response.content.decode()
    assert f"/apply/{inv.token}/" in content
    assert "<svg" in content


def test_link_uses_public_base_url_setting(client: Client) -> None:
    settings_row = CompanySettings.get()
    settings_row.selfform_base_url = "https://hr.example.mn"
    settings_row.save()
    _login(client, "HR", "hr_base")
    client.post(NEW_URL, {"label": "Бат Бат", "branch": "", "hours": ""})
    inv = SelfFormInvitation.objects.get()
    response = client.get(reverse("employees:selfform_show", args=[inv.pk]))
    assert f"https://hr.example.mn/apply/{inv.token}/" in response.content.decode()


def test_create_rejects_blank_label_and_creates_nothing(client: Client) -> None:
    _login(client, "HR", "hr_blank")
    response = client.post(NEW_URL, {"label": "   ", "branch": "", "hours": ""})
    assert response.status_code == 200
    assert not SelfFormInvitation.objects.exists()


def test_new_is_post_only(client: Client) -> None:
    _login(client, "HR", "hr_new_get")
    assert client.get(NEW_URL).status_code == 405


def test_revoke_and_extend_post_only(client: Client) -> None:
    hr = _login(client, "HR", "hr_post_only")
    inv = _invitation_for_user(hr)
    assert client.get(reverse("employees:selfform_revoke", args=[inv.pk])).status_code == 405
    assert client.get(reverse("employees:selfform_extend", args=[inv.pk])).status_code == 405
    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.OPEN


def test_extend_then_revoke_change_the_invitation(client: Client) -> None:
    hr = _login(client, "HR", "hr_revoke")
    inv = _invitation_for_user(hr)
    client.post(reverse("employees:selfform_extend", args=[inv.pk]), {"hours": "48"})
    inv.refresh_from_db()
    assert inv.expires_at > timezone.now() + timedelta(hours=40)
    client.post(reverse("employees:selfform_revoke", args=[inv.pk]))
    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.REVOKED


def test_branch_limited_user_cannot_revoke_other_branch_invitation(client: Client) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    owner = _user_in("HR", "hr_owner_south")
    inv = _invitation_for_user(owner, branch=south)
    limited = _user_in("HR", "hr_north", limit=[north.pk])
    client.force_login(limited)
    assert client.get(reverse("employees:selfform_show", args=[inv.pk])).status_code == 404
    assert client.post(reverse("employees:selfform_revoke", args=[inv.pk])).status_code == 404
    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.OPEN


def test_branch_limited_user_must_pick_a_listed_branch(client: Client) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    limited = _user_in("HR", "hr_pick", limit=[north.pk])
    client.force_login(limited)
    response = client.post(NEW_URL, {"label": "Бат", "branch": str(south.pk), "hours": ""})
    assert response.status_code == 200  # the form is shown again with the error
    assert not SelfFormInvitation.objects.exists()


def test_waiting_count_in_nav_for_hr_only() -> None:
    hr = _user_in("HR", "hr_nav")
    submitted = _invitation_for_user(hr)
    submitted.status = SelfFormStatus.SUBMITTED
    submitted.save(update_fields=["status"])
    assert _employees_nav(hr)["Өөрөө бөглөх анкет"] == 1
    accountant = _user_in("Accountant", "acc_nav")
    assert "Өөрөө бөглөх анкет" not in _employees_nav(accountant)


def test_list_escapes_the_label(client: Client) -> None:
    _login(client, "HR", "hr_escape")
    client.post(NEW_URL, {"label": "<script>alert(1)</script>", "branch": "", "hours": ""})
    content = client.get(LIST_URL).content.decode()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "<script>alert(1)</script>" not in content


def test_submitted_row_links_to_the_hire_page(client: Client) -> None:
    hr = _login(client, "HR", "hr_submitted")
    inv = _invitation_for_user(hr)
    inv.status = SelfFormStatus.SUBMITTED
    inv.save(update_fields=["status"])
    content = client.get(LIST_URL).content.decode()
    assert "Нээх" in content
    assert f"{reverse('employees:add')}?submission={inv.pk}" in content


def test_expired_invitation_shows_as_expired(client: Client) -> None:
    hr = _login(client, "HR", "hr_expired")
    inv = _invitation_for_user(hr)
    SelfFormInvitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() - timedelta(hours=1))
    assert "Хугацаа дууссан" in client.get(LIST_URL).content.decode()


def test_list_query_leaves_answers_and_photo_out() -> None:
    hr = _user_in("HR", "hr_defer")
    _invitation_for_user(hr)
    row = visible_invitations(hr).first()
    assert row is not None
    assert {"answers", "photo_b64"} <= row.get_deferred_fields()


def test_show_page_for_an_open_invitation_has_revoke_and_extend(client: Client) -> None:
    hr = _login(client, "HR", "hr_show")
    inv = _invitation_for_user(hr)
    content = client.get(reverse("employees:selfform_show", args=[inv.pk])).content.decode()
    assert reverse("employees:selfform_revoke", args=[inv.pk]) in content
    assert reverse("employees:selfform_extend", args=[inv.pk]) in content


def _submitted_form(user: User, label: str = "Сараа") -> SelfFormInvitation:
    inv = _invitation_for_user(user, label=label)
    answers = {
        "person": {
            "family_name": "Батын",
            "given_name": "Сараа",
            "register_no": "УБ99112233",
            "birth_date": "1999-11-22",
            "gender": "F",
            "work_phone": "99112233",
        },
        "education": [],
        "family": [],
        "contact": {},
    }
    submit(inv, answers, photo_b64="", agreed_correct=True, consent=True)
    return inv


def test_list_shows_the_waiting_count_above_the_table(client: Client) -> None:
    hr = _login(client, "HR", "hr_waiting")
    _submitted_form(hr, "Нэг")
    _submitted_form(hr, "Хоёр")
    _invitation_for_user(hr, label="Нээлттэй")  # open: not waiting for review

    content = client.get(LIST_URL).content.decode()

    assert "Хянах хүлээж буй: 2" in content
    assert content.index("Хянах хүлээж буй: 2") < content.index("<table")


def test_show_page_of_a_confirmed_invitation_links_to_the_employee(client: Client, hired: Employee) -> None:
    hr = _login(client, "HR", "hr_confirmed")
    inv = _submitted_form(hr)
    mark_confirmed(inv.pk, hired, hr)

    content = client.get(reverse("employees:selfform_show", args=[inv.pk])).content.decode()

    assert reverse("employees:detail", args=[hired.pk]) in content


def test_show_page_of_a_rejected_invitation_shows_the_reason_and_who_decided(client: Client) -> None:
    hr = _login(client, "HR", "hr_rejects")
    inv = _submitted_form(hr)
    reject(inv, reason="Регистрийн дугаар буруу", by=hr)

    content = client.get(reverse("employees:selfform_show", args=[inv.pk])).content.decode()

    assert "Регистрийн дугаар буруу" in content
    assert hr.username in content


def test_error_message_has_error_styling_and_success_has_the_green_one(client: Client) -> None:
    hr = _login(client, "HR", "hr_messages")
    inv = _invitation_for_user(hr)
    created = client.post(reverse("employees:selfform_revoke", args=[inv.pk]), follow=True)  # success
    success = "Холбоосыг цуцаллаа."
    assert f'bg-emerald-50 text-emerald-800">{success}' in created.content.decode()

    again = client.post(reverse("employees:selfform_revoke", args=[inv.pk]), follow=True)  # refused: already revoked
    body = again.content.decode()
    assert "Энэ маягтын холбоосыг цуцлах боломжгүй." in body
    assert 'bg-red-50 text-red-700">Энэ маягтын холбоосыг цуцлах боломжгүй.' in body


def test_invitation_for_leaves_the_answers_and_photo_out(client: Client) -> None:
    from employees.selfform.service import invitation_for

    hr = _login(client, "HR", "hr_deferred")
    inv = _submitted_form(hr)
    found = invitation_for(hr, inv.pk)

    assert {"answers", "photo_b64"} <= found.get_deferred_fields()

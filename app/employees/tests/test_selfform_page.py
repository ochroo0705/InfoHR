"""The request-free self-form screen service (employees.services.selfform_page), frontend-split step 3e Task 6."""

import sys
from datetime import timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from macs.models import Branch

from employees.models import SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.services import selfform_page

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor() -> User:
    user = User.objects.create_user("hr_page_actor", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=roles.HR))
    return User.objects.get(pk=user.pk)


def _invitation(actor: User, branch: Branch | None = None, **fields: Any) -> SelfFormInvitation:
    inv = service.create_invitation(label="Бат Бат", branch=branch, hours=72, by=actor)
    if fields:
        SelfFormInvitation.objects.filter(pk=inv.pk).update(**fields)
    return SelfFormInvitation.objects.get(pk=inv.pk)


def _ahead(hours: int) -> Any:
    return timezone.now() + timedelta(hours=hours)


def test_state_key_covers_every_status_and_expiry(actor: User) -> None:
    now = timezone.now()
    open_inv = _invitation(actor, expires_at=_ahead(2))
    expired = _invitation(actor, expires_at=now - timedelta(minutes=1))
    assert selfform_page.state_key(open_inv, now) == "open"
    assert selfform_page.state_key(expired, now) == "expired"
    for status in (SelfFormStatus.SUBMITTED, SelfFormStatus.CONFIRMED, SelfFormStatus.REJECTED, SelfFormStatus.REVOKED):
        inv = _invitation(actor, status=status, expires_at=_ahead(2))
        assert selfform_page.state_key(inv, now) == str(status)
    assert set(selfform_page.BADGES) == {"open", "expired", "submitted", "confirmed", "rejected", "revoked"}


def test_list_rows_newest_first_and_scoped(actor: User) -> None:
    branch_a = Branch.objects.create(name="Салбар А")
    branch_b = Branch.objects.create(name="Салбар Б")
    older = _invitation(actor, branch=branch_a, expires_at=_ahead(2))
    newer = _invitation(actor, branch=branch_a, expires_at=_ahead(2))
    SelfFormInvitation.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
    _invitation(actor, branch=branch_b, expires_at=_ahead(2))  # outside the limited user's scope

    limited = User.objects.create_user("hr_page_limited", password="x-long-pass-123")  # noqa: S106
    limited.groups.add(Group.objects.get(name=roles.HR))
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[branch_a.pk])
    limited = User.objects.get(pk=limited.pk)

    rows = selfform_page.list_rows(limited, timezone.now())
    assert [row.invitation.pk for row in rows] == [newer.pk, older.pk]
    assert all(row.invitation.branch_id == branch_a.pk for row in rows)
    assert rows[0].show_path == reverse("employees:selfform_show", args=[newer.pk])


def test_list_row_hire_path_only_when_submitted(actor: User) -> None:
    now = timezone.now()
    open_inv = _invitation(actor, expires_at=_ahead(2))
    submitted = _invitation(actor, status=SelfFormStatus.SUBMITTED, expires_at=_ahead(2), submitted_at=now)
    rows = {row.invitation.pk: row for row in selfform_page.list_rows(actor, now)}
    assert rows[open_inv.pk].hire_path == ""
    assert rows[open_inv.pk].when == open_inv.expires_at
    assert rows[submitted.pk].hire_path == f"{reverse('employees:add')}?submission={submitted.pk}"
    assert rows[submitted.pk].when == submitted.submitted_at
    assert rows[submitted.pk].badge == selfform_page.BADGES["submitted"][1]


def test_show_data_for_open_and_purged(actor: User) -> None:
    request = RequestFactory().get("/")
    open_inv = _invitation(actor, expires_at=_ahead(2))
    data = selfform_page.show_data(actor, open_inv.pk, request)
    assert data.state_key == "open"
    assert data.state == selfform_page.BADGES["open"][0]
    assert data.purged is False
    assert data.url.endswith(f"/apply/{open_inv.token}/")
    assert data.url.startswith("http://testserver/")
    assert data.hire_path == f"{reverse('employees:add')}?submission={open_inv.pk}"
    assert data.default_hours > 0

    purged = _invitation(actor, expires_at=_ahead(2), purged_at=timezone.now(), answers="{}", photo_b64="")
    purged_data = selfform_page.show_data(actor, purged.pk, request)
    assert purged_data.purged is True


def test_show_data_hides_an_invitation_outside_the_scope(actor: User) -> None:
    inv = _invitation(actor, expires_at=_ahead(2))
    stranger = User.objects.create_user("hr_page_stranger", password="x-long-pass-123")  # noqa: S106
    stranger.groups.add(Group.objects.get(name=roles.HR))
    limited_branch = Branch.objects.create(name="Салбар В")
    AccessScope.objects.create(user=stranger, limited=True, branch_ids=[limited_branch.pk])
    stranger = User.objects.get(pk=stranger.pk)
    with pytest.raises(Http404):
        selfform_page.show_data(stranger, inv.pk, RequestFactory().get("/"))


def test_qr_or_none_when_segno_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "segno", None)  # importing segno now raises ImportError
    assert selfform_page.qr_or_none("https://example.test/apply/abc/") is None


def test_qr_or_none_when_link_too_long(monkeypatch: pytest.MonkeyPatch) -> None:
    segno = pytest.importorskip("segno")

    def too_long(url: str) -> str:
        raise segno.DataOverflowError("too long for a QR code")

    monkeypatch.setattr(service, "qr_svg", too_long)
    assert selfform_page.qr_or_none("https://example.test/apply/abc/") is None


def test_qr_or_none_draws_an_svg_for_a_short_link() -> None:
    pytest.importorskip("segno")
    svg = selfform_page.qr_or_none("https://example.test/apply/abc/")
    assert svg is not None
    assert "<svg" in svg


def test_parse_hours_blank_digits_and_bad() -> None:
    assert selfform_page.parse_hours("") is None
    assert selfform_page.parse_hours("   ") is None
    assert selfform_page.parse_hours("12") == 12
    assert selfform_page.parse_hours(" 12 ") == 12
    for raw in ("1x", "1234567", "-3"):
        with pytest.raises(service.SelfFormError, match="бүхэл тоогоор"):
            selfform_page.parse_hours(raw)

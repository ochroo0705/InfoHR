"""Self-form invitation life cycle: tokens, expiry, visibility, revoke and extend."""

from datetime import timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, SystemLogEntry, User
from django.contrib.auth.models import Group
from django.http import Http404
from django.test import RequestFactory
from django.utils import timezone
from macs.models import Branch

from employees.models import CompanySettings, SelfFormInvitation, SelfFormStatus
from employees.selfform.service import (
    SelfFormError,
    create_invitation,
    extend,
    get_for_token,
    invitation_for,
    invitation_url,
    is_expired,
    is_fillable,
    revoke,
    visible_invitations,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def north(db: None) -> Branch:
    return Branch.objects.create(name="Хойд")


@pytest.fixture
def south(db: None) -> Branch:
    return Branch.objects.create(name="Өмнөд")


def _limited_hr(branch: Branch) -> User:
    """A branch-limited HR user, built the way test_scope_screens._user_in builds one."""
    user = User.objects.create_user("hr_limited", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=roles.HR))
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _expire(inv: SelfFormInvitation) -> None:
    inv.expires_at = timezone.now() - timedelta(minutes=1)
    inv.save(update_fields=["expires_at"])


def test_token_has_at_least_32_chars_and_is_unique(actor: User) -> None:
    first = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    second = create_invitation(label="Дорж", branch=None, hours=None, by=actor)
    assert len(first.token) == 32
    assert first.token != second.token


def test_default_hours_is_72_from_settings(actor: User) -> None:
    now = timezone.now()
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    assert abs((inv.expires_at - (now + timedelta(hours=72))).total_seconds()) < 1

    settings_row = CompanySettings.get()
    settings_row.selfform_default_hours = 24
    settings_row.save(update_fields=["selfform_default_hours"])
    now = timezone.now()
    shorter = create_invitation(label="Дорж", branch=None, hours=None, by=actor)
    assert abs((shorter.expires_at - (now + timedelta(hours=24))).total_seconds()) < 1


@pytest.mark.parametrize("bad", ["", "x", "a" * 10000, "../etc", "a" * 19, "a b c d e f g h i j k"])
def test_get_for_token_rejects_bad_shapes(actor: User, bad: str) -> None:
    create_invitation(label="Бат", branch=None, hours=None, by=actor)
    assert get_for_token(bad) is None


def test_get_for_token_is_exact_match(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    assert get_for_token(inv.token) == inv
    assert get_for_token(inv.token.upper()) is None


def test_is_fillable_false_after_expiry_and_for_non_open(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    assert is_fillable(inv) and not is_expired(inv)

    _expire(inv)
    assert is_expired(inv) and not is_fillable(inv)

    submitted = create_invitation(label="Дорж", branch=None, hours=None, by=actor)
    submitted.status = SelfFormStatus.SUBMITTED
    submitted.save(update_fields=["status"])
    assert not is_expired(submitted) and not is_fillable(submitted)


def test_extend_reopens_expired_open_invitation_for_fresh_hours(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=1, by=actor)
    _expire(inv)
    extend(inv, hours=24, by=actor)
    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.OPEN
    assert abs((inv.expires_at - (timezone.now() + timedelta(hours=24))).total_seconds()) < 5
    assert is_fillable(inv)


def test_extend_refuses_submitted_invitation(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    inv.status = SelfFormStatus.SUBMITTED
    inv.save(update_fields=["status"])
    with pytest.raises(SelfFormError):
        extend(inv, hours=24, by=actor)


def test_revoke_blocks_fillable_and_writes_audit(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    revoke(inv, by=actor)
    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.REVOKED
    assert not is_fillable(inv)
    assert SystemLogEntry.objects.filter(action="selfform_revoked").exists()


def test_revoke_refuses_confirmed_invitation(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)
    inv.status = SelfFormStatus.CONFIRMED
    inv.save(update_fields=["status"])
    with pytest.raises(SelfFormError):
        revoke(inv, by=actor)


def test_branch_limited_user_sees_only_own_branch(actor: User, north: Branch, south: Branch) -> None:
    limited = _limited_hr(north)
    own = create_invitation(label="Хойд", branch=north, hours=None, by=limited)
    other = create_invitation(label="Өмнөд", branch=south, hours=None, by=actor)

    assert list(visible_invitations(limited)) == [own]
    assert invitation_for(limited, own.pk) == own
    with pytest.raises(Http404):
        invitation_for(limited, other.pk)


def test_branch_limited_user_must_pick_a_branch(north: Branch) -> None:
    limited = _limited_hr(north)
    with pytest.raises(SelfFormError):
        create_invitation(label="Бат", branch=None, hours=None, by=limited)


def test_branch_limited_user_cannot_create_outside_own_branch(north: Branch, south: Branch) -> None:
    limited = _limited_hr(north)
    with pytest.raises(SelfFormError):
        create_invitation(label="Бат", branch=south, hours=None, by=limited)
    assert not SelfFormInvitation.objects.filter(label="Бат").exists()


def test_unlimited_user_sees_every_invitation(actor: User, north: Branch, south: Branch) -> None:
    first = create_invitation(label="Хойд", branch=north, hours=None, by=actor)
    second = create_invitation(label="Өмнөд", branch=south, hours=None, by=actor)
    assert set(visible_invitations(actor)) == {first, second}


@pytest.mark.parametrize("hours", [0, -1])
def test_hours_below_one_is_refused(actor: User, hours: int) -> None:
    with pytest.raises(SelfFormError):
        create_invitation(label="Бат", branch=None, hours=hours, by=actor)
    inv = create_invitation(label="Дорж", branch=None, hours=1, by=actor)
    with pytest.raises(SelfFormError):
        extend(inv, hours=hours, by=actor)


def test_huge_hours_is_refused_by_create_and_extend(actor: User) -> None:
    with pytest.raises(SelfFormError):
        create_invitation(label="Бат", branch=None, hours=10**9, by=actor)
    inv = create_invitation(label="Дорж", branch=None, hours=None, by=actor)
    with pytest.raises(SelfFormError):
        extend(inv, hours=10**9, by=actor)


def test_revoke_with_stale_object_refuses_a_row_that_was_confirmed(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)  # caller's copy: open
    SelfFormInvitation.objects.filter(pk=inv.pk).update(status=SelfFormStatus.CONFIRMED)

    with pytest.raises(SelfFormError):
        revoke(inv, by=actor)

    assert SelfFormInvitation.objects.get(pk=inv.pk).status == SelfFormStatus.CONFIRMED


def test_extend_with_stale_object_refuses_a_row_that_was_submitted(actor: User) -> None:
    inv = create_invitation(label="Бат", branch=None, hours=None, by=actor)  # caller's copy: open
    SelfFormInvitation.objects.filter(pk=inv.pk).update(status=SelfFormStatus.SUBMITTED)
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    with pytest.raises(SelfFormError):
        extend(inv, hours=48, by=actor)

    assert SelfFormInvitation.objects.get(pk=inv.pk).expires_at == before


def test_invitation_url_defaults_to_the_request_host(actor: User) -> None:
    inv = create_invitation(label="Сараа", branch=None, hours=None, by=actor)

    url = invitation_url(inv, RequestFactory().get("/"))

    assert url == f"http://testserver/apply/{inv.token}/"


def test_invitation_url_uses_the_selfform_base_url_setting(actor: User) -> None:
    inv = create_invitation(label="Сараа", branch=None, hours=None, by=actor)
    row = CompanySettings.get()
    row.selfform_base_url = "https://hr.example.mn/"
    row.save(update_fields=["selfform_base_url"])

    url = invitation_url(inv, RequestFactory().get("/"))

    assert url == f"https://hr.example.mn/apply/{inv.token}/"

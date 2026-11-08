"""The self-form retention purge (service.purge_old), its hook in the daily sync, the admin settings, and the
QR overflow on the link page."""

import logging
from datetime import date, datetime, timedelta
from typing import Any

import pytest
import segno
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.forms.models import model_to_dict
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from employees import daily_sync
from employees.daily_sync import run_daily_sync
from employees.models import CompanySettings, DailySync, SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.selfform.service import SelfFormError, create_invitation, extend, is_fillable, purge_old, revoke

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


def _ago(days: int) -> datetime:
    return timezone.now() - timedelta(days=days)


def _ahead(days: int) -> datetime:
    return timezone.now() + timedelta(days=days)


def _today() -> date:
    return timezone.localdate()


def _invitation(actor: User, **fields: Any) -> SelfFormInvitation:
    inv = create_invitation(label="Бат Бат", branch=None, hours=72, by=actor)
    SelfFormInvitation.objects.filter(pk=inv.pk).update(
        answers='{"last_name": "Бат"}', photo_b64="ZGF0YQ==", consent_text="Зөвшөөрөл", **fields
    )
    return SelfFormInvitation.objects.get(pk=inv.pk)


def _selfform_purged_entries() -> int:
    return SystemLogEntry.objects.filter(action="selfform_purged").count()


def test_confirmed_older_than_retention_is_cleared_and_keeps_who_when_outcome(actor: User) -> None:
    reviewed = _ago(31)
    submitted = _ago(40)
    inv = _invitation(
        actor,
        status=SelfFormStatus.CONFIRMED,
        reviewed_by=actor,
        reviewed_at=reviewed,
        submitted_at=submitted,
        consented_at=submitted,
    )

    assert purge_old(_today()) == 1

    inv.refresh_from_db()
    assert inv.answers == "{}"
    assert inv.photo_b64 == ""
    assert inv.purged_at is not None
    assert inv.status == SelfFormStatus.CONFIRMED
    assert inv.reviewed_by == actor
    assert inv.reviewed_at == reviewed
    assert inv.submitted_at == submitted
    assert inv.consented_at == submitted
    assert inv.consent_text == "Зөвшөөрөл"
    assert inv.label == "Бат Бат"


def test_recent_confirmed_is_kept(actor: User) -> None:
    inv = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(29))

    assert purge_old(_today()) == 0

    inv.refresh_from_db()
    assert inv.answers == '{"last_name": "Бат"}'
    assert inv.photo_b64 == "ZGF0YQ=="
    assert inv.purged_at is None


def test_exactly_retention_days_old_is_kept_and_one_day_more_is_purged(actor: User) -> None:
    kept = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(30))
    purged = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(31))

    assert purge_old(_today()) == 1

    kept.refresh_from_db()
    purged.refresh_from_db()
    assert kept.purged_at is None
    assert purged.purged_at is not None


def test_rejected_older_than_retention_is_cleared_and_keeps_reason(actor: User) -> None:
    inv = _invitation(
        actor,
        status=SelfFormStatus.REJECTED,
        reviewed_by=actor,
        reviewed_at=_ago(31),
        reject_reason="Дутуу мэдээлэл",
    )
    recent = _invitation(actor, status=SelfFormStatus.REJECTED, reviewed_at=_ago(5), reject_reason="x")

    assert purge_old(_today()) == 1

    inv.refresh_from_db()
    recent.refresh_from_db()
    assert inv.answers == "{}" and inv.photo_b64 == ""
    assert inv.reject_reason == "Дутуу мэдээлэл"
    assert inv.reviewed_by == actor
    assert recent.purged_at is None


def test_revoked_counts_from_the_day_hr_cancelled(actor: User) -> None:
    old = _invitation(
        actor, status=SelfFormStatus.REVOKED, reviewed_by=actor, reviewed_at=_ago(31), expires_at=_ahead(3)
    )
    recent = _invitation(
        actor, status=SelfFormStatus.REVOKED, reviewed_by=actor, reviewed_at=_ago(10), expires_at=_ago(60)
    )

    assert purge_old(_today()) == 1

    old.refresh_from_db()
    recent.refresh_from_db()
    assert old.answers == "{}" and old.purged_at is not None
    assert recent.purged_at is None


def test_revoke_stamps_reviewed_by_and_reviewed_at(actor: User) -> None:
    inv = _invitation(actor, status=SelfFormStatus.SUBMITTED, submitted_at=_ago(2), expires_at=_ahead(1))

    revoke(inv, by=actor)

    inv.refresh_from_db()
    assert inv.status == SelfFormStatus.REVOKED
    assert inv.reviewed_by == actor
    assert inv.reviewed_at is not None and abs((inv.reviewed_at - timezone.now()).total_seconds()) < 60


def test_submitted_then_revoked_today_keeps_answers_past_expiry_until_retention(actor: User) -> None:
    """A submission HR cancelled today is not wiped just because its link expired long ago."""
    inv = _invitation(actor, status=SelfFormStatus.SUBMITTED, submitted_at=_ago(100), expires_at=_ago(90))
    revoke(inv, by=actor)

    assert purge_old(_today()) == 0
    inv.refresh_from_db()
    assert inv.answers == '{"last_name": "Бат"}'
    assert inv.purged_at is None

    assert purge_old(_today() + timedelta(days=31)) == 1
    inv.refresh_from_db()
    assert inv.answers == "{}"


def test_extend_refused_after_purge_and_answers_stay_empty(actor: User) -> None:
    inv = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ago(31))
    assert purge_old(_today()) == 1
    before = SelfFormInvitation.objects.get(pk=inv.pk).expires_at

    with pytest.raises(SelfFormError):
        extend(inv, hours=24, by=actor)

    stored = SelfFormInvitation.objects.get(pk=inv.pk)
    assert stored.answers == "{}"
    assert stored.expires_at == before
    assert stored.status == SelfFormStatus.OPEN


def test_purged_row_is_not_fillable(actor: User) -> None:
    inv = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ago(31))
    assert purge_old(_today()) == 1
    inv.refresh_from_db()
    assert not is_fillable(inv)


def test_extend_button_is_absent_on_show_page_of_purged_row(client: Client, actor: User) -> None:
    hr = User.objects.create_user("hr_purged_show", password=PASSWORD)  # noqa: S106
    hr.groups.add(Group.objects.get(name="HR"))
    client.force_login(hr)
    inv = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ago(31))
    assert purge_old(_today()) == 1

    response = client.get(reverse("employees:selfform_show", args=[inv.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Хариулт устгагдсан" in content
    assert reverse("employees:selfform_extend", args=[inv.pk]) not in content


def test_abandoned_draft_cleared_after_expiry_plus_retention(actor: User) -> None:
    abandoned = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ago(31))
    expired_recently = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ago(10))

    assert purge_old(_today()) == 1

    abandoned.refresh_from_db()
    expired_recently.refresh_from_db()
    assert abandoned.answers == "{}" and abandoned.photo_b64 == ""
    assert expired_recently.purged_at is None


def test_unexpired_open_invitation_is_never_purged(actor: User) -> None:
    open_now = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ahead(1))

    assert purge_old(_today()) == 0

    open_now.refresh_from_db()
    assert open_now.answers == '{"last_name": "Бат"}'
    assert open_now.purged_at is None


def test_submitted_is_never_purged_even_far_past_retention(actor: User) -> None:
    """HR has not decided yet: a submission nobody reviewed must keep its answers and photo."""
    waiting = _invitation(actor, status=SelfFormStatus.SUBMITTED, expires_at=_ago(90), submitted_at=_ago(95))

    assert purge_old(_today()) == 0

    waiting.refresh_from_db()
    assert waiting.answers == '{"last_name": "Бат"}'
    assert waiting.photo_b64 == "ZGF0YQ=="
    assert waiting.purged_at is None


def test_sent_back_open_invitation_expired_and_old_is_cleared(actor: User) -> None:
    """HR sent the form back and the employee never finished: an abandoned draft, counted from its expiry."""
    sent_back = _invitation(
        actor,
        status=SelfFormStatus.OPEN,
        reviewed_by=actor,
        reviewed_at=_ago(60),
        hr_note="Нэмж бөглөнө үү",
        expires_at=_ago(31),
    )

    assert purge_old(_today()) == 1

    sent_back.refresh_from_db()
    assert sent_back.answers == "{}" and sent_back.photo_b64 == ""
    assert sent_back.hr_note == "Нэмж бөглөнө үү"


def test_retention_setting_is_respected(actor: User) -> None:
    row = CompanySettings.get()
    row.selfform_retention_days = 7
    row.save()
    eight_days = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(8))
    six_days = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(6))

    assert purge_old(_today()) == 1

    eight_days.refresh_from_db()
    six_days.refresh_from_db()
    assert eight_days.purged_at is not None
    assert six_days.purged_at is None


def test_purge_is_idempotent_and_writes_one_entry_per_run(actor: User) -> None:
    _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(40))

    assert purge_old(_today()) == 1
    assert purge_old(_today()) == 0
    assert _selfform_purged_entries() == 1


def test_no_audit_entry_when_nothing_is_purged(actor: User) -> None:
    _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(1))

    assert purge_old(_today()) == 0
    assert _selfform_purged_entries() == 0


def test_purge_never_touches_employee_side_data(actor: User) -> None:
    inv = _invitation(actor, status=SelfFormStatus.CONFIRMED, reviewed_by=actor, reviewed_at=_ago(40))
    before = (inv.label, inv.branch_id, inv.created_by_id, inv.employee_id)

    purge_old(_today())

    inv.refresh_from_db()
    assert (inv.label, inv.branch_id, inv.created_by_id, inv.employee_id) == before


def test_run_daily_sync_triggers_the_purge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[date] = []

    def fake_purge(today: date) -> int:
        calls.append(today)
        return 0

    monkeypatch.setattr(service, "purge_old", fake_purge)

    run_daily_sync(date(2026, 10, 16))
    run_daily_sync(date(2026, 10, 16))  # the skipped second run does not purge

    assert calls == [date(2026, 10, 16)]


def test_purge_failure_does_not_break_run_daily_sync(monkeypatch: pytest.MonkeyPatch, caplog: Any) -> None:
    def broken(today: date) -> int:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(service, "purge_old", broken)
    caplog.set_level(logging.ERROR, logger="employees.daily_sync")

    changed = run_daily_sync(date(2026, 10, 16))

    assert changed == 0
    assert DailySync.objects.get(pk=daily_sync.SINGLETON_PK).day == date(2026, 10, 16)
    assert any(record.exc_info for record in caplog.records)


@pytest.fixture
def superuser_client(client: Client) -> Client:
    client.force_login(User.objects.create_superuser("company_purge", password=PASSWORD))  # noqa: S106
    return client


def test_admin_change_page_shows_selfform_fieldset(superuser_client: Client) -> None:
    row = CompanySettings.get()
    response = superuser_client.get(reverse("admin:employees_companysettings_change", args=[row.pk]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Өөрөө бөглөх анкет" in content
    for name in (
        "selfform_base_url",
        "selfform_notice",
        "selfform_retention_days",
        "selfform_default_hours",
    ):
        assert f'name="{name}"' in content


def _admin_form(row: CompanySettings, **overrides: Any) -> Any:
    from django.contrib.admin.sites import site

    admin = site._registry[CompanySettings]
    request = RequestFactory().get("/")
    request.user = User.objects.create_superuser("company_form", password=PASSWORD)  # noqa: S106
    data = {k: v for k, v in model_to_dict(row).items() if v is not None}
    data.update(overrides)
    form_class = admin.get_form(request, row)
    return form_class(data=data, instance=row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selfform_default_hours", "0"),
        ("selfform_default_hours", "8761"),
        ("selfform_retention_days", "0"),
        ("selfform_retention_days", "3651"),
        ("selfform_base_url", "ftp://x"),
        ("selfform_base_url", "https://" + "a" * 193),
    ],
)
def test_admin_refuses_bad_selfform_settings(field: str, value: str) -> None:
    form = _admin_form(CompanySettings.get(), **{field: value})
    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selfform_default_hours", "8760"),
        ("selfform_default_hours", "1"),
        ("selfform_retention_days", "1"),
        ("selfform_retention_days", "3650"),
        ("selfform_base_url", "https://hr.example.mn/"),
        ("selfform_base_url", ""),
    ],
)
def test_admin_accepts_edge_selfform_settings(field: str, value: str) -> None:
    form = _admin_form(CompanySettings.get(), **{field: value})
    assert form.is_valid(), form.errors


def test_admin_help_says_placeholder_when_notice_is_blank() -> None:
    form = _admin_form(CompanySettings.get(), selfform_notice="")
    assert "баталгаажуул" in form.fields["selfform_notice"].help_text.lower()


def test_link_page_survives_qr_data_overflow(client: Client, monkeypatch: pytest.MonkeyPatch, actor: User) -> None:
    hr = User.objects.create_user("hr_overflow", password=PASSWORD)  # noqa: S106
    hr.groups.add(Group.objects.get(name="HR"))
    client.force_login(hr)
    inv = _invitation(actor, status=SelfFormStatus.OPEN, expires_at=_ahead(2))

    def too_long(url: str) -> str:
        raise segno.DataOverflowError("too long for a QR code")

    monkeypatch.setattr(service, "qr_svg", too_long)

    response = client.get(reverse("employees:selfform_show", args=[inv.pk]))

    assert response.status_code == 200
    assert response.context["qr"] is None
    assert f"/apply/{inv.token}/" in response.content.decode()

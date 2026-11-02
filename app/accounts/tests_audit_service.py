"""System log: SystemLogEntry is append-only, record() fills actor and ip from the request context."""

from collections.abc import Iterator

import pytest
from django.contrib.auth.models import Group

from accounts import audit, audit_context
from accounts.audit import record, record_safe
from accounts.models import SystemLogEntry, User
from accounts.roles import ACCOUNTANT, ADMIN, EMPLOYEE, HR

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


def test_record_defaults_actor_and_ip_from_context() -> None:
    user = User.objects.create_user("audit_actor", password="x-long-pass-123")  # noqa: S106
    audit_context.set_context(user, "10.0.0.5")

    entry = record("access", "login", message="Нэвтэрлээ")

    entry.refresh_from_db()
    assert entry.actor == user
    assert entry.actor_name == user.username
    assert entry.ip == "10.0.0.5"
    assert entry.category == "access" and entry.action == "login"


def test_record_without_context_gives_null_actor() -> None:
    entry = record("settings", "setting_changed", target_type="Setting", target_label="x")

    entry.refresh_from_db()
    assert entry.actor is None
    assert entry.actor_name == ""
    assert entry.ip is None


def test_entry_is_append_only() -> None:
    entry = record("access", "logout")

    with pytest.raises(PermissionError):
        entry.message = "changed"
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()
    with pytest.raises(PermissionError):
        SystemLogEntry.objects.update(message="changed")
    with pytest.raises(PermissionError):
        SystemLogEntry.objects.all().delete()


def test_record_safe_swallows_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is down")

    logged: list[str] = []
    monkeypatch.setattr(SystemLogEntry.objects, "create", boom)
    monkeypatch.setattr(audit.logger, "exception", lambda msg, *args: logged.append(msg % args))

    assert record_safe("access", "login_failed") is None
    assert logged == ["System log entry was not saved: access login_failed"]
    with pytest.raises(RuntimeError):
        record("access", "login_failed")


def test_view_audit_default_admin_only() -> None:
    def has_view_audit(group_name: str) -> bool:
        return (
            Group.objects.get(name=group_name)
            .permissions.filter(content_type__app_label="accounts", codename="view_audit")
            .exists()
        )

    assert has_view_audit(ADMIN)
    assert not has_view_audit(HR)
    assert not has_view_audit(ACCOUNTANT)
    assert not has_view_audit(EMPLOYEE)


def test_str_is_safe_for_unsaved_entry() -> None:
    assert str(SystemLogEntry(action="login", actor_name="naraa")) == "- naraa login"


def test_deleting_user_keeps_entry_and_its_name() -> None:
    user = User.objects.create_user("audit_gone", password="x-long-pass-123")  # noqa: S106
    entry = record("access", "login", actor=user)

    user.delete()

    entry.refresh_from_db()
    assert entry.actor is None
    assert entry.actor_name == "audit_gone"

"""Audit receivers for accounts: logins, user switches, group and permission links.

Flag changes (is_active, is_superuser, is_staff) are logged in post_save with record(), so a failed log write
raises inside the save. Outside an atomic block the flag change can already be committed before that failure
surfaces. The admin change form is atomic, so there the change and its log line stand or fall together.
"""

from typing import Any

from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import m2m_changed, post_save, pre_save
from django.dispatch import receiver

from . import login_throttle
from .audit import Category, record, record_safe
from .models import User
from .roles import EMPLOYEE


@receiver(post_save, sender=User, dispatch_uid="accounts_add_employee_role")
def add_employee_role(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    """Every user gets the Employee role automatically (core-hr-scope §1)."""
    if created:
        group, _ = Group.objects.get_or_create(name=EMPLOYEE)
        instance.groups.add(group)


@receiver(user_logged_in, dispatch_uid="accounts_audit_login")
def log_login(sender: type[User], request: Any, user: User, **kwargs: Any) -> None:
    """Pass the user explicitly: during the login view the request context still shows no user."""
    record_safe(Category.ACCESS, "login", actor=user)
    login_throttle.reset(request, user.get_username())


@receiver(user_login_failed, dispatch_uid="accounts_audit_login_failed")
def log_login_failed(sender: Any, credentials: dict[str, Any], request: Any = None, **kwargs: Any) -> None:
    """Store only the username that was typed. The password is never written to the log."""
    username = str(credentials.get("username") or "")[:150]
    record_safe(Category.ACCESS, "login_failed", message=username, actor=None)
    login_throttle.record_failure(request, username)


@receiver(user_logged_out, dispatch_uid="accounts_audit_logout")
def log_logout(sender: type[User], request: Any, user: User | None, **kwargs: Any) -> None:
    """Django sends this for anonymous visitors too (user is None). Those are not logged out, so skip them."""
    if user is None:
        return
    record_safe(Category.ACCESS, "logout", actor=user)


# User switches whose change is logged: (field, action code, Mongolian label).
WATCHED_USER_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("is_active", "user_active_changed", "Идэвхтэй"),
    ("is_superuser", "superuser_changed", "Супер админ"),
    ("is_staff", "staff_changed", "Удирдлагын хэсэг"),
)


def _yes_no(value: Any) -> str:
    return "Тийм" if value else "Үгүй"


@receiver(pre_save, sender=User, dispatch_uid="accounts_audit_user_before_save")
def snapshot_user_flags(sender: type[User], instance: User, raw: bool = False, **kwargs: Any) -> None:
    """One query: remember the switches as they were, so post_save can tell what changed.

    Also marks a brand-new user, so its automatic Employee role is not logged as a separate change.
    """
    instance.__dict__["_audit_new"] = instance.pk is None
    instance.__dict__["_audit_before"] = None
    update_fields = kwargs.get("update_fields")
    touches_flags = update_fields is None or bool({field for field, _a, _l in WATCHED_USER_FLAGS} & set(update_fields))
    if (
        instance.pk is not None and not raw and touches_flags
    ):  # e.g. the last_login save on every login skips the SELECT
        fields = [field for field, _action, _label in WATCHED_USER_FLAGS]
        instance.__dict__["_audit_before"] = User.objects.filter(pk=instance.pk).values(*fields).first()


@receiver(post_save, sender=User, dispatch_uid="accounts_audit_user_saved")
def log_user_saved(sender: type[User], instance: User, created: bool, raw: bool = False, **kwargs: Any) -> None:
    """Runs after add_employee_role (connected later in this file), so the new user's flag is cleared last."""
    before = instance.__dict__.pop("_audit_before", None)
    instance.__dict__["_audit_new"] = False
    if raw:
        return
    if created:
        record(Category.ACCESS, "login_created", target_type="user", target_label=instance.username)
        return
    if not before:
        return
    for field, action, label in WATCHED_USER_FLAGS:
        old, new = before[field], getattr(instance, field)
        if old != new:
            record(
                Category.ACCESS,
                action,
                target_type="user",
                target_label=instance.username,
                message=label,
                changes=[{"field": label, "old": _yes_no(old), "new": _yes_no(new)}],
            )


def _label_of(obj: Any) -> str:
    if isinstance(obj, Group):
        return str(obj.name)
    if isinstance(obj, Permission):
        return str(obj.codename)
    return str(obj.username)


def _record_membership(owner: Any, action_code: str, message: str) -> None:
    """One line on the owner: a user (target type user) or a role group (target type role)."""
    if isinstance(owner, User):
        record(Category.ACCESS, action_code, message=message, target_type="user", target_label=owner.username)
    else:
        record(Category.ACCESS, action_code, message=message, target_type="role", target_label=str(owner.name))


def _log_membership(
    sender: Any, instance: Any, action: str, reverse: bool, model: Any, pk_set: Any, action_code: str
) -> None:
    """Shared by the three m2m links (user-groups, user-permissions, role-permissions).

    Forward (instance is the user or the role): one line on that owner.
    Reverse (instance is the group or the permission, e.g. group.user_set.add): one line per affected owner.
    Raises on failure (record, not record_safe): the change runs in the same transaction and must roll back.
    """
    new_user = not reverse and isinstance(instance, User) and bool(instance.__dict__.get("_audit_new"))
    instance_key = f"{instance._meta.model_name}_id"
    other_key = f"{model._meta.model_name}_id"
    if action == "pre_clear":  # pk_set is None on post_clear, so remember what was linked before
        instance.__dict__["_audit_cleared"] = list(
            sender.objects.filter(**{instance_key: instance.pk}).values_list(other_key, flat=True)
        )
        return
    if action == "post_clear":
        pks = list(instance.__dict__.pop("_audit_cleared", []))
    elif action in ("post_add", "post_remove"):
        pks = list(pk_set or [])
    else:
        return
    if new_user and model is Group:  # only the automatic Employee role is left out: login_created covers it
        employee_pks = set(Group.objects.filter(name=EMPLOYEE).values_list("pk", flat=True))
        pks = [pk for pk in pks if pk not in employee_pks]
    if not pks:
        return
    verb = "Нэмсэн" if action == "post_add" else "Хассан"
    if reverse:
        message = f"{verb}: {_label_of(instance)}"
        for owner in model.objects.filter(pk__in=pks):
            _record_membership(owner, action_code, message)
    else:
        labels = sorted(_label_of(obj) for obj in model.objects.filter(pk__in=pks))
        if labels:
            _record_membership(instance, action_code, f"{verb}: {', '.join(labels)}")


@receiver(m2m_changed, sender=User.groups.through, dispatch_uid="accounts_audit_user_groups")
def log_user_groups(
    sender: Any, instance: Any, action: str, reverse: bool, model: Any, pk_set: Any, **kwargs: Any
) -> None:
    _log_membership(sender, instance, action, reverse, model, pk_set, "groups_changed")


@receiver(m2m_changed, sender=User.user_permissions.through, dispatch_uid="accounts_audit_user_permissions")
def log_user_permissions(
    sender: Any, instance: Any, action: str, reverse: bool, model: Any, pk_set: Any, **kwargs: Any
) -> None:
    _log_membership(sender, instance, action, reverse, model, pk_set, "permissions_changed")


@receiver(m2m_changed, sender=Group.permissions.through, dispatch_uid="accounts_audit_role_permissions")
def log_role_permissions(
    sender: Any, instance: Any, action: str, reverse: bool, model: Any, pk_set: Any, **kwargs: Any
) -> None:
    _log_membership(sender, instance, action, reverse, model, pk_set, "permissions_changed")

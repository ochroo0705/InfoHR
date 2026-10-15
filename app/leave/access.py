"""Who may do what in the leave module. Every leave view asks this module."""

from accounts.models import User


def can_view(user: User) -> bool:
    return user.is_active and user.has_perm("leave.view_leave")


def can_record(user: User) -> bool:
    return user.is_active and user.has_perm("leave.record_leave") and can_view(user)


def can_manage_settings(user: User) -> bool:
    return user.is_active and user.has_perm("leave.manage_leave_settings")

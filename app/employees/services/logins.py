"""Giving an existing employee a login (a User account). Used by the hire form and the detail page.

Passwords are never chosen by an admin: the system makes a temporary one, the manager hands it over,
and the user must change it at first login. The plain password is returned to the caller once and is
never written to a log, a message or an ActivityEntry.
"""

from accounts.models import User
from accounts.passwords import set_temp_password
from django.db import transaction

from employees.models import ActivityEntry, ActivityKind, Employee, ensure_ext


@transaction.atomic
def create_login(employee: Employee, username: str, by: User) -> tuple[User, str]:
    """Create the User with a temporary password, link it to `employee` and log it.

    Returns (user, temporary password). The password is shown once; the user must change it at first login.
    """
    username = username.strip()
    if not username:
        raise ValueError("Нэвтрэх нэрийг бичнэ үү.")
    ext = ensure_ext(employee)
    if ext.user_id is not None:
        raise ValueError("Нэвтрэх эрх аль хэдийн байна.")
    if User.objects.filter(username=username).exists():
        raise ValueError("Энэ нэвтрэх нэр бүртгэлтэй байна.")
    login = User.objects.create_user(username, first_name=employee.given_name, last_name=employee.family_name)
    password = set_temp_password(login)
    ext.user = login
    ext.save(update_fields=["user"])
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.CHANGED,
        message=f"Нэвтрэх эрх үүсгэсэн: {username}",
        changes=[{"field": "Нэвтрэх нэр", "old": "", "new": username}],
    )
    return login, password

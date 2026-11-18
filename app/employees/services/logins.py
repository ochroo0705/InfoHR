"""Giving an existing employee a login (a User account). Used by the hire form and the detail page.

Passwords are never chosen by an admin: the system makes a temporary one, the manager hands it over,
and the user must change it at first login. The plain password is returned to the caller once and is
never written to a log, a message or an ActivityEntry.
"""

from accounts.models import User
from accounts.passwords import set_temp_password
from django.db import IntegrityError, transaction

from employees import history_range
from employees.models import ActivityEntry, ActivityKind, Employee, ensure_ext


@transaction.atomic
def create_login(employee: Employee, username: str, by: User) -> tuple[User, str]:
    """Create the User with a temporary password, link it to `employee` and log it.

    Returns (user, temporary password). The password is shown once; the user must change it at first login.
    """
    username = username.strip()
    if not username:
        raise ValueError("Нэвтрэх нэрийг бичнэ үү.")
    # Lock order as setup.toggle: the history lock, then the Employee row. Two concurrent calls for one employee
    # wait here, so the second one sees the login the first one made.
    history_range.lock_employee(employee.pk)
    Employee.objects.select_for_update().get(pk=employee.pk)
    ext = ensure_ext(employee)
    if ext.user_id is not None:
        raise ValueError("Нэвтрэх эрх аль хэдийн байна.")
    if User.objects.filter(username=username).exists():
        raise ValueError("Энэ нэвтрэх нэр бүртгэлтэй байна.")
    try:
        with transaction.atomic():  # a savepoint: a duplicate name lost in a race is a ValueError, not a 500
            login = User.objects.create_user(username, first_name=employee.given_name, last_name=employee.family_name)
    except IntegrityError:
        raise ValueError("Энэ нэвтрэх нэр бүртгэлтэй байна.") from None
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

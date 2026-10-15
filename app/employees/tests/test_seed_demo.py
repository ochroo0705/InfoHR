from io import StringIO

import pytest
from accounts.models import User
from django.core.management import CommandError, call_command
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from employees.models import ActivityEntry, Employee
from employees.services.history import job_on

pytestmark = pytest.mark.django_db


def test_seed_demo_builds_company(settings: SettingsWrapper) -> None:
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    assert Employee.objects.count() == 10
    for login, role in [("director", "Admin"), ("hr", "HR"), ("accountant", "Accountant"), ("bold", "Employee")]:
        assert User.objects.get(username=login).groups.filter(name=role).exists()
    today = timezone.localdate()
    status = {e.given_name: getattr(job_on(e, today), "status", None) for e in Employee.objects.all()}
    assert status["Мөнх-Эрдэнэ"] == "left"
    assert status["Ариунаа"] == "long_leave"
    assert status["Хулан"] is None  # upcoming hire
    assert ActivityEntry.objects.filter(kind="note").count() == 3


def test_seed_demo_refuses_without_debug_or_when_data_exists(settings: SettingsWrapper) -> None:
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo")
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    with pytest.raises(CommandError):
        call_command("seed_demo", stdout=StringIO())


def test_seed_demo_adds_holidays_and_leaves(settings: SettingsWrapper) -> None:
    from leave.models import Holiday, Leave

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    assert Holiday.objects.exists()
    assert Leave.objects.count() >= 3


@pytest.mark.django_db
def test_seed_creates_demo_superuser(settings: SettingsWrapper) -> None:
    from employees.management.commands.seed_demo import DEMO_PASSWORD

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    admin = User.objects.get(username="admin")
    assert admin.is_superuser and admin.is_staff and admin.check_password(DEMO_PASSWORD)

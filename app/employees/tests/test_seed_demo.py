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
    from leave.models import LeaveExt
    from leave.services import ledger
    from macs.models import LeaveAssign, LegalHoliday

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    assert LegalHoliday.objects.exists()
    assert LeaveAssign.objects.count() >= 3
    assert ledger.annual_configured()
    # old-style rows (no ext row) exist next to rows written by Info HR
    assert LeaveAssign.objects.exclude(pk__in=LeaveExt.objects.values_list("assign", flat=True)).exists()
    assert LeaveAssign.objects.filter(status__isnull=True, adays__isnull=True).exists()


@pytest.mark.django_db
def test_seed_creates_demo_superuser(settings: SettingsWrapper) -> None:
    from employees.management.commands.seed_demo import DEMO_PASSWORD

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    admin = User.objects.get(username="admin")
    assert admin.is_superuser and admin.is_staff and admin.check_password(DEMO_PASSWORD)


def test_seed_demo_fills_list_entries_and_meaning(settings: SettingsWrapper) -> None:
    from lists.models import MONGOLIA, MeaningfulEntry
    from macs.models import Country, District, MaritalStatus, Shift

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    mongolia = Country.objects.get(name="Монгол")
    assert MeaningfulEntry.get(MONGOLIA) == mongolia.pk
    assert Country.objects.filter(name__in=["Япон", "Солонгос"]).count() == 2
    assert MaritalStatus.objects.filter(name="Гэрлэсэн").count() == 1
    assert Shift.objects.filter(name="09:00-18:00").count() == 1
    assert District.objects.filter(city__name="Улаанбаатар").count() == 6


def test_seed_demo_fills_personal_lists(settings: SettingsWrapper) -> None:
    from django.db import connection
    from django.db.models import F
    from macs.models import AddressRow, ContactRow, EducRow, FamilyRow, PresentRow

    from employees.models import EducationExt, GiftExt

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    # every employee has one address and one emergency contact written through personal_writes
    assert ContactRow.objects.count() == Employee.objects.count()
    assert AddressRow.objects.count() == Employee.objects.count() + 1  # + one old-style row
    # old-style rows: no ext row for education or gift
    assert EducRow.objects.exclude(pk__in=EducationExt.objects.values_list("educ", flat=True)).exists()
    assert PresentRow.objects.exclude(pk__in=GiftExt.objects.values_list("present", flat=True)).exists()
    assert FamilyRow.objects.filter(given_name="Дорждэрэм").exists()
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM emp_talents")
        assert cur.fetchone() == (1,)
    # the old-style address has a district of another city
    assert AddressRow.objects.exclude(district__city=F("city")).count() == 1


def test_seed_demo_adds_fired_reasons_and_death_meaning(settings: SettingsWrapper) -> None:
    from lists.models import DEATH, MeaningfulEntry
    from macs.models import FiredReason

    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    names = {
        "Өөрийн хүсэлтээр",
        "Харилцан тохиролцсон",
        "Гэрээний хугацаа дууссан",
        "Ажлаас халсан",
        "Тэтгэвэрт гарсан",
        "Нас барсан",
    }
    assert names <= set(FiredReason.objects.values_list("name", flat=True))
    assert MeaningfulEntry.get(DEATH) == FiredReason.objects.get(name="Нас барсан").pk

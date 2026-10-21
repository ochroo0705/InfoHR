from datetime import date

import pytest
from accounts.models import User

from employees.models import ActivityEntry, Employee, EmployeeExt, JobRecord
from employees.services import events, records
from employees.services.display import shown

pytestmark = pytest.mark.django_db


def test_shown_uses_choice_labels_dates_and_yes_no() -> None:
    status = JobRecord._meta.get_field("status")
    assert shown(status, "long_leave") == "Урт хугацааны чөлөөтэй"
    assert shown(EmployeeExt._meta.get_field("setup_required"), True) == "Тийм"
    assert shown(EmployeeExt._meta.get_field("setup_required"), False) == "Үгүй"
    assert shown(Employee._meta.get_field("birth_date"), date(1999, 1, 2)) == "1999-01-02"
    assert shown(status, None) == ""


def test_event_log_shows_status_labels(hired: Employee, actor: User) -> None:
    events.record(
        hired,
        type="leave_start",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="unpaid",
        note="",
        by=actor,
    )
    change = ActivityEntry.objects.filter(employee=hired).latest("id").changes[0]
    assert (change["old"], change["new"]) == ("Ажиллаж байгаа", "Урт хугацааны чөлөөтэй")


def test_edit_log_shows_choice_labels(hired: Employee, actor: User) -> None:
    changes = records.update_employee(hired, {"gender": "M"}, actor)
    assert changes[0]["old"] == "Эмэгтэй" and changes[0]["new"] == "Эрэгтэй"


def test_short_name_is_initial_and_given_name(hired: Employee) -> None:
    assert hired.short_name == f"{(hired.family_name or '')[:1]}. {hired.given_name}"
    hired.family_name = ""
    assert hired.short_name == hired.given_name

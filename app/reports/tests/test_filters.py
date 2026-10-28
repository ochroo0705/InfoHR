from datetime import date

import pytest
from accounts.models import User
from config.params import date_param
from django.contrib.auth.models import Group
from django.http import QueryDict
from django.utils import timezone
from employees.models import ensure_ext
from employees.services import macs_writes
from macs.models import AbsenceType, ContactType, Employee, LeaveTypeRow, PresentType

from reports.filters import Filters, describe, parse_filters, period_of, to_query
from reports.movements import MOVEMENTS
from reports.staff_list import REPORT as STAFF_LIST
from reports.table import usable_filters
from reports.types import Report


def test_garbage_is_ignored() -> None:
    f = parse_filters(
        QueryDict("state=x&as_of=2026-13-40&department=abc&branch=-1&gender=Q&cols=Nope&sort=--x&group=1")
    )
    assert f == Filters()


@pytest.mark.parametrize("query", ["age_from=--5", "age_to=--1", "year=--2000", "age_from=5-", "year=1e3"])
def test_double_sign_and_malformed_numbers_are_ignored(query: str) -> None:
    """Numbers are read as «-?digits» only; a value like --5 once raised ValueError (a 500)."""
    assert parse_filters(QueryDict(query)) == Filters()


def test_round_trip_keeps_values_and_order() -> None:
    q = "state=all&as_of=2025-12-31&department=7&cols=code&cols=name&group=department&sort=-name"
    assert to_query(parse_filters(QueryDict(q))) == q


def test_to_query_omits_defaults() -> None:
    assert to_query(Filters()) == ""


def test_date_param_rejects_out_of_range() -> None:
    assert date_param("1899-12-31") is None and date_param("2026-02-30") is None
    assert date_param("2026-10-23") == date(2026, 10, 23)


def test_describe_names_department(db: None) -> None:
    dept = macs_writes.save_department("Санхүү")
    assert describe(Filters(department=dept.pk), ("state", "department")) == ["Төлөв: Ажиллаж байгаа", "Хэлтэс: Санхүү"]


def test_describe_shows_dash_for_unknown_department(db: None) -> None:
    assert describe(Filters(department=999999), ("department",)) == ["Хэлтэс: —"]


def test_to_query_omits_today_as_of() -> None:
    assert to_query(Filters(as_of=timezone.localdate())) == ""
    assert to_query(Filters(as_of=date(2026, 3, 1))) == "as_of=2026-03-01"


def test_period_round_trip_and_new_keys() -> None:
    q = "from=2025-01-01&to=2025-06-30&change=transfer&reason=3&order_type=4&discipline=2&employee=11"
    f = parse_filters(QueryDict(q))
    assert (f.date_from, f.date_to, f.change, f.reason, f.order_type, f.discipline, f.employee) == (
        date(2025, 1, 1),
        date(2025, 6, 30),
        "transfer",
        3,
        4,
        2,
        11,
    )
    assert to_query(f) == q


def test_to_query_omits_default_period() -> None:
    year = timezone.localdate().year
    assert to_query(Filters(date_from=date(year, 1, 1), date_to=date(year, 12, 31))) == ""
    assert to_query(Filters(date_from=date(year, 2, 1))) == f"from={year}-02-01"


def test_new_filter_garbage_is_ignored() -> None:
    f = parse_filters(QueryDict("from=2026-02-30&to=x&change=opening&reason=a&order_type=99&discipline=-1&employee="))
    assert f == Filters()


def test_period_defaults_to_this_year() -> None:
    year = timezone.localdate().year
    assert period_of(Filters()) == (date(year, 1, 1), date(year, 12, 31))


def test_period_swaps_reversed_dates() -> None:
    f = Filters(date_from=date(2026, 12, 31), date_to=date(2026, 1, 1))
    assert period_of(f) == (date(2026, 1, 1), date(2026, 12, 31))


def test_describe_period_and_unknown_reason(db: None) -> None:
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31), reason=999999, change="hire")
    assert describe(f, ("period", "change", "reason")) == [
        "Хугацаа: 2026-01-01 – 2026-03-31",
        "Өөрчлөлт: Ажилд авсан",
        "Шалтгаан: —",
    ]


def _report(filters: tuple[str, ...], filter_needs: dict[str, str] | None = None) -> Report:
    """A small report that offers these filter names; no rows are needed for the filter checks."""
    return Report(
        key="t",
        title="Туршилт",
        filters=filters,
        columns=(),
        default_columns=(),
        rows=lambda user, f: [],
        filter_needs=filter_needs or {},
    )


def _user_with_role(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


def test_employee_filter_hidden_when_not_visible(db: None, hired: Employee, left_employee: Employee) -> None:
    """An Employee-role user sees only their own record, so another id is dropped; HR keeps any id."""
    self_user = _user_with_role("Employee", "self-user")
    own = ensure_ext(hired)
    own.user = self_user
    own.save()
    report = _report(("employee",))
    assert usable_filters(report, self_user, Filters(employee=left_employee.pk)).employee is None
    assert usable_filters(report, self_user, Filters(employee=hired.pk)).employee == hired.pk
    hr = _user_with_role("HR", "hr-check")
    assert usable_filters(report, hr, Filters(employee=left_employee.pk)).employee == left_employee.pk


def test_period_reset_when_filter_not_offered(db: None, hr_user: User) -> None:
    """HR has no view_salary, so a period that needs it is reset to the year default."""
    report = _report(("period",), {"period": "macs.view_salary"})
    f = usable_filters(report, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    assert (f.date_from, f.date_to) == (None, None)


def test_undeclared_filters_are_dropped(db: None, hr_user: User, hired: Employee) -> None:
    """A filter the report does not declare is reset, so no link carries it; columns, group and sort are kept."""
    f = usable_filters(STAFF_LIST, hr_user, Filters(employee=hired.pk, date_from=date(2020, 1, 1), reason=3))
    assert (f.employee, f.date_from, f.reason) == (None, None, None)
    f = usable_filters(MOVEMENTS, hr_user, Filters(gender="F", state="all"))
    assert (f.gender, f.state) == ("", "working")
    f = usable_filters(STAFF_LIST, hr_user, Filters(columns=("code",), group="", sort="-code"))
    assert (f.columns, f.sort) == (("code",), "-code")


def test_leave_filters_round_trip_and_garbage() -> None:
    q = "leave_type=3&leave_state=cancelled&absence_type=5"
    f = parse_filters(QueryDict(q))
    assert (f.leave_type, f.leave_state, f.absence_type) == (3, "cancelled", 5)
    assert to_query(f) == q
    assert parse_filters(QueryDict("leave_type=x&leave_state=nope&absence_type=-2")) == Filters()


def test_describe_names_the_leave_filters(db: None) -> None:
    leave_type = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    absence_type = AbsenceType.objects.create(name="Цагаар")
    assert describe(Filters(leave_state="mistake"), ("leave_state",)) == ["Төлөв: Буруу бүртгэсэн"]
    assert describe(Filters(leave_type=leave_type.pk), ("leave_type",)) == ["Төрөл: Ээлжийн амралт"]
    assert describe(Filters(absence_type=absence_type.pk), ("absence_type",)) == ["Төрөл: Цагаар"]
    assert describe(Filters(leave_type=999999, absence_type=999999), ("leave_type", "absence_type")) == [
        "Төрөл: —",
        "Төрөл: —",
    ]


def test_leave_filters_reset_on_a_report_that_does_not_declare_them(db: None, hr_user: User) -> None:
    """A report without the leave filters resets them, so no link carries them (as with the other filters)."""
    f = usable_filters(STAFF_LIST, hr_user, Filters(leave_type=3, leave_state="cancelled", absence_type=5))
    assert (f.leave_type, f.leave_state, f.absence_type) == (None, "", None)


def test_survey_filters_round_trip_and_garbage() -> None:
    year = timezone.localdate().year - 1  # not the current year, so it stays in the address
    q = f"age_from=60&age_to=70&attribute=marital&contact_type=3&year={year}"
    f = parse_filters(QueryDict(q))
    assert (f.age_from, f.age_to, f.attribute, f.contact_type, f.year) == (60, 70, "marital", 3, year)
    assert to_query(f) == q
    garbage = parse_filters(QueryDict("age_from=x&age_to=999&attribute=zzz&contact_type=-1&year=1"))
    assert garbage == Filters()


def test_year_of_this_year_is_left_out_of_the_address() -> None:
    assert to_query(Filters(year=timezone.localdate().year)) == ""


def test_describe_names_the_survey_filters(db: None) -> None:
    contact = ContactType.objects.create(name="Яаралтай холбоо")
    assert describe(Filters(age_from=60, age_to=70), ("age_range",)) == ["Нас: 60 – 70"]
    assert describe(Filters(age_from=60), ("age_range",)) == ["Нас: 60 – "]
    assert describe(Filters(), ("age_range", "attribute")) == ["Шинж: Хүйс"]
    assert describe(Filters(attribute="marital"), ("attribute",)) == ["Шинж: Гэрлэлтийн байдал"]
    assert describe(Filters(contact_type=contact.pk), ("contact_type",)) == ["Холбоо барих төрөл: Яаралтай холбоо"]
    assert describe(Filters(contact_type=999999), ("contact_type",)) == ["Холбоо барих төрөл: —"]
    assert describe(Filters(year=2025), ("year",)) == ["Он: 2025"]
    assert describe(Filters(), ("year",)) == [f"Он: {timezone.localdate().year}"]


def _this_quarter() -> int:
    return (timezone.localdate().month - 1) // 3 + 1


def test_phase5_filters_round_trip_and_order() -> None:
    other = 1 if _this_quarter() != 1 else 2  # a quarter that is not this one, so it stays in the address
    q = f"tr_type=2&quarter={other}&present_type=5"
    f = parse_filters(QueryDict(q))
    assert (f.tr_type, f.quarter, f.present_type) == (2, other, 5)
    assert to_query(f) == q


def test_phase5_filters_garbage_is_ignored() -> None:
    assert parse_filters(QueryDict("tr_type=9&quarter=9&present_type=-1")) == Filters()
    assert parse_filters(QueryDict("tr_type=x&quarter=0&present_type=")) == Filters()


def test_quarter_of_this_quarter_is_left_out_of_the_address() -> None:
    assert to_query(Filters(quarter=_this_quarter())) == ""


def test_describe_names_the_phase5_filters(db: None) -> None:
    present = PresentType.objects.create(name="Номын бэлэг")
    assert describe(Filters(tr_type=2), ("tr_type",)) == ["Хэлбэр: Гадаад"]
    assert describe(Filters(quarter=2), ("quarter",)) == ["Улирал: 2"]
    assert describe(Filters(), ("quarter",)) == [f"Улирал: {_this_quarter()}"]
    assert describe(Filters(present_type=present.pk), ("present_type",)) == ["Бэлгийн төрөл: Номын бэлэг"]
    assert describe(Filters(present_type=999999), ("present_type",)) == ["Бэлгийн төрөл: —"]

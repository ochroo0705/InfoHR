"""The leave list's rules as service calls: the filter cases of test_views.py and test_batches.py, without the page."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from employees.models import Employee
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveExt, LeaveTypeExt
from leave.services import calendar, ledger, records
from leave.services.list_page import banners, list_batch, parse_filter
from leave.services.records import Draft
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

TOO_BIG = str(2**31)  # one above the largest production id


@pytest.fixture
def two(actor: User, annual: LeaveTypeRow) -> tuple[Employee, Employee]:
    a = make_employee(actor, hired=date(2020, 3, 1), register_no="УБ11112233")
    a.family_name, a.given_name = "Ганбатын", "Сарантуяа"
    a.save()
    b = make_employee(actor, hired=date(2020, 3, 1), register_no="УБ22112233")
    b.family_name, b.given_name = "Дорждэрэмийн", "Болд"
    b.save()
    records.record(Draft(a, annual, date(2026, 11, 2), date(2026, 11, 3)), actor, date(2026, 10, 14))
    records.record(Draft(b, annual, date(2026, 11, 9), date(2026, 11, 10)), actor, date(2026, 10, 14))
    return a, b


@pytest.fixture
def viewer(db: None) -> User:
    """Can view leave but not employees: the only employee she may see is the one linked to her own login. This user
    has none, so the list shows her nobody."""
    user = User.objects.create_user("leave_viewer", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_leave", content_type__app_label="leave"))
    return User.objects.get(pk=user.pk)  # a fresh object, so no permission is cached from before


def _people(user: User, query: dict[str, str], offset: int = 0, size: int = 50) -> list[int]:
    """The employee ids of the rows one batch returns for `query`; the batch must hold them all."""
    found, more = list_batch(user, parse_filter(user, query), offset, size)
    assert not more
    return sorted(employee.pk for _, employee in found)


def test_every_word_must_match_name_or_code(actor: User, two: tuple[Employee, Employee]) -> None:
    a, _b = two
    assert _people(actor, {"q": "ГАН"}) == [a.pk]  # case ignored
    assert _people(actor, {"q": "Ганбатын Сарантуяа"}) == [a.pk]
    assert _people(actor, {"q": "Ганбатын Болд"}) == []  # the second word matches someone else


def test_blank_search_matches_everyone(actor: User, two: tuple[Employee, Employee]) -> None:
    a, b = two
    assert _people(actor, {"q": "   "}) == sorted([a.pk, b.pk])


def test_employee_link_shows_that_person_and_sets_the_search_text(actor: User, two: tuple[Employee, Employee]) -> None:
    a, _b = two
    assert _people(actor, {"employee": str(a.pk)}) == [a.pk]
    assert parse_filter(actor, {"employee": str(a.pk)}).q == "Ганбатын Сарантуяа"


def test_employee_link_to_someone_the_user_cannot_see_keeps_the_search_text(
    viewer: User, two: tuple[Employee, Employee]
) -> None:
    a, _b = two
    flt = parse_filter(viewer, {"employee": str(a.pk), "q": "Болд"})
    assert flt.q == "Болд"  # not replaced by the name of a person she may not see
    assert list_batch(viewer, flt, 0, 50) == ([], False)


def test_type_text_is_ignored(actor: User, two: tuple[Employee, Employee]) -> None:
    a, b = two
    assert parse_filter(actor, {"type": "abc"}).type_id is None
    assert _people(actor, {"type": "abc"}) == sorted([a.pk, b.pk])


def test_largest_id_is_accepted(actor: User) -> None:
    largest = 2**31 - 1
    assert parse_filter(actor, {"employee": str(largest)}).employee == largest
    assert _people(actor, {"employee": str(largest)}) == []  # accepted, but no such employee


@pytest.mark.parametrize("bad", ["abc", TOO_BIG, "99999999999"])
def test_bad_employee_id_is_ignored(actor: User, two: tuple[Employee, Employee], bad: str) -> None:
    a, b = two
    assert parse_filter(actor, {"employee": bad}).employee is None
    assert _people(actor, {"employee": bad}) == sorted([a.pk, b.pk])


def test_rows_of_people_outside_the_visible_set_never_appear(
    actor: User, viewer: User, two: tuple[Employee, Employee]
) -> None:
    a, b = two
    assert _people(actor, {}) == sorted([a.pk, b.pk])  # control: the admin sees both
    assert _people(viewer, {}) == []
    assert _people(viewer, {"q": "Сарантуяа"}) == []


def test_all_states_and_the_default_state(actor: User, annual: LeaveTypeRow, two: tuple[Employee, Employee]) -> None:
    a, _b = two
    LeaveAssign.objects.create(
        employee=a,
        leave_type=annual,
        date1=date(2026, 9, 1),
        date2=date(2026, 9, 2),
        status=LeaveAssign.CANCELLED,
        adays=2,
        comment="",
    )
    recorded, _ = list_batch(actor, parse_filter(actor, {}), 0, 50)
    everything, _ = list_batch(actor, parse_filter(actor, {"status": "all"}), 0, 50)
    assert len(recorded) == 2 and len(everything) == 3
    assert _people(actor, {"status": "cancelled"}) == [a.pk]


def test_mistake_and_rejected_states(actor: User, annual: LeaveTypeRow, two: tuple[Employee, Employee]) -> None:
    a, b = two
    cancelled = LeaveAssign.objects.create(
        employee=a,
        leave_type=annual,
        date1=date(2026, 9, 1),
        date2=date(2026, 9, 2),
        status=LeaveAssign.CANCELLED,
        adays=2,
        comment="",
    )
    LeaveExt.objects.create(assign=cancelled, mistake=True)  # a cancelled row marked as wrongly recorded
    LeaveAssign.objects.create(
        employee=b,
        leave_type=annual,
        date1=date(2026, 8, 1),
        date2=date(2026, 8, 2),
        status=LeaveAssign.REJECTED,
        adays=2,
        comment="",
    )
    assert _people(actor, {"status": "mistake"}) == [a.pk]
    assert _people(actor, {"status": "rejected"}) == [b.pk]


def test_unknown_status_matches_nothing(actor: User, two: tuple[Employee, Employee]) -> None:
    assert _people(actor, {"status": "garbage"}) == []


@pytest.mark.parametrize("query", [{"from": "garbage"}, {"to": "2026-13-01"}, {"from": "2026-02-30", "to": "nope"}])
def test_bad_dates_are_ignored(actor: User, two: tuple[Employee, Employee], query: dict[str, str]) -> None:
    flt = parse_filter(actor, query)
    assert flt.start is None and flt.end is None
    assert len(list_batch(actor, flt, 0, 50)[0]) == 2


def test_dates_are_applied_as_a_range(actor: User, two: tuple[Employee, Employee]) -> None:
    a, _b = two
    assert _people(actor, {"from": "2026-11-01", "to": "2026-11-05"}) == [a.pk]
    assert _people(actor, {"from": "2026-11-09", "to": "2026-11-02"}) == []  # from after to: nothing fits


def test_type_filter(actor: User, annual: LeaveTypeRow, sick: LeaveTypeRow, two: tuple[Employee, Employee]) -> None:
    a, b = two
    assert _people(actor, {"type": str(annual.pk)}) == sorted([a.pk, b.pk])
    assert _people(actor, {"type": str(sick.pk)}) == []


def test_a_batch_reports_when_more_rows_follow(actor: User, two: tuple[Employee, Employee]) -> None:
    flt = parse_filter(actor, {})
    first, more = list_batch(actor, flt, 0, 1)
    assert len(first) == 1 and more
    second, more = list_batch(actor, flt, 1, 1)
    assert len(second) == 1 and not more
    assert first[0][0].id != second[0][0].id


def test_banners_list_the_current_year_with_no_holidays(monkeypatch: pytest.MonkeyPatch, annual: LeaveTypeRow) -> None:
    monkeypatch.setattr(calendar, "has_holidays", lambda year: False)
    assert banners(date(2026, 10, 14)) == ("", [2026])


def test_banners_list_next_year_only_in_december(monkeypatch: pytest.MonkeyPatch, annual: LeaveTypeRow) -> None:
    monkeypatch.setattr(calendar, "has_holidays", lambda year: False)
    assert banners(date(2026, 12, 5)) == ("", [2026, 2027])


def test_no_banner_when_holidays_are_set(monkeypatch: pytest.MonkeyPatch, annual: LeaveTypeRow) -> None:
    monkeypatch.setattr(calendar, "has_holidays", lambda year: True)
    assert banners(date(2026, 12, 5)) == ("", [])


def test_banner_text_when_the_annual_type_is_not_set(annual: LeaveTypeRow) -> None:
    LeaveTypeExt.objects.all().delete()  # no type uses the annual balance
    assert ledger.annual_configured() is False
    not_configured, _missing = banners(date(2026, 10, 14))
    assert not_configured == ledger.NOT_CONFIGURED


def test_annual_configured_means_no_banner_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "annual_configured", lambda: True)
    assert banners(date(2026, 10, 14))[0] == ""

import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from lists.registry import LISTS
from macs.models import FiredReason
from reports.registry import REPORTS, can_open

from employees import palette
from employees.models import Employee, EmployeeExt, HrOrder, OrderState, OrderType, ensure_ext
from employees.services import history
from employees.templatetags.palette_extras import hl

from .conftest import hire_values, link_login, named
from .helpers import record_signed

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _user(role: str, name: str = "t1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


@pytest.fixture
def listed(hired: Employee) -> Employee:
    """The hired employee with an HR row, so the palette (like the employee list) can find them."""
    ensure_ext(hired)
    return hired


def _hire(actor: User, job_values: dict[str, Any], register_no: str, family: str, given: str) -> Employee:
    values = hire_values(register_no) | {"family_name": family, "given_name": given}
    emp = history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)
    ensure_ext(emp)
    return emp


def test_screens_with_empty_query_list_every_allowed_screen(listed: Employee) -> None:
    hr = _user("HR", "pal_hr")
    titles = [s.title for s in palette.screens(hr, "")]
    expected = [
        "Өнөөдөр",
        "Ажилтнууд",
        "Тушаалын бүртгэл",
        "Чөлөө, амралт",
        "Багийн хуанли",
        "Амралтын үлдэгдэл",
        "Тайлан",
    ]
    if hr.has_perm("lists.manage_lists"):
        expected.append("Жагсаалтууд")
    assert titles == expected
    assert ("Жагсаалтууд" in titles) == hr.has_perm("lists.manage_lists")


def test_screens_hide_what_the_user_may_not_open(listed: Employee) -> None:
    emp = _user("Employee", "pal_emp")
    titles = [s.title for s in palette.screens(emp, "")]
    assert "Өнөөдөр" in titles
    assert "Тушаалын бүртгэл" not in titles
    assert "Жагсаалтууд" not in titles
    assert "Тайлан" not in titles


def test_screens_match_typed_words_case_insensitively(listed: Employee) -> None:
    hr = _user("HR", "pal_hr2")
    assert palette.screens(hr, "ХУАНЛИ") == [palette.Screen("Багийн хуанли", reverse("leave:calendar"))]
    assert palette.screens(hr, "багийн ХУАНЛИ") == [palette.Screen("Багийн хуанли", reverse("leave:calendar"))]
    assert palette.screens(hr, "хуанли чөлөө") == []  # every word must match


def test_reports_are_found_by_a_word_of_their_title(listed: Employee) -> None:
    hr = _user("HR", "pal_rep1")
    found = palette.screens(hr, "мэдээлэл")
    assert [s for s in found if s.title.startswith("Тайлан · ")] == [
        palette.Screen("Тайлан · Ажилчдын мэдээлэл", reverse("reports:report", args=["employee-info"]))
    ]
    assert reverse("reports:report", args=["employee-info"]) == "/reports/employee-info/"


def test_reports_are_not_listed_for_an_empty_query(listed: Employee) -> None:
    hr = _user("HR", "pal_rep2")
    titles = [s.title for s in palette.screens(hr, "")]
    assert not any(t.startswith("Тайлан · ") for t in titles)
    fixed = [perm for _, _, perm in palette._CATALOGUE if not perm or hr.has_perm(perm)]
    assert len(titles) == len(fixed)  # only the short menu of fixed screens


def test_typing_tailan_finds_the_catalogue_and_only_reports_with_the_word_in_their_title(listed: Employee) -> None:
    hr = _user("HR", "pal_rep3")
    found = palette.screens(hr, "тайлан")
    assert palette.Screen("Тайлан", reverse("reports:catalogue")) in found
    reports = [s.title for s in found if s.title.startswith("Тайлан · ")]
    assert reports  # some report titles end in «тайлан», so they are found by their own title
    assert all("тайлан" in t.removeprefix("Тайлан · ").casefold() for t in reports)
    assert "Тайлан · Ажилчдын мэдээлэл" not in reports  # the «Тайлан · » prefix is not searched


def test_a_user_without_report_access_finds_no_reports(listed: Employee) -> None:
    emp = _user("Employee", "pal_rep4")
    assert palette.screens(emp, "мэдээлэл") == []


def test_a_report_needing_a_permission_the_user_lacks_is_not_found(listed: Employee) -> None:
    hr = _user("HR", "pal_rep5")  # HR has no macs.view_salary
    accountant = _user("Accountant", "pal_rep6")  # the Accountant role has it
    assert REPORTS["household-income"].needs == ("macs.view_employees", "macs.view_salary")
    title = "Тайлан · Өрхийн амьжиргааны баталгаажих түвшний тайлан"
    assert title not in [s.title for s in palette.screens(hr, "амьжиргааны")]
    assert title in [s.title for s in palette.screens(accountant, "амьжиргааны")]


def test_at_most_eight_reports_are_listed(listed: Employee) -> None:
    hr = _user("HR", "pal_rep7")
    matching = [r for r in REPORTS.values() if "а" in r.title.casefold() and can_open(hr, r)]
    assert len(matching) > 8  # the letter really matches more reports than the limit
    found = palette.screens(hr, "а")
    assert sum(1 for s in found if s.title.startswith("Тайлан · ")) == 8


def test_lists_are_found_by_a_word_of_their_label(listed: Employee) -> None:
    hr = _user("HR", "pal_list1")
    found = palette.screens(hr, "боловсрол")
    assert palette.Screen("Жагсаалт · Боловсрол", reverse("lists:list", args=["education"])) in found
    assert reverse("lists:list", args=["education"]) == "/lists/education/"


def test_lists_are_not_found_by_a_user_without_list_access(listed: Employee) -> None:
    accountant = _user("Accountant", "pal_list2")  # the Accountant role lacks lists.manage_lists
    assert not accountant.has_perm("lists.manage_lists")
    found = palette.screens(accountant, "боловсрол")
    assert not [s for s in found if s.title.startswith("Жагсаалт · ")]


def test_lists_and_deep_pages_are_not_listed_for_an_empty_query(listed: Employee) -> None:
    hr = _user("HR", "pal_list3")
    titles = [s.title for s in palette.screens(hr, "")]
    assert not any(t.startswith(("Жагсаалт · ", "Тайлан · ")) for t in titles)
    assert not {"Ажилтан нэмэх", "Баярын өдрүүд", "Амралтын төрөл, тохиргоо"} & set(titles)
    fixed = [perm for _, _, perm in palette._CATALOGUE if not perm or hr.has_perm(perm)]
    assert len(titles) == len(fixed)  # only the short menu of fixed screens


def test_at_most_eight_lists_are_listed(listed: Employee) -> None:
    hr = _user("HR", "pal_list4")
    matching = [s for s in LISTS.values() if "а" in s.label.casefold()]
    assert len(matching) > 8  # the letter really matches more lists than the limit
    found = palette.screens(hr, "а")
    assert sum(1 for s in found if s.title.startswith("Жагсаалт · ")) == 8


def test_add_employee_is_found_by_a_word_only_for_those_who_may_add(listed: Employee) -> None:
    hr = _user("HR", "pal_deep1")
    accountant = _user("Accountant", "pal_deep2")  # the Accountant role lacks macs.manage_employees
    assert reverse("employees:add") == "/employees/new/"
    assert palette.Action("Ажилтан нэмэх", reverse("employees:add"), False) in palette.actions(hr, "нэмэх")
    assert "Ажилтан нэмэх" not in [a.title for a in palette.actions(accountant, "нэмэх")]
    assert "Ажилтан нэмэх" not in [s.title for s in palette.screens(hr, "нэмэх")]  # a quick action, not a deep page


def test_actions_with_empty_query_list_both_in_order(listed: Employee) -> None:
    hr = _user("HR", "pal_act1")
    assert hr.has_perm("leave.record_leave") and hr.has_perm("leave.view_leave")
    assert hr.has_perm("macs.manage_employees")
    assert reverse("leave:add") == "/leave/new/"
    assert palette.actions(hr, "") == [
        palette.Action("Чөлөө бүртгэх", "/leave/new/", True),
        palette.Action("Ажилтан нэмэх", "/employees/new/", False),
        palette.Action("Тушаалын бүртгэл хэвлэх", reverse("employees:orders_print"), False),
        palette.Action("Нууц үг солих", reverse("password_change"), False),
    ]


def test_actions_hide_what_the_user_may_not_use(listed: Employee) -> None:
    accountant = _user("Accountant", "pal_act2")  # no record_leave and no manage_employees
    employee = _user("Employee", "pal_act3")  # no rights at all
    # The password change needs only a login, so it is listed for everyone who is signed in.
    assert [a.title for a in palette.actions(accountant, "")] == ["Тушаалын бүртгэл хэвлэх", "Нууц үг солих"]
    assert [a.title for a in palette.actions(employee, "")] == ["Нууц үг солих"]  # no order register for Employee


def test_leave_action_needs_both_record_and_view_leave(listed: Employee) -> None:
    """Record without view is not enough: the leave form itself asks for both (leave/access.py can_record)."""
    lonely = User.objects.create_user("pal_act4", password="x-long-pass-123")  # noqa: S106
    lonely.user_permissions.add(Permission.objects.get(codename="record_leave", content_type__app_label="leave"))
    assert lonely.has_perm("leave.record_leave") and not lonely.has_perm("leave.view_leave")
    assert "Чөлөө бүртгэх" not in [a.title for a in palette.actions(lonely, "")]
    assert [a.title for a in palette.actions(lonely, "")] == ["Нууц үг солих"]


def test_actions_match_typed_words(listed: Employee) -> None:
    hr = _user("HR", "pal_act5")
    assert palette.actions(hr, "бүртгэх") == [palette.Action("Чөлөө бүртгэх", reverse("leave:add"), True)]
    assert palette.actions(hr, "НЭМЭХ") == [palette.Action("Ажилтан нэмэх", reverse("employees:add"), False)]
    assert palette.actions(hr, "zzzz") == []
    assert palette.actions(hr, "бүртгэх нэмэх") == []  # every word must match


def test_inactive_user_gets_no_actions(listed: Employee) -> None:
    hr = _user("HR", "pal_act6")
    hr.is_active = False
    hr.save(update_fields=["is_active"])
    assert palette.actions(hr, "") == []
    assert palette.actions(hr, "нэмэх") == []


def test_leave_setup_pages_are_found_by_a_word_only_for_admin(listed: Employee) -> None:
    admin = _user("Admin", "pal_deep3")
    hr = _user("HR", "pal_deep4")  # leave settings and holidays are Admin only
    assert palette.Screen("Амралтын төрөл, тохиргоо", reverse("leave:settings")) in palette.screens(admin, "тохиргоо")
    assert palette.Screen("Баярын өдрүүд", reverse("leave:holidays")) in palette.screens(admin, "баярын")
    assert "Амралтын төрөл, тохиргоо" not in [s.title for s in palette.screens(hr, "тохиргоо")]
    assert "Баярын өдрүүд" not in [s.title for s in palette.screens(hr, "баярын")]


def test_the_list_prefix_is_not_searched(listed: Employee) -> None:
    hr = _user("HR", "pal_list5")
    found = palette.screens(hr, "жагсаалт")
    assert not [s for s in found if s.title.startswith("Жагсаалт · ")]
    assert palette.Screen("Жагсаалтууд", reverse("lists:index")) in found  # the fixed screen still matches


def test_people_empty_query_returns_nothing(listed: Employee) -> None:
    hr = _user("HR", "pal_hr3")
    assert palette.people(hr, "  ", TODAY) == []
    assert palette.people(hr, "", TODAY) == []
    assert [h.employee.pk for h in palette.people(hr, "Батын", TODAY)] == [listed.pk]  # the control query works


def test_people_match_every_word_on_name_or_code(listed: Employee) -> None:
    hr = _user("HR", "pal_hr4")
    assert listed.code
    for query in ("Батын", "Сараа", "Сараа Батын", "Батын Сараа", listed.code):
        assert [h.employee.pk for h in palette.people(hr, query, TODAY)] == [listed.pk], query
    assert palette.people(hr, "Батын Ганзориг", TODAY) == []
    assert palette.people(hr, "Ганзориг", TODAY) == []


def test_people_match_in_other_letter_case(listed: Employee) -> None:
    hr = _user("HR", "pal_hr5")
    assert listed.family_name and listed.given_name  # the model allows None; the fixture always sets both
    assert [h.employee.pk for h in palette.people(hr, listed.family_name.upper(), TODAY)] == [listed.pk]
    assert [h.employee.pk for h in palette.people(hr, listed.given_name.lower(), TODAY)] == [listed.pk]


def test_people_wildcards_are_literal(listed: Employee) -> None:
    hr = _user("HR", "pal_hr6")
    assert [h.employee.pk for h in palette.people(hr, "Батын", TODAY)] == [listed.pk]  # the control query works
    assert palette.people(hr, "%", TODAY) == []
    assert palette.people(hr, "_", TODAY) == []
    assert palette.people(hr, "Бат%", TODAY) == []


def test_people_query_is_cut_to_100_chars(listed: Employee) -> None:
    hr = _user("HR", "pal_hr7")
    assert palette.people(hr, "а" * 5000, TODAY) == []
    # "Батын" then 99 spaces then "zzz": the cut at 100 characters drops "zzz", so the family name alone matches
    assert [h.employee.pk for h in palette.people(hr, "Батын" + " " * 99 + "zzz", TODAY)] == [listed.pk]


def test_people_only_include_employees_hr_has_touched(actor: User, job_values: dict[str, Any]) -> None:
    """Like the employee list: a person with no HR row is not searched, even by an HR user."""
    emp = history.hire(
        hire_values("УБ99112255") | {"family_name": "Нуудэл"},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
    )
    EmployeeExt.objects.filter(employee=emp).delete()  # history.hire writes the HR row; drop it to model "not touched"
    hr = _user("HR", "pal_hr11")
    assert palette.people(hr, "Нуудэл", TODAY) == []
    ensure_ext(emp)
    assert [h.employee.pk for h in palette.people(hr, "Нуудэл", TODAY)] == [emp.pk]


def test_people_respect_access(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    other = _hire(actor, job_values, "УБ99112234", "Ганбат", "Бат")
    hr = _user("HR", "pal_hr8")
    assert [h.employee.pk for h in palette.people(hr, "Ганбат", TODAY)] == [other.pk]  # HR can find them

    emp = _user("Employee", "pal_emp2")
    link_login(listed, emp)
    assert [h.employee.pk for h in palette.people(emp, "Батын", TODAY)] == [listed.pk]
    assert palette.people(emp, "Ганбат", TODAY) == []


def test_people_mark_leavers(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    leaver = _hire(actor, job_values, "УБ99112244", "Цэвэг", "Нараа")
    record_signed(
        leaver,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    hr = _user("HR", "pal_hr9")
    (gone,) = palette.people(hr, "Цэвэг", TODAY)
    assert gone.employee.pk == leaver.pk
    assert gone.left is True
    (here,) = palette.people(hr, "Батын", TODAY)
    assert here.left is False


def test_people_are_limited_to_eight(actor: User, job_values: dict[str, Any]) -> None:
    for i in range(9):
        _hire(actor, job_values, f"УБ{99130000 + i:08d}", "Олон", f"Нэр{i}")
    assert Employee.objects.filter(family_name="Олон").count() == 9
    hr = _user("HR", "pal_hr10")
    assert len(palette.people(hr, "Олон", TODAY)) == palette.PEOPLE_LIMIT == 8


def test_people_do_not_match_phone_or_register_no(actor: User, job_values: dict[str, Any]) -> None:
    """Deliberate difference from the employee list, which also matches phone and register number."""
    emp = history.hire(
        hire_values("УБ99887766") | {"family_name": "Тэмүүлэн", "work_phone": "97775544"},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
    )
    ensure_ext(emp)
    emp.refresh_from_db()
    assert emp.work_phone and emp.register_no  # the digits really are stored, so the negatives mean something
    hr = _user("HR", "pal_hr12")
    assert [h.employee.pk for h in palette.people(hr, "Тэмүүлэн", TODAY)] == [emp.pk]  # control
    assert palette.people(hr, emp.work_phone, TODAY) == []
    assert palette.people(hr, emp.register_no, TODAY) == []
    assert palette.people(hr, "99887766", TODAY) == []


def test_people_order_by_name_and_limit_to_eight_together(actor: User, job_values: dict[str, Any]) -> None:
    """Created in reverse, so insertion order differs from name order: the first eight by pk would be wrong."""
    for i in reversed(range(9)):
        _hire(actor, job_values, f"УБ{99140000 + i:08d}", "Дараалал", f"Нэр{i}")
    hr = _user("HR", "pal_hr13")
    names = [h.employee.given_name for h in palette.people(hr, "Дараалал", TODAY)]
    assert names == [f"Нэр{i}" for i in range(8)]


def test_people_order_by_family_name_then_given_name(actor: User, job_values: dict[str, Any]) -> None:
    """Created in an order that differs from the expected result, so a missing order_by shows."""
    _hire(actor, job_values, "УБ99150001", "Баяр", "Жишээ Алтан")
    _hire(actor, job_values, "УБ99150002", "Аюуш", "Жишээ Цэцэг")
    _hire(actor, job_values, "УБ99150003", "Аюуш", "Жишээ Болд")
    hr = _user("HR", "pal_hr14")
    found = [(h.employee.family_name, h.employee.given_name) for h in palette.people(hr, "Жишээ", TODAY)]
    assert found == [("Аюуш", "Жишээ Болд"), ("Аюуш", "Жишээ Цэцэг"), ("Баяр", "Жишээ Алтан")]


def test_inactive_user_gets_nothing(listed: Employee) -> None:
    hr = _user("HR", "pal_hr15")
    hr.is_active = False
    hr.save(update_fields=["is_active"])
    assert palette.screens(hr, "") == []
    assert palette.people(hr, "Батын", TODAY) == []


# --- Folding: ө is read as о and ү as у, in typed words and in every title and name searched ---


def test_people_fold_mongolian_o_and_u(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values, "УБ99160001", "Өнөрболд", "Түмэн")
    hr = _user("HR", "pal_fold1")
    assert [h.employee.pk for h in palette.people(hr, "Өнөрболд", TODAY)] == [emp.pk]  # control
    assert [h.employee.pk for h in palette.people(hr, "онорболд", TODAY)] == [emp.pk]  # ө typed as о
    assert [h.employee.pk for h in palette.people(hr, "тумэн", TODAY)] == [emp.pk]  # ү typed as у
    assert [h.employee.pk for h in palette.people(hr, "ТҮМЭН ОНӨРБОЛД", TODAY)] == [emp.pk]  # both, two words


def test_titles_fold_mongolian_o_and_u(listed: Employee) -> None:
    admin = _user("Admin", "pal_fold2")
    hr = _user("HR", "pal_fold3")
    balances = palette.Screen("Амралтын үлдэгдэл", reverse("leave:balances"))
    assert balances in palette.screens(hr, "үлдэгдэл")  # the title's ү, typed as ү
    assert balances in palette.screens(hr, "улдэгдэл")  # typed as у
    holidays = palette.Screen("Баярын өдрүүд", reverse("leave:holidays"))
    assert holidays in palette.screens(admin, "баярын одрүүд")  # typed as о
    action = palette.Action("Нууц үг солих", reverse("password_change"), False)
    assert action in palette.actions(hr, "уу уг")  # the action title's ү and ө, typed as у and о


# --- Ranking: better matches first, inside each group; the old order breaks ties ---


def test_screens_rank_a_title_that_starts_with_the_word_before_one_that_contains_it(listed: Employee) -> None:
    hr = _user("HR", "pal_rank1")
    titles = [s.title for s in palette.screens(hr, "амрал")]
    assert titles[:2] == ["Амралтын үлдэгдэл", "Чөлөө, амралт"]  # same group: starts-with first


def test_people_rank_starts_with_before_contains_then_name_order(actor: User, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, "УБ99161001", "Абатай", "Нэр")  # «бат» inside the family name
    _hire(actor, job_values, "УБ99161002", "Батбаяр", "Нэр")  # starts with «бат»
    hr = _user("HR", "pal_rank2")
    families = [h.employee.family_name for h in palette.people(hr, "бат", TODAY)]
    assert families == ["Батбаяр", "Абатай"]  # the plain name order would put Абатай first


def test_people_rank_exact_code_first(actor: User, job_values: dict[str, Any]) -> None:
    starts = _hire(actor, job_values, "УБ99161003", "ZX100X", "Нэр")  # family starts with the code
    exact = _hire(actor, job_values, "УБ99161004", "Яс", "Нэр")
    Employee.objects.filter(pk=exact.pk).update(code="ZX100")
    hr = _user("HR", "pal_rank3")
    found = [h.employee.pk for h in palette.people(hr, "zx100", TODAY)]
    assert found == [exact.pk, starts.pk]  # the code match first, even though its name sorts later


def test_people_query_count_does_not_grow_with_more_candidates(actor: User, job_values: dict[str, Any]) -> None:
    """Candidates past the limit cost nothing: the same eight people are shown, so the same queries run."""
    for i in range(8):
        _hire(actor, job_values, f"УБ{99170000 + i:08d}", "Тоолол", f"Нэр{i}")
    hr = _user("HR", "pal_rank4")
    palette.people(hr, "Тоолол", TODAY)  # warm-up: the user's permissions are loaded once, on first use
    with CaptureQueriesContext(connection) as few:
        assert len(palette.people(hr, "Тоолол", TODAY)) == 8
    for i in range(8, 12):
        _hire(actor, job_values, f"УБ{99170000 + i:08d}", "Тоолол", f"Нэр{i}")
    with CaptureQueriesContext(connection) as many:
        assert len(palette.people(hr, "Тоолол", TODAY)) == 8
    assert len(many.captured_queries) == len(few.captured_queries)


# --- The two new quick actions ---


def test_password_change_and_print_orders_are_found_by_a_word(listed: Employee) -> None:
    hr = _user("HR", "pal_act7")
    assert palette.actions(hr, "нууц") == [palette.Action("Нууц үг солих", reverse("password_change"), False)]
    assert palette.actions(hr, "хэвлэх") == [
        palette.Action("Тушаалын бүртгэл хэвлэх", reverse("employees:orders_print"), False)
    ]
    assert reverse("password_change") == "/password/change/"
    assert reverse("employees:orders_print") == "/employees/orders/print/"


# --- The HTTP endpoint: GET /employees/palette/?q=… (the fragment the palette script fetches) ---


def test_palette_needs_login(client: Client, listed: Employee) -> None:
    response = client.get(reverse("employees:palette"))
    assert response.status_code == 302


def test_palette_without_query_lists_screens_only(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v1"))
    response = client.get(reverse("employees:palette"))
    body = response.content.decode()
    assert response.status_code == 200
    assert "data-palette-item" in body
    assert "Хуудас" in body
    assert "Хүмүүс" not in body


def test_palette_finds_a_person_and_links_to_the_record(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v2"))
    assert listed.family_name  # the model allows None; the fixture always sets it
    response = client.get(reverse("employees:palette"), {"q": listed.family_name})
    body = response.content.decode()
    assert "Хүмүүс" in body
    assert f'href="/employees/{listed.pk}/"' in body


def test_palette_marks_leavers(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    leaver = _hire(actor, job_values, "УБ99112299", "Цэвэг", "Нараа")
    record_signed(
        leaver,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    client.force_login(_user("HR", "pal_v3"))
    response = client.get(reverse("employees:palette"), {"q": "Цэвэг"})
    body = response.content.decode()
    assert f'href="/employees/{leaver.pk}/"' in body
    assert "Гарсан" in body


def test_palette_nothing_found(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v4"))
    response = client.get(reverse("employees:palette"), {"q": "zzzz"})
    body = response.content.decode()
    assert "data-palette-empty" in body
    assert "Юу ч олдсонгүй" in body


def _anchor(body: str, href: str) -> str:
    """The opening <a> tag of the palette answer that links to href ("" when there is none)."""
    tags = [tag for tag in re.findall(r"<a [^>]*>", body) if f'href="{href}"' in tag]
    return tags[0] if tags else ""


def test_palette_lists_quick_actions_after_screens(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v8"))
    body = client.get(reverse("employees:palette")).content.decode()
    assert "Үйлдэл" in body
    assert body.index("Хуудас") < body.index("Үйлдэл")
    leave = _anchor(body, "/leave/new/")
    assert "data-palette-item" in leave and "data-palette-modal" in leave  # opens as a pop-up
    hire = _anchor(body, "/employees/new/")
    assert "data-palette-item" in hire and "data-palette-modal" not in hire  # a page


def test_palette_empty_box_still_starts_with_the_first_screen(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v10"))
    body = client.get(reverse("employees:palette")).content.decode()
    first = re.findall(r"<a [^>]*data-palette-item[^>]*>", body)[0]
    assert f'href="{reverse("employees:today")}"' in first  # Ctrl+K then Enter still opens «Өнөөдөр»


def test_palette_action_alone_is_not_an_empty_answer(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v9"))
    body = client.get(reverse("employees:palette"), {"q": "бүртгэх"}).content.decode()
    assert "Үйлдэл" in body
    assert "data-palette-empty" not in body


def test_palette_nothing_found_has_no_actions(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v11"))
    body = client.get(reverse("employees:palette"), {"q": "zzzzqq"}).content.decode()
    assert "data-palette-empty" in body
    assert "Үйлдэл" not in body


def test_palette_hides_other_people_from_a_plain_employee(
    client: Client, listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    """Review Focus 5: an employee searching a colleague's name must not learn the colleague's record link."""
    emp = _user("Employee", "pal_v5")
    link_login(listed, emp)
    other = _hire(actor, job_values, "УБ99112235", "Ганбат", "Бат")
    client.force_login(emp)
    own = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert f'href="/employees/{listed.pk}/"' in own  # control: the own record is found
    body = client.get(reverse("employees:palette"), {"q": "Ганбат"}).content.decode()
    assert f"/employees/{other.pk}/" not in body


def test_palette_rejects_post(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v6"))
    response = client.post(reverse("employees:palette"), {"q": "Батын"})
    assert response.status_code == 405


def test_palette_is_not_cached(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_v7"))
    response = client.get(reverse("employees:palette"), {"q": "Батын"})
    assert "no-store" in response["Cache-Control"]


# --- The pop-up in base.html: signed-in pages only ---


def test_base_has_the_palette_for_signed_in_users(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_base1"))
    body = client.get(reverse("employees:today")).content.decode()
    assert "data-palette-open" in body
    assert 'id="palette-template"' in body
    assert "palette.js" in body
    # The shell must sit only inside the template: a shell in the page locks the scroll of every page (UI_RULES §6).
    outside = re.sub(r'<template id="palette-template".*?</template>', "", body, flags=re.DOTALL)
    assert outside != body  # the template really is there to strip
    assert "fixed inset-0 z-50" not in outside


def test_login_page_has_no_palette(client: Client) -> None:
    body = client.get(reverse("login")).content.decode()
    assert "data-palette-open" not in body
    assert "palette-template" not in body


# --- Rows show the position and department; a typed word matches them too (folded, ranked last) ---


def test_person_rows_carry_position_and_department(listed: Employee) -> None:
    hr = _user("HR", "pal_row1")
    (hit,) = palette.people(hr, "Батын", TODAY)
    assert hit.position == "Нягтлан"  # the job the list shows: job_values in conftest
    assert hit.department == "Санхүү"


def test_position_and_department_are_searched_folded(listed: Employee) -> None:
    hr = _user("HR", "pal_row2")
    for query in ("нягтлан", "Нягтлан", "санхүү", "санхуу", "нягтлан батын", "батын санхүү"):
        assert [h.employee.pk for h in palette.people(hr, query, TODAY)] == [listed.pk], query
    assert palette.people(hr, "нягтлан хүний", TODAY) == []  # every word must match somewhere


def test_position_match_ranks_after_a_name_match(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, "УБ99180001", "Нягтланов", "Болд")  # family name starts with the typed word
    hr = _user("HR", "pal_row3")
    found = [h.employee.family_name for h in palette.people(hr, "нягтлан", TODAY)]
    assert found == ["Нягтланов", "Батын"]  # Батын matches only by position: it ranks last


def test_position_match_finds_only_people_the_user_may_see(
    listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    _hire(actor, job_values, "УБ99180002", "Ганбат", "Бат")  # also a Нягтлан, but not the user's own record
    emp = _user("Employee", "pal_row4")
    link_login(listed, emp)
    assert [h.employee.pk for h in palette.people(emp, "нягтлан", TODAY)] == [listed.pk]


def test_position_hits_do_not_add_queries(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    """The same queries whether one person or several are shown: the names are read in bulk, not per person."""
    hr = _user("HR", "pal_row5")
    palette.people(hr, "санхүү", TODAY)  # warm-up: permissions are loaded once
    with CaptureQueriesContext(connection) as few:
        one = palette.people(hr, "санхүү", TODAY)
    for i in range(3):
        _hire(actor, job_values, f"УБ{99181000 + i:08d}", "Нэмэх", f"Нэр{i}")
    with CaptureQueriesContext(connection) as many:
        several = palette.people(hr, "санхүү", TODAY)
    assert len(one) == 1 and len(several) == 4
    assert len(many.captured_queries) == len(few.captured_queries)


# --- Person actions: only for a single match, only with the rights, never for a person who has left ---


def _perm(codename: str, app: str) -> Permission:
    return Permission.objects.get(codename=codename, content_type__app_label=app)


def test_single_match_offers_leave_and_contract_actions(listed: Employee) -> None:
    hr = _user("HR", "pal_pa1")
    (hit,) = palette.people(hr, "Батын", TODAY)
    assert palette.person_actions(hr, hit) == [
        palette.Action("Чөлөө бүртгэх", f"/leave/new/?employee={listed.pk}", True),
        palette.Action("Гэрээ сунгах / өөрчлөх", f"/employees/{listed.pk}/event/contract/", True),
    ]


def test_person_actions_follow_the_rights(listed: Employee) -> None:
    (hit,) = palette.people(_user("HR", "pal_pa2"), "Батын", TODAY)
    leave_only = _user("Employee", "pal_pa3")
    leave_only.user_permissions.add(_perm("record_leave", "leave"), _perm("view_leave", "leave"))
    contract_only = _user("Employee", "pal_pa4")
    contract_only.user_permissions.add(_perm("manage_employees", "macs"))
    nobody = _user("Employee", "pal_pa5")
    assert [a.title for a in palette.person_actions(leave_only, hit)] == ["Чөлөө бүртгэх"]
    assert [a.title for a in palette.person_actions(contract_only, hit)] == ["Гэрээ сунгах / өөрчлөх"]
    assert palette.person_actions(nobody, hit) == []


def test_no_person_actions_for_a_left_person(actor: User, job_values: dict[str, Any]) -> None:
    leaver = _hire(actor, job_values, "УБ99112288", "Цэвэг", "Нараа")
    record_signed(
        leaver,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    hr = _user("HR", "pal_pa6")
    (hit,) = palette.people(hr, "Цэвэг", TODAY)
    assert palette.person_actions(hr, hit) == []


def test_palette_shows_person_actions_under_a_single_person(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_pa7"))
    body = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert f"Үйлдэл · {listed.full_name}" in body
    assert body.index("Хүмүүс") < body.index("Үйлдэл · ")  # right after the person row
    leave = _anchor(body, f"/leave/new/?employee={listed.pk}")
    assert "data-palette-item" in leave and "data-palette-modal" in leave  # the leave pop-up, with the employee
    contract = _anchor(body, f"/employees/{listed.pk}/event/contract/")
    assert "data-palette-item" in contract and "data-palette-modal" in contract  # the contract pop-up


def test_palette_shows_no_person_actions_for_several_matches(
    client: Client, listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    _hire(actor, job_values, "УБ99190001", "Батын", "Болд")
    client.force_login(_user("HR", "pal_pa8"))
    body = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert "Хүмүүс" in body
    assert "Үйлдэл · " not in body
    assert f"?employee={listed.pk}" not in body


def test_palette_shows_no_person_actions_for_a_left_person(
    client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    leaver = _hire(actor, job_values, "УБ99112289", "Цэвэг", "Нараа")
    record_signed(
        leaver,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    client.force_login(_user("HR", "pal_pa9"))
    body = client.get(reverse("employees:palette"), {"q": "Цэвэг"}).content.decode()
    assert f'href="/employees/{leaver.pk}/"' in body
    assert "Үйлдэл · " not in body


def test_contract_action_opens_as_a_pop_up_over_htmx(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_pa10"))
    url = reverse("employees:event", args=[listed.pk, "contract"])
    response = client.get(url, HTTP_HX_REQUEST="true")  # what the palette's htmx call sends
    assert response.status_code == 200
    assert "fixed inset-0 z-50" in response.content.decode()  # the pop-up shell


def test_leave_action_opens_with_the_employee_chosen(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_pa11"))
    response = client.get(f"{reverse('leave:add')}?employee={listed.pk}", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert f'value="{listed.pk}" selected' in response.content.decode()


# --- Recent items: the empty box shows what the user opened last (the browser sends short refs, the server checks) ---


def _recent_body(client: Client, recent: str, q: str = "") -> str:
    return client.get(reverse("employees:palette"), {"q": q, "recent": recent}).content.decode()


def test_recent_resolves_people_and_pages_in_the_sent_order(listed: Employee) -> None:
    hr = _user("HR", "pal_rec1")
    refs = [f"s:{reverse('employees:today')}", f"p:{listed.pk}"]
    found = palette.recent(hr, refs, TODAY)
    assert [r.ref for r in found] == refs
    assert found[0].title == "Өнөөдөр" and found[0].url == reverse("employees:today")
    assert found[0].person is None
    assert found[1].title == listed.full_name and found[1].url == f"/employees/{listed.pk}/"
    assert found[1].person is not None and found[1].person.employee.pk == listed.pk
    assert palette.recent(hr, [f"p:{listed.pk}", refs[0]], TODAY)[0].ref == f"p:{listed.pk}"  # order kept


def test_recent_drops_a_person_the_user_may_not_see(listed: Employee, actor: User, job_values: dict[str, Any]) -> None:
    other = _hire(actor, job_values, "УБ99200001", "Хориотой", "Бат")
    emp = _user("Employee", "pal_rec2")
    link_login(listed, emp)
    assert [r.ref for r in palette.recent(emp, [f"p:{other.pk}", f"p:{listed.pk}"], TODAY)] == [f"p:{listed.pk}"]


def test_recent_drops_a_page_the_user_lacks_the_right_for(listed: Employee) -> None:
    emp = _user("Employee", "pal_rec3")
    assert palette.recent(emp, [f"s:{reverse('employees:orders')}"], TODAY) == []  # needs macs.view_employees
    assert palette.recent(emp, ["s:/no/such/page/"], TODAY) == []  # not a screen at all


def test_recent_drops_a_person_with_no_hr_row(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(
        hire_values("УБ99200002") | {"family_name": "Нуудэлгүй"},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
    )
    EmployeeExt.objects.filter(employee=emp).delete()
    hr = _user("HR", "pal_rec4")
    assert palette.recent(hr, [f"p:{emp.pk}"], TODAY) == []


def test_recent_refs_drop_garbage_and_duplicates() -> None:
    assert palette.parse_refs("p:abc,x:1,,s:,p:-1,p:,s:nopath,p:7") == ["p:7"]
    assert palette.parse_refs("p:7,p:7,s:/leave/,s:/leave/") == ["p:7", "s:/leave/"]
    assert palette.parse_refs("p:" + "9" * 40) == []  # too long a number is not a pk
    assert palette.parse_refs("s:/" + "a" * 500) == []  # too long a path is not read


def test_recent_list_is_capped_at_five(listed: Employee) -> None:
    hr = _user("HR", "pal_rec5")
    screens_now = [f"s:{s.url}" for s in palette.screens(hr, "")]
    assert len(screens_now) >= 6  # the user really has more pages than the cap
    assert len(palette.parse_refs(",".join(screens_now))) == palette.RECENT_LIMIT == 5
    assert [r.ref for r in palette.recent(hr, screens_now[:5], TODAY)] == screens_now[:5]
    assert len(palette.recent(hr, screens_now[:6], TODAY)) == 6  # recent() itself does not cut; the parser does


def test_recent_ignores_garbage_before_the_five(client: Client, listed: Employee) -> None:
    hr = _user("HR", "pal_rec6")
    client.force_login(hr)
    pages = [f"s:{s.url}" for s in palette.screens(hr, "")][:5]
    body = _recent_body(client, ",".join(["zz:1", "p:abc", *pages]))
    assert all(f'data-palette-ref="{ref}"' in body for ref in pages)


def test_recent_is_not_shown_for_a_typed_query(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_rec7"))
    body = _recent_body(client, f"p:{listed.pk}", q="Батын")
    assert "Сүүлд нээсэн" not in body
    assert f'data-palette-ref="p:{listed.pk}"' in body  # the person row itself still carries its ref


def test_empty_box_without_recent_is_unchanged(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_rec8"))
    body = client.get(reverse("employees:palette")).content.decode()
    assert "Сүүлд нээсэн" not in body
    assert "data-palette-ref" in body  # the screens still carry their refs, for the browser to remember


def test_rendered_recent_group_has_header_and_refs(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_rec9"))
    today_ref = f"s:{reverse('employees:today')}"
    body = _recent_body(client, f"{today_ref},p:{listed.pk}")
    assert "Сүүлд нээсэн" in body
    assert body.index("Сүүлд нээсэн") < body.index("Хуудас")  # first group in the empty box
    assert body.index(f'data-palette-ref="p:{listed.pk}"') < body.index("Хуудас")
    assert f'href="/employees/{listed.pk}/"' in body
    first = re.findall(r"<a [^>]*data-palette-item[^>]*>", body)[0]
    assert f'data-palette-ref="{today_ref}"' in first and 'role="option"' in first


def test_quick_actions_carry_no_ref(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_rec10"))
    body = _recent_body(client, f"p:{listed.pk}")
    assert "data-palette-ref" not in _anchor(body, "/leave/new/")
    assert "data-palette-ref" not in _anchor(body, "/employees/new/")


def test_empty_state_still_works_with_recent(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_rec11"))
    body = _recent_body(client, "p:99999999", q="zzzzqq")
    assert "data-palette-empty" in body and "Юу ч олдсонгүй" in body


def test_recent_query_count_does_not_grow_with_more_people(actor: User, job_values: dict[str, Any]) -> None:
    first = _hire(actor, job_values, "УБ99201001", "Олноор", "Нэр1")
    hr = _user("HR", "pal_rec12")
    palette.recent(hr, [f"p:{first.pk}"], TODAY)  # warm-up
    with CaptureQueriesContext(connection) as few:
        assert len(palette.recent(hr, [f"p:{first.pk}"], TODAY)) == 1
    others = [_hire(actor, job_values, f"УБ{99201010 + i:08d}", "Олноор", f"Нэр{i}") for i in range(4)]
    refs = [f"p:{first.pk}"] + [f"p:{e.pk}" for e in others]
    with CaptureQueriesContext(connection) as many:
        assert len(palette.recent(hr, refs, TODAY)) == 5
    assert len(many.captured_queries) == len(few.captured_queries)


def test_palette_recent_is_the_only_group_on_an_empty_box_with_no_screens(client: Client, listed: Employee) -> None:
    """A recent person keeps the person's row markup (the same link as the people group)."""
    client.force_login(_user("HR", "pal_rec13"))
    body = _recent_body(client, f"p:{listed.pk}")
    assert body.count(f'href="/employees/{listed.pk}/"') == 1
    assert "Хүмүүс" not in body  # the people group is for typed queries only


# --- Context group: on an employee's page the empty box starts with that person's actions (the `from` path) ---


def _from_body(client: Client, path: str, recent: str = "", q: str = "") -> str:
    return client.get(reverse("employees:palette"), {"q": q, "recent": recent, "from": path}).content.decode()


def test_empty_box_on_a_person_page_starts_with_their_actions(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_ctx1"))
    body = _from_body(client, f"/employees/{listed.pk}/", recent=f"s:{reverse('employees:today')}")
    assert f"Үйлдэл · {listed.full_name}" in body
    assert body.index(f"Үйлдэл · {listed.full_name}") < body.index("Сүүлд нээсэн") < body.index("Хуудас")
    assert "Хүмүүс" not in body  # the people group is for typed queries only
    leave = _anchor(body, f"/leave/new/?employee={listed.pk}")
    assert "data-palette-item" in leave and "data-palette-modal" in leave  # the leave pop-up, with the employee
    contract = _anchor(body, f"/employees/{listed.pk}/event/contract/")
    assert "data-palette-item" in contract and "data-palette-modal" in contract  # the contract pop-up


def test_empty_box_context_group_follows_the_rights(client: Client, listed: Employee) -> None:
    leave_only = _user("Employee", "pal_ctx2")
    link_login(listed, leave_only)
    leave_only.user_permissions.add(_perm("record_leave", "leave"), _perm("view_leave", "leave"))
    client.force_login(leave_only)
    body = _from_body(client, f"/employees/{listed.pk}/")
    assert f"Үйлдэл · {listed.full_name}" in body
    assert f"/leave/new/?employee={listed.pk}" in body
    assert f"/employees/{listed.pk}/event/contract/" not in body


def test_empty_box_context_group_is_absent_without_rights(client: Client, listed: Employee) -> None:
    nobody = _user("Employee", "pal_ctx3")
    link_login(listed, nobody)
    client.force_login(nobody)
    body = _from_body(client, f"/employees/{listed.pk}/")
    assert "Үйлдэл · " not in body
    assert f"?employee={listed.pk}" not in body


def test_empty_box_context_group_is_absent_for_a_left_person(
    client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    leaver = _hire(actor, job_values, "УБ99301100", "Цэвэг", "Нараа")
    record_signed(
        leaver,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    client.force_login(_user("HR", "pal_ctx4"))
    body = _from_body(client, f"/employees/{leaver.pk}/")
    assert "Үйлдэл · " not in body


def test_empty_box_context_group_is_absent_for_a_person_the_user_cannot_see(
    client: Client, listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _hire(actor, job_values, "УБ99301200", "Дорж", "Оюун")
    emp = _user("Employee", "pal_ctx5")
    link_login(listed, emp)  # sees only their own record
    emp.user_permissions.add(_perm("record_leave", "leave"), _perm("view_leave", "leave"))
    client.force_login(emp)
    body = _from_body(client, f"/employees/{other.pk}/")
    assert "Үйлдэл · " not in body
    assert f"?employee={other.pk}" not in body
    assert "Үйлдэл · " in _from_body(client, f"/employees/{listed.pk}/")  # the visible one still gets it


def test_pages_that_are_not_a_person_record_add_no_context_group(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_ctx6"))
    for path in [
        "/leave/",
        "/employees/",
        f"/employees/{listed.pk}/event/contract/",
        f"/employees/{listed.pk}/save/",
        "garbage",
        "/employees/abc/",
        "/employees/999999/",
        "/employees/" + "1" * 250 + "/",
        f"https://evil.example/employees/{listed.pk}/",
        "",
    ]:
        assert "Үйлдэл · " not in _from_body(client, path), path


def test_a_typed_query_ignores_the_page_it_is_sent_from(
    client: Client, listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = _hire(actor, job_values, "УБ99301300", "Дорж", "Оюун")
    client.force_login(_user("HR", "pal_ctx7"))
    nothing = _from_body(client, f"/employees/{listed.pk}/", q="zzzzqq")
    assert "Үйлдэл · " not in nothing and "data-palette-empty" in nothing
    body = _from_body(client, f"/employees/{other.pk}/", q="Батын")
    assert f"Үйлдэл · {listed.full_name}" in body  # the typed match, not the page's person
    assert f"Үйлдэл · {other.full_name}" not in body


def test_context_group_is_shown_with_recent_items_too(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_ctx8"))
    body = _from_body(client, f"/employees/{listed.pk}/", recent=f"p:{listed.pk}")
    assert "Сүүлд нээсэн" in body and f"Үйлдэл · {listed.full_name}" in body
    assert body.count(f'href="/employees/{listed.pk}/"') == 1  # the recent row only; actions link elsewhere


def test_current_is_the_visible_person_with_an_hr_row(
    listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    hr = _user("HR", "pal_ctx9")
    hit = palette.current(hr, listed.pk, TODAY)
    assert hit is not None and hit.employee.pk == listed.pk and hit.left is False
    assert palette.current(hr, 999999, TODAY) is None  # no such person
    assert palette.current(_user("Employee", "pal_ctx10"), listed.pk, TODAY) is None  # not visible
    inactive = _user("HR", "pal_ctx11")
    inactive.is_active = False
    assert palette.current(inactive, listed.pk, TODAY) is None
    no_row = _hire(actor, job_values, "УБ99301400", "Нуудэлгүй", "Бат")
    EmployeeExt.objects.filter(employee=no_row).delete()
    assert palette.current(hr, no_row.pk, TODAY) is None  # no HR row, as the list shows it


def test_current_query_count_does_not_grow_with_more_people(actor: User, job_values: dict[str, Any]) -> None:
    first = _hire(actor, job_values, "УБ99301500", "Олноор", "Нэр1")
    hr = _user("HR", "pal_ctx12")
    palette.current(hr, first.pk, TODAY)  # warm-up
    with CaptureQueriesContext(connection) as few:
        assert palette.current(hr, first.pk, TODAY) is not None
    for i in range(4):
        _hire(actor, job_values, f"УБ{99301510 + i:08d}", "Олноор", f"Нэр{i}")
    with CaptureQueriesContext(connection) as many:
        assert palette.current(hr, first.pk, TODAY) is not None
    assert len(many.captured_queries) == len(few.captured_queries)


# --- Orders by number, and the date jump ---


def _numbered(emp: Employee, number: str, day: date | None) -> HrOrder:
    """Give the employee's hire order a number and a date (a hire makes it with neither)."""
    HrOrder.objects.filter(employee=emp).update(
        number=number, number_key=number.casefold(), date=day, state=OrderState.REGISTERED
    )
    return HrOrder.objects.get(employee=emp)


def test_order_is_found_by_its_number_with_or_without_the_sign(listed: Employee) -> None:
    hr = _user("HR", "pal_ord1")
    order = _numbered(listed, "12", date(2026, 3, 1))
    expected = palette.OrderHit(
        order.pk,
        f"№ 12 · {listed.full_name} · {OrderType.HIRED.label}",
        "2026-03-01",
        reverse("employees:order_detail", args=[listed.pk, order.pk]),
    )
    for query in ("12", "№12", "№ 12", "№ 12 "):
        assert palette.orders(hr, query) == [expected], query
    assert palette.orders(hr, "№") == []  # the sign alone is no number
    assert palette.orders(hr, "13") == []


def test_order_is_not_found_without_the_register_right(listed: Employee) -> None:
    _numbered(listed, "12", date(2026, 3, 1))
    assert palette.orders(_user("Employee", "pal_ord2"), "12") == []
    linked = _user("Employee", "pal_ord3")
    link_login(listed, linked)  # the own order too: the register right decides, as on the register screen
    assert palette.orders(linked, "12") == []


def test_orders_are_newest_first_and_an_undated_one_is_last(
    listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    hr = _user("HR", "pal_ord4")
    old = _numbered(listed, "5", date(2026, 1, 9))
    new = _numbered(_hire(actor, job_values, "УБ99300001", "Тушаалын", "Нэг"), "5", date(2026, 6, 1))
    undated = _numbered(_hire(actor, job_values, "УБ99300002", "Тушаалын", "Хоёр"), "5", None)
    assert [h.pk for h in palette.orders(hr, "5")] == [new.pk, old.pk, undated.pk]


def test_at_most_five_orders_are_listed(actor: User, job_values: dict[str, Any]) -> None:
    hr = _user("HR", "pal_ord5")
    orders = [
        _numbered(_hire(actor, job_values, f"УБ{99310000 + i:08d}", "Тоо", f"Нэр{i}"), "7", date(2026, 1, 1 + i))
        for i in range(7)
    ]
    found = palette.orders(hr, "7")
    assert len(found) == palette.ORDER_LIMIT == 5
    assert [h.pk for h in found] == [o.pk for o in reversed(orders[2:])]  # the five newest


def test_order_query_count_does_not_grow_with_more_orders(
    listed: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    hr = _user("HR", "pal_ord6")
    _numbered(listed, "8", date(2026, 2, 2))
    palette.orders(hr, "8")  # warm-up: the user's permissions are loaded once, on first use
    with CaptureQueriesContext(connection) as few:
        assert len(palette.orders(hr, "8")) == 1
    for i in range(6):
        _numbered(_hire(actor, job_values, f"УБ{99320000 + i:08d}", "Тоо", f"Нэр{i}"), "8", date(2026, 3, 1 + i))
    with CaptureQueriesContext(connection) as many:
        assert len(palette.orders(hr, "8")) == palette.ORDER_LIMIT
    assert len(many.captured_queries) == len(few.captured_queries)


def test_order_row_is_a_pop_up_link_to_the_order(client: Client, listed: Employee) -> None:
    hr = _user("HR", "pal_ord7")
    order = _numbered(listed, "21", date(2026, 4, 4))
    client.force_login(hr)
    body = client.get(reverse("employees:palette"), {"q": "21"}).content.decode()
    url = reverse("employees:order_detail", args=[listed.pk, order.pk])
    anchor = _anchor(body, url)
    assert "data-palette-item" in anchor and "data-palette-modal" in anchor
    assert "Тушаал</span>" in body  # the group header (title, then its count)
    assert "2026-04-04" in body  # the date, in small text under the row
    pop = client.get(url, HTTP_HX_REQUEST="true")  # what the palette's htmx load fetches
    assert pop.status_code == 200 and "fixed inset-0" in pop.content.decode()


def test_a_query_without_a_number_adds_no_order_group(client: Client, listed: Employee) -> None:
    hr = _user("HR", "pal_ord8")
    _numbered(listed, "12", date(2026, 3, 1))
    client.force_login(hr)
    body = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert "Тушаал</span>" not in body
    assert palette.orders(hr, "Батын") == []


def test_a_typed_date_or_month_offers_that_months_calendar(listed: Employee) -> None:
    hr = _user("HR", "pal_dt1")
    link = palette.Screen("Багийн хуанли · 2026-03", f"{reverse('leave:calendar')}?month=2026-03")
    assert palette.screens(hr, "2026-03-05") == [link]
    assert palette.screens(hr, "2026-03") == [link]
    assert palette.screens(hr, "2026-03-05 2026-03") == [link]  # one row per month


@pytest.mark.parametrize("query", ["2026-13-40", "2026-13", "2026-00", "2026-02-30", "1899-12", "2101-01", "2026-3"])
def test_an_invalid_date_or_month_offers_nothing(listed: Employee, query: str) -> None:
    assert palette.screens(_user("HR", "pal_dt2"), query) == []


def test_the_date_jump_needs_the_leave_right(listed: Employee) -> None:
    assert palette.screens(_user("Employee", "pal_dt3"), "2026-03-05") == []


def test_the_date_jump_is_first_in_the_screens_group(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_dt4"))
    body = client.get(reverse("employees:palette"), {"q": "2026-03-05"}).content.decode()
    anchor = _anchor(body, f"{reverse('leave:calendar')}?month=2026-03")
    assert "data-palette-item" in anchor and "data-palette-modal" not in anchor  # a page, not a pop-up
    assert "Хүмүүс" not in body
    assert body.index("Хуудас") < body.index("Багийн хуанли · 2026-03")


# --- Highlight: the typed letters inside a row's text (folded like the search, positions kept) ---


def test_highlight_plain_text_marks_the_typed_word() -> None:
    assert palette.highlight("Батын Сараа", ["сараа"]) == [("Батын ", False), ("Сараа", True)]


def test_highlight_reads_folded_letters_and_keeps_the_original_text() -> None:
    assert palette.highlight("Өнөрболд", ["онорболд"]) == [("Өнөрболд", True)]  # ө typed as о
    assert palette.highlight("Өнөрболд", ["нор"]) == [("Ө", False), ("нөр", True), ("болд", False)]  # ө in the text


def test_highlight_ignores_case() -> None:
    assert palette.highlight("ANNA", ["nna"]) == [("A", False), ("NNA", True)]


def test_highlight_marks_every_typed_word() -> None:
    assert palette.highlight("Батын Сараа", ["бат", "сар"]) == [
        ("Бат", True),
        ("ын ", False),
        ("Сар", True),
        ("аа", False),
    ]


def test_highlight_merges_overlapping_matches() -> None:
    assert palette.highlight("abcd", ["ab", "bc"]) == [("abc", True), ("d", False)]


def test_highlight_merges_adjacent_matches() -> None:
    assert palette.highlight("abcd", ["ab", "cd"]) == [("abcd", True)]


def test_highlight_with_no_words_or_no_text() -> None:
    assert palette.highlight("Батын", []) == [("Батын", False)]
    assert palette.highlight("Батын", [""]) == [("Батын", False)]
    assert palette.highlight("", ["бат"]) == []


def test_highlight_pieces_always_join_back_to_the_text() -> None:
    text = "Өнөрболд Түмэн-Очир <b>x</b>"
    for words in (["он"], ["тум", "очир"], ["ө", "у", "б"], ["zz"]):
        pieces = palette.highlight(text, words)
        assert "".join(segment for segment, _ in pieces) == text
        assert all(segment for segment, _ in pieces)  # no empty pieces


def test_highlight_never_misaligns_after_a_letter_whose_fold_changes_length() -> None:
    """ß folds to two letters, so it is never matched and the letters after it still line up."""
    assert palette.highlight("ßa", ["ss"]) == [("ßa", False)]
    assert palette.highlight("ßab", ["ab"]) == [("ß", False), ("ab", True)]


def test_highlight_filter_escapes_html_and_marks_matches() -> None:
    out = hl("<b>Бат</b>", ["бат"])
    assert out == ('&lt;b&gt;<mark class="rounded bg-violet-200/60 text-inherit">Бат</mark>&lt;/b&gt;')


def test_highlight_filter_without_words_only_escapes() -> None:
    assert hl("<b>Бат</b>", []) == "&lt;b&gt;Бат&lt;/b&gt;"
    assert hl("", ["бат"]) == ""


def test_rendered_row_marks_a_typed_word_and_escapes_html(client: Client, listed: Employee) -> None:
    Employee.objects.filter(pk=listed.pk).update(given_name="<b>Бат")
    client.force_login(_user("HR", "pal_hl1"))
    body = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert "<mark" in body
    assert "&lt;b&gt;" in body
    assert "<b>Бат" not in body


def test_rendered_empty_box_has_no_marks(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_hl2"))
    body = client.get(reverse("employees:palette")).content.decode()
    assert "<mark" not in body


# --- Icons, initials and the selected-row marker ---


def test_initials_are_the_first_letters_of_family_and_given_name() -> None:
    assert palette.PersonHit(Employee(family_name="батын", given_name="сараа"), False, "", "").initials == "БС"
    assert palette.PersonHit(Employee(family_name=None, given_name=""), False, "", "").initials == ""


def test_screen_kind_is_calendar_only_for_the_team_calendar(listed: Employee) -> None:
    hr = _user("HR", "pal_icon1")
    (calendar,) = palette.screens(hr, "хуанли")
    assert calendar.kind == "calendar"
    (leave,) = [s for s in palette.screens(hr, "чөлөө") if s.title == "Чөлөө, амралт"]
    assert leave.kind == "page"
    (month,) = palette.screens(hr, "2026-03")
    assert month.kind == "calendar"


def test_palette_rows_carry_icons_initials_and_the_selected_marker(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_icon2"))
    body = client.get(reverse("employees:palette")).content.decode()
    assert body.count('aria-hidden="true"') >= 5  # one icon per page and action row
    assert "aria-selected:border-l-violet-600" in body  # the selected row's marker
    assert "border-l-transparent" in body  # reserved on every row, so rows do not shift
    initials = ((listed.family_name or "")[:1] + (listed.given_name or "")[:1]).upper()
    typed = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    assert f">{initials}</span>" in typed  # the initials circle of the person row


# --- The pop-up's look (2026-10-27): shell, footer hint, group headers, empty state, phone rows ---


def test_palette_shell_is_a_wide_panel_with_the_key_hint(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_shell1"))
    body = client.get(reverse("employees:today")).content.decode()
    tpl = re.search(r'<template id="palette-template".*?</template>', body, re.DOTALL)
    assert tpl is not None
    shell = tpl.group(0)
    assert "max-w-xl" in shell and "max-w-lg" not in shell
    assert "pt-4 sm:pt-24" in shell and "shadow-2xl ring-1 ring-slate-900/5" in shell
    assert "text-base" in shell  # the larger input text
    hint_at = shell.index("data-palette-hint")
    assert shell.index("Хайлт амжилтгүй боллоо</p></div>") < hint_at  # below the list, not in it
    hint = re.search(r'<div data-palette-hint class="([^"]*)">', shell)
    assert hint is not None
    assert "hidden" in hint.group(1).split() and "sm:flex" in hint.group(1).split()  # no keys on a phone
    assert "сонгох" in shell and "нээх" in shell and "хаах" in shell
    assert shell.count("<kbd") == 3
    assert 'role="combobox"' in shell and "data-palette-input" in shell  # the input keeps its attributes


def test_group_headers_show_how_many_rows_each_group_has(
    client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    _hire(actor, job_values, "УБ99401001", "Тоолуур", "Нэр1")
    _hire(actor, job_values, "УБ99401002", "Тоолуур", "Нэр2")
    client.force_login(_user("HR", "pal_grp1"))
    body = client.get(reverse("employees:palette"), {"q": "Тоолуур"}).content.decode()
    assert '<span>Хүмүүс</span><span class="font-normal text-slate-400">2</span>' in body
    assert "sticky top-0" in body and "first:border-t-0" in body  # sticky, and no divider above the first group


def test_empty_state_keeps_its_text_and_offers_the_employee_list(client: Client, listed: Employee) -> None:
    client.force_login(_user("Employee", "pal_empty1"))
    body = client.get(reverse("employees:palette"), {"q": "zzzzqq"}).content.decode()
    assert "data-palette-empty" in body and "Юу ч олдсонгүй" in body
    assert body.index("Юу ч олдсонгүй") < body.index("Эсвэл нээх:") < body.index("Ажилтнууд</span>")
    link = _anchor(body, reverse("employees:list"))
    assert "data-palette-item" in link and 'role="option"' in link  # keyboard-selectable like any row
    assert "Ажилтан нэмэх" not in body  # the Employee role may not add a person


def test_empty_state_offers_adding_a_person_to_those_who_may(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_empty2"))
    body = client.get(reverse("employees:palette"), {"q": "zzzzqq"}).content.decode()
    add = _anchor(body, reverse("employees:add"))
    assert "Ажилтан нэмэх" in body and "data-palette-item" in add and 'role="option"' in add
    assert "data-palette-modal" not in add  # a page, not a pop-up


def test_rows_are_at_least_44_px_tall_on_a_phone(client: Client, listed: Employee) -> None:
    client.force_login(_user("HR", "pal_phone1"))
    body = client.get(reverse("employees:palette"), {"q": "Батын"}).content.decode()
    rows = re.findall(r"<a [^>]*data-palette-item[^>]*>", body)
    assert rows and all("max-sm:min-h-11" in row for row in rows)


def test_each_sticky_group_header_has_its_own_group_wrapper(client: Client, listed: Employee) -> None:
    """Sibling headers all stick at top 0 and stack; each needs its own wrapper so the next one replaces it."""
    client.force_login(_user("HR", "pal_grp_wrap"))
    body = _recent_body(client, f"p:{listed.pk}")
    chunks = body.split('<div class="border-t border-slate-100 first:border-t-0">')[1:]
    assert len(chunks) >= 2
    assert all(chunk.count("sticky top-0") == 1 for chunk in chunks)

"""The palette's display rows (employees.services.palette_rows): the groups in the order of the palette fragment, the
«show all» and cut rows, highlight pieces, the fallback rows and where each row opens. The answer itself is covered by
test_palette_answer.py; the HTTP side by test_palette.py."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from employees.models import Employee
from employees.palette import Action, OrderHit, PersonHit, Recent, Screen
from employees.services import palette_answer
from employees.services.palette_answer import PaletteAnswer
from employees.services.palette_rows import (
    EMPTY_TEXT,
    FALLBACK_HEADING,
    PaletteOpen,
    PalettePiece,
    empty,
    fallback,
    groups,
    open_target,
)

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _answer(**overrides: object) -> PaletteAnswer:
    """An answer with every group empty, then the given fields."""
    base: dict[str, object] = {
        "words": [],
        "people": [],
        "people_total": 0,
        "people_more": False,
        "recent": [],
        "current": None,
        "current_actions": [],
        "single": None,
        "person_actions": [],
        "orders": [],
        "screens": [],
        "actions": [],
        "fixed_urls": set(),
    }
    return PaletteAnswer(**(base | overrides))  # type: ignore[arg-type]


def _hit(
    pk: int = 1, family: str = "Батын", given: str = "Дорж", position: str = "", department: str = ""
) -> PersonHit:
    emp = Employee(pk=pk, family_name=family, given_name=given, code="УБ99100001")
    return PersonHit(emp, False, position, department)


def _user(name: str) -> User:
    return User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106


def _grant(user: User, app_label: str, codename: str) -> None:
    perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
    user.user_permissions.add(perm)


def _plain(text: str) -> list[PalettePiece]:
    return [PalettePiece(text, False)]


def test_open_target_page_for_non_modal() -> None:
    url = reverse("leave:calendar") + "?month=2026-10"
    assert open_target(url, False) == PaletteOpen("page", url, None, None, None, None, None)
    assert open_target(reverse("employees:order_detail", args=[5, 9]), False).kind == "page"


def test_open_target_order_popup() -> None:
    url = reverse("employees:order_detail", args=[5, 9])
    assert open_target(url, True) == PaletteOpen("popup", url, "order_detail", 5, 9, None, None)


def test_open_target_event_popup_carries_type_and_employee() -> None:
    url = reverse("employees:event", args=[5, "contract"])
    assert open_target(url, True) == PaletteOpen("popup", url, "event", 5, None, "contract", None)


def test_open_target_slot_add_carries_year() -> None:
    path = reverse("employees:slot_add")
    # The quick action has no ?year=: the pop-up gets the current year, as slot_add itself does.
    this_year = timezone.localdate().year
    assert open_target(path, True) == PaletteOpen("popup", path, "slot_add", None, None, None, this_year)
    assert open_target(path + "?year=2031", True) == PaletteOpen("popup", path, "slot_add", None, None, None, 2031)
    assert open_target(path + "?year=2026", False).kind == "page"  # not a pop-up when opened as a page


@pytest.mark.parametrize("raw", ["1999", "12", "99999", "abcd", "", "2026x"])
def test_open_target_slot_add_invalid_year_falls_back_to_this_year(raw: str) -> None:
    path = reverse("employees:slot_add")
    target = open_target(path + f"?year={raw}", True)
    assert target.popup == "slot_add"
    assert target.year == timezone.localdate().year


def test_open_target_leave_add_is_a_popup_with_the_employee() -> None:
    path = reverse("leave:add")
    assert open_target(path + "?employee=5", True) == PaletteOpen("popup", path, "leave_add", 5, None, None, None)
    assert open_target(path, True) == PaletteOpen("popup", path, "leave_add", None, None, None, None)
    assert open_target(path + "?employee=abc", True) == PaletteOpen("popup", path, "leave_add", None, None, None, None)
    assert open_target(path + "?employee=5", False).kind == "page"  # not a pop-up when opened as a page


def test_open_target_leave_request_new_is_a_popup_without_employee() -> None:
    path = reverse("leave:request_new")
    assert open_target(path, True) == PaletteOpen("popup", path, "leave_request", None, None, None, None)
    assert open_target(path, False).kind == "page"  # not a pop-up when opened as a page


def test_open_target_unported_modals_become_legacy_list_pages() -> None:
    vacancy = open_target(reverse("recruitment:vacancy_add"), True)
    assert vacancy == PaletteOpen("legacy", reverse("recruitment:vacancies"), None, None, None, None, None)
    # A modal that no table names is opened as the page it names (never loaded as a fragment).
    listed = reverse("employees:list")
    assert open_target(listed, True) == PaletteOpen("page", listed, None, None, None, None, None)


def test_groups_order_and_titles() -> None:
    hit = _hit()
    order_url = reverse("employees:order_detail", args=[5, 9])
    event_url = reverse("employees:event", args=[5, "contract"])
    leave_url = reverse("leave:add") + "?employee=5"
    answer = _answer(
        current=hit,
        current_actions=[Action("Чөлөө бүртгэх", leave_url, True)],
        recent=[Recent("s:/today/", "Өнөөдөр", "/today/")],
        people=[hit],
        people_total=1,
        single=hit,
        person_actions=[Action("Гэрээ сунгах / өөрчлөх", event_url, True)],
        orders=[OrderHit(9, "№ 1 · Батын Дорж · Ажилд авах", "2026-10-01", order_url)],
        screens=[Screen("Тайлан", "/reports/")],
        actions=[Action("Нууц үг солих", reverse("password_change"), False)],
    )
    result = groups(answer, _user("pr_order"))
    by_key = {g.key: g for g in result}
    # Each row opens what the template links to, through the same rule as open_target.
    assert by_key["current_actions"].rows[0].open == PaletteOpen(
        "popup", reverse("leave:add"), "leave_add", 5, None, None, None
    )
    assert by_key["person_actions"].rows[0].open == PaletteOpen("popup", event_url, "event", 5, None, "contract", None)
    order_row = by_key["orders"].rows[0]
    assert order_row.open == PaletteOpen("popup", order_url, "order_detail", 5, 9, None, None)
    assert order_row.day == "2026-10-01"
    assert order_row.lines == []
    assert by_key["actions"].rows[0].open == PaletteOpen(
        "page", reverse("password_change"), None, None, None, None, None
    )
    assert by_key["recent"].rows[0].open == PaletteOpen("page", "/today/", None, None, None, None, None)
    assert [g.key for g in result] == [
        "current_actions",
        "recent",
        "people",
        "person_actions",
        "orders",
        "screens",
        "actions",
    ]
    assert [g.title for g in result] == [
        "Үйлдэл · Батын Дорж",
        "Сүүлд нээсэн",
        "Хүмүүс",
        "Үйлдэл · Батын Дорж",
        "Тушаал",
        "Хуудас",
        "Үйлдэл",
    ]
    assert [g.count for g in result] == [1, 1, 1, 1, 1, 1, 1]


def test_people_group_has_total_and_more_row_or_cut_note() -> None:
    hit = _hit()
    more = groups(_answer(people=[hit], people_total=3, people_more=True), _user("pr_more1"))[0]
    assert (more.count, more.total, more.note) == (1, 3, "")
    assert more.rows[-1].kind == "more"
    assert more.rows[-1].ref is None
    assert more.rows[-1].open is None  # «show all» does not navigate
    assert more.rows[-1].title == _plain("Бүх 3 хүнийг харуулах")
    cut = groups(_answer(people=[hit], people_total=3, people_more=False), _user("pr_more2"))[0]
    assert cut.note == "Эхний 1 хүн харагдаж байна. Хайлтаа нарийсгана уу."
    assert cut.total == 3
    assert [r.kind for r in cut.rows] == ["person"]
    whole = groups(_answer(people=[hit], people_total=1, people_more=False), _user("pr_more3"))[0]
    assert whole.note == ""
    assert whole.total is None  # the header shows «x / total» only when some are left out
    assert [r.kind for r in whole.rows] == ["person"]


def test_highlight_pieces_only_when_words_typed() -> None:
    hit = _hit()
    typed = groups(_answer(words=["Батын"], people=[hit], people_total=1), _user("pr_hl1"))[0]
    title = typed.rows[0].title
    assert [p.text for p in title if p.hit] == ["Батын"]
    assert "".join(p.text for p in title) == "Батын Дорж"
    empty_box = groups(_answer(words=[], people=[hit], people_total=1), _user("pr_hl2"))[0]
    assert all(not p.hit for p in empty_box.rows[0].title)


def test_recent_person_row_has_no_highlight() -> None:
    hit = _hit()
    recent = Recent("p:1", "Батын Дорж", reverse("employees:detail", args=[1]), hit)
    result = groups(_answer(words=["Батын"], recent=[recent]), _user("pr_recent"))
    row = result[0].rows[0]
    assert row.kind == "person"
    assert row.ref == "p:1"
    assert not any(p.hit for p in row.title)
    assert row.lines == []


def test_screen_ref_only_for_fixed_urls() -> None:
    answer = _answer(
        screens=[Screen("Өнөөдөр", "/today/"), Screen("Тайлан", "/reports/")],
        fixed_urls={"/today/"},
    )
    rows = groups(answer, _user("pr_screen"))[0].rows
    assert [r.ref for r in rows] == ["s:/today/", None]
    assert [r.kind for r in rows] == ["page", "page"]


def test_groups_empty_for_user_without_rights() -> None:
    user = _user("pr_norights")
    answer = palette_answer.answer(user, q="zzz", more=False, recent_raw="", from_path="", today=TODAY)
    assert groups(answer, user) == []
    assert fallback(user) == []


def test_fallback_rows_follow_rights() -> None:
    both = _user("pr_fb_both")
    _grant(both, "reports", "view_reports")
    _grant(both, "macs", "view_employees")
    _grant(both, "macs", "manage_employees")
    rows = fallback(User.objects.get(pk=both.pk))
    assert [r.title for r in rows] == [_plain("Ажилтнууд"), _plain("Ажилтан нэмэх")]
    assert [r.kind for r in rows] == ["page", "action"]
    assert rows[0].open == open_target(reverse("employees:list"), False)
    assert rows[1].open == open_target(reverse("employees:add"), False)

    viewer = _user("pr_fb_view")
    _grant(viewer, "reports", "view_reports")
    _grant(viewer, "macs", "view_employees")
    assert [r.title for r in fallback(User.objects.get(pk=viewer.pk))] == [_plain("Ажилтнууд")]

    reports_only = _user("pr_fb_reports")  # the report right alone does not show the employee list (AND gate)
    _grant(reports_only, "reports", "view_reports")
    assert fallback(User.objects.get(pk=reports_only.pk)) == []

    manager = _user("pr_fb_manage")
    _grant(manager, "macs", "manage_employees")
    assert [r.title for r in fallback(User.objects.get(pk=manager.pk))] == [_plain("Ажилтан нэмэх")]


def test_empty_rule_and_text_constants() -> None:
    assert EMPTY_TEXT == "Юу ч олдсонгүй"
    assert FALLBACK_HEADING == "Эсвэл нээх:"
    assert empty(_answer())
    # The person's own actions do not count toward the empty rule, as in the template.
    hit = _hit()
    assert empty(_answer(single=hit, person_actions=[Action("Чөлөө бүртгэх", "/x/", True)]))
    assert not empty(_answer(orders=[OrderHit(1, "№ 1", "", "/o/")]))
    assert not empty(_answer(people=[hit], people_total=1))
    assert not empty(_answer(screens=[Screen("Тайлан", "/reports/")]))
    assert not empty(_answer(actions=[Action("Нууц үг солих", "/p/", False)]))
    assert not empty(_answer(recent=[Recent("s:/today/", "Өнөөдөр", "/today/")]))
    assert not empty(_answer(current=hit, current_actions=[Action("Чөлөө бүртгэх", "/x/", True)]))

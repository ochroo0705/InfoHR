"""The «Багана» pop-up: the columns and grouping the user picks, and the page they make."""

import re
from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client

from reports import table as tables
from reports.filters import Filters
from reports.registry import REPORTS
from reports.staff_list import DEFAULT_COLUMNS, REPORT
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

MODAL = "/reports/staff-list/columns/"


def _checkbox(page: str, key: str) -> str:
    """The tag of the column tick box for this key."""
    match = re.search(rf'<input[^>]*name="cols"[^>]*value="{key}"[^>]*>', page)
    assert match is not None, f"no tick box for {key}"
    return match.group(0)


def _headers(page: str) -> list[str]:
    """The table's header texts, in order (the sort arrow is not part of the text)."""
    return [text.strip() for text in re.findall(r"<th[^>]*><a[^>]*>([^<]*)", page)]


def test_modal_lists_only_columns_hr_may_see(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")  # view_personal, no view_salary
    page = client.get(MODAL).content.decode()
    assert "Багана сонгох" in page
    assert "Регистрийн дугаар" in page
    assert 'value="salary"' not in page and "Үндсэн цалин" not in page


def test_current_columns_are_ticked(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(MODAL + "?cols=code&cols=email").content.decode()
    assert "checked" in _checkbox(page, "code")
    assert "checked" in _checkbox(page, "email")
    assert "checked" not in _checkbox(page, "name")


def test_no_columns_in_address_ticks_the_default_ones(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(MODAL).content.decode()
    assert "checked" in _checkbox(page, "name")  # a default column
    assert "checked" not in _checkbox(page, "clan_name")  # not a default column


def test_form_is_a_get_to_the_report_keeping_the_filters(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(MODAL + "?state=all&as_of=2026-03-01&cols=code&group=department&sort=-name").content.decode()
    form = re.search(r"<form[^>]*>", page)
    assert form is not None
    assert 'action="/reports/staff-list/"' in form.group(0) and 'method="get"' in form.group(0)
    hidden = set(re.findall(r'<input type="hidden" name="(\w+)"', page))
    assert hidden == {"state", "as_of", "sort"}  # cols and group are chosen in the pop-up, not carried
    assert 'name="state" value="all"' in page and 'name="as_of" value="2026-03-01"' in page


def test_grouping_choice_offers_the_group_columns(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(MODAL + "?group=department").content.decode()
    assert 'name="group"' in page
    assert 'value="department" selected' in page
    for label in ("Бүлэглэхгүй", "Хэлтэс", "Салбар", "Албан тушаал"):
        assert label in page


def test_grouping_offers_only_columns_the_user_may_see(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = Report(
        key="picker",
        title="Туршилт",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="regno", label="Регистр", value=lambda r: r.regno, needs="macs.view_personal"),
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("dept", "regno"),
        picks_columns=True,
    )
    monkeypatch.setitem(REPORTS, "picker", report)
    login_as(client, "Accountant")  # no view_personal
    page = client.get("/reports/picker/columns/").content.decode()
    assert 'value="dept"' in page
    assert 'value="regno"' not in page


def test_chosen_columns_and_group_make_the_page(client: Client, login_as: Callable[..., User], hired: object) -> None:
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?cols=code&cols=email&group=department").content.decode()
    assert _headers(page) == ["Код", "И-мэйл"]
    assert "Санхүү · 1" in page  # one group row for the department


def test_columns_button_carries_the_current_query(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?cols=code&cols=email&group=department").content.decode()
    assert 'hx-get="/reports/staff-list/columns/?cols=code&amp;cols=email&amp;group=department"' in page


def test_report_without_column_picker_has_no_modal(
    client: Client, login_as: Callable[..., User], fake_report: Report
) -> None:
    login_as(client, "HR")
    assert client.get("/reports/fake/columns/").status_code == 404


def test_modal_needs_the_report_permission(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee")
    assert client.get(MODAL).status_code == 403


def test_modal_offers_no_personal_column_to_accountant(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant")
    page = client.get(MODAL + "?cols=clan_name&cols=code").content.decode()
    for label in ("Ургийн овог", "Хүйс", "Үндэс угсаа", "Иргэншил", "Төрсөн газар", "Нийгмийн гарал", "Боловсрол"):
        assert label not in page
    assert 'value="clan_name"' not in page and 'value="code"' in page


def test_shown_keys_is_the_one_rule(hr_user: User) -> None:
    assert tables.shown_keys(REPORT, hr_user, Filters(columns=("salary", "code", "code"))) == ["code"]
    assert tables.shown_keys(REPORT, hr_user, Filters()) == list(DEFAULT_COLUMNS)  # no columns asked: the defaults


def test_report_rows_receive_only_the_columns_the_table_shows(hr_user: User) -> None:
    seen: list[Filters] = []

    def fetch(user: User, f: Filters) -> list[object]:
        seen.append(f)
        return []

    report = Report(
        key="shown",
        title="Харагдах багана",
        filters=(),
        columns=(
            Column(key="code", label="Код", value=lambda r: r),
            Column(key="salary", label="Цалин", value=lambda r: r, needs="macs.view_salary"),
        ),
        default_columns=("code",),
        rows=fetch,
    )
    tables.build_table(report, hr_user, Filters(columns=("salary", "code")))  # HR has no view_salary
    assert seen[0].columns == ("code",)

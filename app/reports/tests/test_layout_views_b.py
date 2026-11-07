"""The calendar and timeline pages: the month grid, the arrows, the bars, the notes, and the per-viewer rules."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.templatetags.hr import mnt

from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-views-b-test"
PAGE = f"/reports/{KEY}/"
SALARY = 8765432  # the value a viewer without macs.view_salary must never see


def _row(name: str, start: object = None, end: object = None, pay: int = SALARY) -> Any:
    return SimpleNamespace(name=name, dept="Санхүү", start=start, end=end, pay=pay)


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a report over these rows: name, dept, start and end (dates) and a hidden salary."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тайлан",
            filters=(),
            columns=(
                Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
                Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
                Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
                Column(key="end", label="Дууссан", value=lambda r: r.end, kind="date"),
                Column(
                    key="pay",
                    label="Цалин",
                    value=lambda r: r.pay,
                    needs="macs.view_salary",
                    numeric=True,
                    money=True,
                    kind="number",
                ),
            ),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            group_options=("dept",),
            layouts=("board", "calendar", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


def _tag_with(page: str, label: str) -> str:
    """The opening tag of the element carrying this aria-label."""
    match = re.search(r"<[a-z]+ [^>]*aria-label=\"" + re.escape(label) + r"\"[^>]*>", page)
    assert match is not None, f"no element labelled {label}"
    return match.group(0)


def _day_cell(page: str, day: str) -> str:
    """The text of the grid cell for this day, up to the next grid cell."""
    return page.split(f'data-day="{day}"', 1)[1].split('data-day="', 1)[0]


# ---- the calendar ----


def test_calendar_shows_the_month_heading_and_the_entry_on_its_day(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 3, 15))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert "2026 оны 3-р сар" in page
    assert "Ажилтан 01" in _day_cell(page, "2026-03-15")
    assert "Ажилтан 01" not in _day_cell(page, "2026-03-16")


def test_calendar_counts_rows_without_a_date_as_undated(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 3, 2)), _row("Ажилтан 02"), _row("Ажилтан 03")])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert "Огноогүй: 2" in page


def test_calendar_has_no_undated_line_when_every_row_is_dated(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 3, 2))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert "Огноогүй" not in page


def test_calendar_with_no_rows_shows_the_empty_text(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page
    assert "data-day=" not in page


def test_calendar_mobile_list_shows_only_days_with_entries(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 3, 15))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert 'class="hidden sm:grid' in page
    assert "sm:hidden" in page
    assert 'data-list-day="2026-03-15"' in page
    assert 'data-list-day="2026-03-16"' not in page


def test_calendar_arrows_link_to_the_neighbouring_months(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 3, 15))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}).content.decode()
    assert "lmonth=2026-02" in _tag_with(page, "Өмнөх сар")
    assert "lmonth=2026-04" in _tag_with(page, "Дараах сар")
    assert _tag_with(page, "Өмнөх сар").startswith("<a ")


def _disabled_arrow(page: str, label: str) -> str:
    """The disabled arrow (a span) whose visually hidden text is this label, from its opening tag to the label."""
    marker = f'<span class="sr-only">{label}</span>'
    assert marker in page, f"no disabled arrow labelled {label}"
    start = page.rindex('<span aria-disabled="true"', 0, page.index(marker))
    return page[start : page.index(marker)]


def test_calendar_prev_arrow_is_disabled_at_1900_01(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(1900, 1, 5))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "1900-01"}).content.decode()
    prev = _disabled_arrow(page, "Өмнөх сар")
    assert prev.startswith("<span ")
    assert 'aria-disabled="true"' in prev
    assert "href" not in prev
    assert _tag_with(page, "Дараах сар").startswith("<a ")


def test_calendar_next_arrow_is_disabled_at_2100_12(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2100, 12, 5))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2100-12"}).content.decode()
    nxt = _disabled_arrow(page, "Дараах сар")
    assert nxt.startswith("<span ")
    assert 'aria-disabled="true"' in nxt
    assert "href" not in nxt
    assert _tag_with(page, "Өмнөх сар").startswith("<a ")


# ---- the timeline ----


def test_timeline_has_one_bar_per_row(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    rows = [
        _row(f"Ажилтан {n:02d}", start=date(2026, n, 1), end=date(2026, n, 20)) for n in range(1, 6)
    ]  # five rows, five bars
    use_rows(rows)
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert page.count("data-bar") == 5


def test_timeline_notes_for_undated_rows_and_rows_off_the_axis(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    rows = [
        _row("Ажилтан 01", start=date(2026, 1, 1), end=date(2026, 1, 10)),
        _row("Ажилтан 02", start=date(2026, 2, 1), end=date(2033, 1, 1)),  # ends past 5 years: the axis is clipped
        _row("Ажилтан 03", start=date(2032, 1, 1), end=date(2032, 2, 1)),  # starts after the clipped axis
        _row("Ажилтан 04"),  # no start: undated
    ]
    use_rows(rows)
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert page.count("data-bar") == 2
    assert "Огноогүй: 1" in page
    assert "Хүрээнээс гадуур: 1" in page
    assert "Хугацааны хүрээ 5 жилээр хязгаарлагдсан." in page


def test_timeline_over_the_cap_shows_the_note(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row(f"Ажилтан {n:03d}", start=date(2026, 1, 1), end=date(2026, 1, 2)) for n in range(120)])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert page.count("data-bar") == 100
    assert "Эхний 100-г харууллаа. Шүүлтүүрээр нарийвчилна уу." in page


def test_timeline_under_the_cap_has_no_over_cap_note(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row(f"Ажилтан {n:02d}", start=date(2026, 1, 1), end=date(2026, 1, 2)) for n in range(3)])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert "Шүүлтүүрээр нарийвчилна уу" not in page


def test_timeline_bar_positions_never_use_a_comma_decimal(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    rows = [
        _row("Ажилтан 01", start=date(2026, 1, 1), end=date(2026, 1, 10)),
        _row("Ажилтан 02", start=date(2026, 2, 13), end=date(2026, 3, 7)),
        _row("Ажилтан 03", start=date(2026, 5, 3), end=date(2026, 9, 29)),
    ]
    use_rows(rows)
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    tags = re.findall(r"<[a-z]+ [^>]*data-bar[^>]*>", page)
    assert len(tags) == 3
    styles = [re.search(r'style="([^"]*)"', tag).group(1) for tag in tags]  # type: ignore[union-attr]
    assert all("," not in style for style in styles)
    assert any("." in style for style in styles)  # the positions are fractions, written with a point


def test_timeline_bar_has_its_dates_as_a_title(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2026, 1, 1), end=date(2026, 1, 10))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert 'title="2026-01-01' in page
    assert "2026-01-10" in page


# ---- the per-viewer rules ----


@pytest.mark.parametrize("layout", ["timeline", "calendar"])
def test_hidden_salary_in_the_date_keys_gives_no_salary_and_no_option(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None], layout: str
) -> None:
    rows = [_row("Ажилтан 01", start=date(2026, 3, 15), end=date(2026, 3, 20), pay=SALARY)]
    use_rows(rows)
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": layout, "lby": "pay", "lby2": "pay", "lval": "pay:sum", "lmonth": "2026-03"})
    assert response.status_code == 200
    page = response.content.decode()
    assert str(SALARY) not in page
    assert mnt(Decimal(SALARY)) not in page
    assert "Цалин" not in page
    assert not re.search(r"\bpay\b", page)

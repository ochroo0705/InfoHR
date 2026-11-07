"""Header links for several sort keys: a plain click sorts by one column, Shift+click adds or flips a column."""

import html
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from accounts.models import User
from django.test import Client

from reports import staff_list
from reports.filters import Filters
from reports.table import build_table
from reports.views import _next_sort

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("current", "key", "append", "expected"),
    [
        ("", "name", False, "name"),  # a new column sorts ascending
        ("name", "name", False, "-name"),  # the same column again: descending
        ("-name", "name", False, "name"),  # and ascending again on the third click
        ("name,-age", "name", False, "name"),  # a plain click on one of several keys replaces them all
        ("name,-age", "dept", False, "dept"),  # a plain click on a third column replaces both keys
        ("", "name", True, "name"),  # Shift+click on an empty sort adds the column
        ("name", "age", True, "name,age"),  # a new column is added ascending, at the end
        ("name,-age", "dept", True, "name,-age,dept"),
        ("name,-age", "age", True, "name,age"),  # an existing column flips in place and keeps its place
        ("name,-age", "name", True, "-name,-age"),
        ("-name", "name", True, "name"),
        ("a,b,c,d,e", "f", True, "a,b,c,d,e"),  # at the five-key cap a new column changes nothing
        ("a,b,c,d,e", "a", True, "-a,b,c,d,e"),  # but an existing one still flips at the cap
    ],
)
def test_next_sort(current: str, key: str, append: bool, expected: str) -> None:
    assert _next_sort(current, key, append=append) == expected


def _header_addresses(page: str, attribute: str) -> list[str]:
    """The decoded addresses named by the header links' `attribute` (href or data-append)."""
    return [html.unescape(value) for value in re.findall(rf'{attribute}="([^"]*)"', page)]


def _sort_of(address: str) -> list[str]:
    return parse_qs(urlsplit(address).query).get("sort", [""])


def test_shift_click_addresses_keep_the_sort_and_add_a_column(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?cols=name&cols=age&cols=department&sort=name,-age").content.decode()
    appends = _header_addresses(page, "data-append")
    sorts = [_sort_of(address) for address in appends]
    assert ["-name,-age"] in sorts  # Shift+click on the name column flips it in place
    assert ["name,age"] in sorts  # Shift+click on the age column flips it in place
    assert ["name,-age,department"] in sorts  # Shift+click on the department column adds it at the end
    assert len(appends) == 3  # one per header: name, age, department


def test_arrows_show_order_only_with_two_or_more_keys(client: Client, login_hr: User) -> None:
    two = client.get("/reports/staff-list/?cols=name&cols=age&sort=name,-age").content.decode()
    assert "↑1" in two and "↓2" in two
    one = client.get("/reports/staff-list/?cols=name&cols=age&sort=name").content.decode()
    assert "↑1" not in one
    assert '<span aria-hidden="true">↑</span>' in one


def test_header_links_ignore_htmx_on_shift_click(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?cols=name&sort=name").content.decode()
    assert 'hx-trigger="click[!event.shiftKey]"' in page
    assert 'title="Shift+товшилт: нэмэлт эрэмбэ"' in page


def test_hidden_sort_key_is_dropped_from_marks_and_links(client: Client, login_hr: User) -> None:
    # bank needs view_salary, which the HR user lacks: it must not count, show, or appear in any link
    page = client.get("/reports/staff-list/?cols=name&cols=bank&sort=bank,name").content.decode()
    assert "↑2" not in page and "↓2" not in page  # one usable key: plain arrows only
    assert '<span aria-hidden="true">↑</span>' in page
    links = _header_addresses(page, "href") + _header_addresses(page, "data-append")
    assert links
    assert all("bank" not in _sort_of(address)[0] for address in links)
    assert all("bank" not in address for address in links)


def test_sanitised_sort_is_the_table_sort(hr_user: User) -> None:
    table = build_table(staff_list.REPORT, hr_user, Filters(columns=("name", "bank"), sort="bank,name"))
    assert table.filters.sort == "name"


def test_shift_click_inline_handler_on_header_link(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?cols=name&sort=name").content.decode()
    anchor = re.search(r"<a [^>]*data-append=[^>]*>", page)
    assert anchor is not None
    assert "shiftKey" in anchor.group(0)
    assert 'onclick="' in anchor.group(0)

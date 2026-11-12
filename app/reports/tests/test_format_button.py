"""The «Хэлбэр» button (footer totals, pinned columns, colour rules) is offered only where it does something."""

import pytest
from accounts.models import User
from django.test import Client

pytestmark = pytest.mark.django_db

FORMAT_URL = "reports/staff-list/format/"


def test_format_button_is_shown_in_the_table_layout(client: Client, login_hr: User) -> None:
    assert FORMAT_URL in client.get("/reports/staff-list/").content.decode()


@pytest.mark.parametrize("layout", ["chart", "pivot"])
def test_format_button_is_hidden_where_it_has_no_effect(client: Client, login_hr: User, layout: str) -> None:
    assert FORMAT_URL not in client.get(f"/reports/staff-list/?layout={layout}").content.decode()


def test_format_button_is_kept_for_board_layout(client: Client, login_hr: User) -> None:
    assert FORMAT_URL in client.get("/reports/staff-list/?layout=board").content.decode()

"""The employee page opens at one field (`#<tab>-<key>`, from the assistant's field answer; UI_RULES §2e).

The page script (static/js/employee_field_focus.js) finds the field by its `name` or `data-field`; these tests
check that the script is loaded once and that every target it looks for is in the page HTML.
"""

import pytest
from django.test import Client
from django.urls import reverse

from employees.models import Employee
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

WORK_KEYS = (
    "position",
    "department",
    "manager",
    "employee_type",
    "contract_type",
    "contract_no",
    "contract_start",
    "contract_end",
)


def _page(client: Client, employee: Employee) -> str:
    login_as(client, "HR")
    return client.get(reverse("employees:detail", args=[employee.pk])).content.decode()


def _tab(body: str, tab: str) -> str:
    """The HTML of one tab section: from its id to the next tab section (or the page end)."""
    start = body.index(f'id="tab-{tab}"')
    rest = body[start + 1 :]
    ends = [rest.find(f'id="tab-{other}"') for other in ("work", "personal", "salary")]
    ends = [pos for pos in ends if pos != -1]
    return body[start : start + 1 + (min(ends) if ends else len(rest))]


def test_detail_page_loads_field_focus_script_once(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert body.count("employee_field_focus.js") == 1


def test_work_tab_rows_carry_their_field_keys(client: Client, hired: Employee) -> None:
    work = _tab(_page(client, hired), "work")
    for key in WORK_KEYS:
        assert f'data-field="{key}"' in work, key


def test_personal_tab_phone_input_is_the_focus_target(client: Client, hired: Employee) -> None:
    personal = _tab(_page(client, hired), "personal")
    assert 'name="private_phone"' in personal


def test_hidden_topic_group_has_the_hooks_the_script_opens_it_with(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    personal = _tab(body, "personal")
    edu = personal.split('data-pgroup="edu"', 1)[1].split('data-pgroup="award"', 1)[0]
    assert "data-off" in personal.split('data-pgroup="edu"', 1)[1][:40]
    assert 'name="education_level"' in edu
    assert 'data-pgroup-link="edu"' in body


def test_save_posts_only_the_tab_part_of_the_hash(client: Client, hired: Employee) -> None:
    # The address can be #work-position (tab, then field key); the save sends the tab name only.
    body = _page(client, hired)
    assert "getElementById('emp-tab').value=location.hash.slice(1).split('-')[0];" in body
    assert "getElementById('emp-tab').value=location.hash.slice(1);" not in body

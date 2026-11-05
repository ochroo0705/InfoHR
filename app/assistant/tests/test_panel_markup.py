import re
from collections.abc import Callable

import pytest
from accounts.models import User
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.html import escape

from assistant.resolver import Candidate
from assistant.tables import Ask, TableAnswer

pytestmark = pytest.mark.django_db

ON = {"ASSISTANT_PROVIDER": "gemini", "ASSISTANT_API_KEY": "k", "ASSISTANT_MODEL": "m"}


def _render_assistant_on() -> str:
    return Template("{% load palette_extras %}{% assistant_on as a %}{{ a }}").render(Context())


@override_settings(ASSISTANT_PROVIDER="")
def test_assistant_on_follows_provider_setting() -> None:
    assert _render_assistant_on() == "False"


@override_settings(**ON)
def test_assistant_on_true_when_configured() -> None:
    assert _render_assistant_on() == "True"


# --- The docked panel and the floating button (base.html) ---


def _signed_in_page(client: Client, role_user: Callable[[str], User]) -> str:
    client.force_login(role_user("hr"))
    return client.get(reverse("employees:today")).content.decode()


def _panel_tag(body: str) -> str:
    match = re.search(r"<aside id=\"assistant-panel\"[^>]*>", body)
    assert match is not None
    return match.group(0)


def test_panel_markup_present_for_logged_in_user(client: Client, role_user: Callable[[str], User]) -> None:
    body = _signed_in_page(client, role_user)
    assert 'id="assistant-panel"' in body
    assert "data-assistant-thread" in body
    assert "data-assistant-new" in body
    assert "data-palette-input" in body
    assert "data-palette-open" in body  # the top bar's «Хайх» button stays
    assert "palette-template" not in body


@override_settings(**ON)
def test_fab_only_when_assistant_on(client: Client, role_user: Callable[[str], User]) -> None:
    body = _signed_in_page(client, role_user)
    assert "data-assistant-fab" in body
    assert 'data-ask-on="1"' in _panel_tag(body)


@override_settings(ASSISTANT_PROVIDER="")
def test_no_fab_when_assistant_off_but_panel_stays(client: Client, role_user: Callable[[str], User]) -> None:
    body = _signed_in_page(client, role_user)
    assert "data-assistant-fab" not in body
    assert 'id="assistant-panel"' in body
    assert 'data-ask-on="0"' in _panel_tag(body)


@override_settings(**ON)
def test_no_panel_or_fab_on_login_page(client: Client) -> None:
    body = client.get(reverse("login")).content.decode()
    assert 'id="assistant-panel"' not in body
    assert "data-assistant-fab" not in body


@override_settings(**ON)
def test_panel_hooks_all_present_on_hr_page(client: Client, role_user: Callable[[str], User]) -> None:
    body = _signed_in_page(client, role_user)
    for hook in (
        "data-assistant-close",
        "data-palette-results",
        "data-palette-failed",
        'aria-live="polite"',
        "data-palette-hint",
        "data-assistant-new",
        "data-assistant-thread",
        "data-ask-url",
        "data-ask-on",
    ):
        assert hook in body, hook
    fab = re.search(r"<button [^>]*data-assistant-fab[^>]*>", body)
    assert fab is not None
    assert 'aria-expanded="false"' in fab.group(0)
    assert 'aria-controls="assistant-panel"' in fab.group(0)


@override_settings(**ON)
def test_panel_but_no_fab_on_403_page(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("accountant"))
    response = client.get(reverse("leave:settings"))  # the leave settings are HR-only: a plain 403
    assert response.status_code == 403
    body = response.content.decode()
    assert "data-palette-open" in body  # the 403 page is base.html with its top bar
    assert 'id="assistant-panel"' in body  # Ctrl+K and the top bar's «Хайх» still work here
    assert "data-assistant-fab" not in body  # only the floating button is left out


# Print views never extend base.html, so this test guards that: a print view has no panel and no button.
# (The panel and the button also carry print:hidden, a second line of defence for the ordinary pages.)
@override_settings(**ON)
def test_no_fab_on_print_view(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    response = client.get(reverse("reports:print", args=["staff-list"]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "data-assistant-fab" not in body
    assert 'id="assistant-panel"' not in body


@override_settings(**ON)
def test_panel_but_no_fab_on_error_page(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    response = client.get("/no-such-page-for-the-panel/")
    assert response.status_code == 404
    body = response.content.decode()
    assert 'id="assistant-panel"' in body
    assert "data-assistant-fab" not in body


@override_settings(**ON)
def test_logout_form_posts_to_logout_path(client: Client, role_user: Callable[[str], User]) -> None:
    # palette.js clears the thread on a submit of form[action$="/logout/"]: a rename of the path must fail here.
    body = _signed_in_page(client, role_user)
    assert re.search(r'<form[^>]*action="/logout/"', body) is not None


def test_panel_does_not_use_scroll_lock_classes(client: Client, role_user: Callable[[str], User]) -> None:
    tag = _panel_tag(_signed_in_page(client, role_user))
    assert not ("inset-0" in tag and "z-50" in tag)  # input.css locks the page scroll for that pair


def test_thread_store_loads_before_palette(client: Client, role_user: Callable[[str], User]) -> None:
    body = _signed_in_page(client, role_user)
    assert "js/thread_store.js" in body
    assert body.index("js/thread_store.js") < body.index("js/palette.js")


# --- The panel hooks of a table answer (palette.js): follow-up buttons and the previous-answer context ---


def _table_fragment(ta: TableAnswer, choices: list[dict[str, str]] | None = None) -> str:
    return render_to_string("assistant/_table_answer.html", {"ta": ta, "choices": choices or []})


def _table(status: str, query: str, ask: Ask | None = None) -> TableAnswer:
    return TableAnswer(
        status=status,
        want="list",
        query=query,
        url="/reports/staff-list/",
        count=None if status != "list" else 1,
        chips=(),
        not_applied=(),
        ask=ask,
        rest=(),
        chart_kind="",
        chart_by="",
    )


def test_ask_fragment_has_follow_up_buttons_and_no_context() -> None:
    ask = Ask(param="department", label="Хэлтэс", candidates=(Candidate(id=1, name="Санхүү"),), more=False)
    choices = [{"name": "Санхүү", "body": "query=&param=department&id=1"}]
    html = _table_fragment(_table("ask", "", ask), choices)
    assert 'data-follow-url="' in html
    assert 'data-follow-label="Санхүү"' in html
    assert 'data-follow-body="query=&amp;param=department&amp;id=1"' in html
    assert "data-assistant-context" not in html  # a question has no answer context for the next question


def test_list_fragment_carries_its_query_as_context() -> None:
    query = "department=3&state=working"
    html = _table_fragment(_table("list", query))
    assert f'data-assistant-context="{escape(query)}"' in html
    assert "data-follow-url" not in html

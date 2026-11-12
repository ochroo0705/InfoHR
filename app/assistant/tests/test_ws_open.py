"""«Хүснэгт болгон нээх»: the ws_open view and the button on the SQL answer card.

No Firebird: the gate's switch and database seams are monkeypatched on assistant.sqlanswer, the catalogue seam is
assistant.ws_views._catalogue_views, and the checker's catalogue is assistant.ws_service.catalogue_for.
The card is rendered through the real `ask` view; the SQL answer itself is the `services._sql_answer` seam used by
test_sql_tool.py.
"""

from collections.abc import Iterator

import pytest
from accounts.models import User
from django.conf import settings
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from sqlcore.catalogue import Catalogue, Column, View

from assistant import services, sqlanswer, views as assistant_views, ws_service, ws_views
from assistant.models import HelpQuestion, Outcome, WorkspaceTab
from assistant.tests.test_sql_tool import GOOD_SQL, QUESTION, SqlPlanProvider, _plan, _ok, _refused
from assistant.ws_limits import MAX_TABS
from assistant.ws_service import new_tab

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
BUTTON = "Хүснэгт болгон нээх"


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate starts closed (switch off); the checker sees one view, so the stored SQL passes check_sql."""
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda user: (EMPLOYEES,))
    monkeypatch.setattr(ws_service, "catalogue_for", lambda user: CATALOGUE)


def open_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    cache.clear()


def _question(user: User, *, outcome: str = Outcome.SQL, sql: str = SQL) -> HelpQuestion:
    return HelpQuestion.objects.create(user=user, question="Ажилтнуудын жагсаалт", outcome=outcome, sql=sql)


def _open_url(question: HelpQuestion | int) -> str:
    pk = question if isinstance(question, int) else question.pk
    return reverse("assistant:ws_open", args=[pk])


def test_open_creates_tab_and_redirects(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("staff")
    question = _question(user)
    open_gate(monkeypatch)
    client.force_login(user)

    response = client.post(_open_url(question))

    assert response.status_code == 302
    tab = WorkspaceTab.objects.get(owner=user)
    assert response["Location"] == reverse("assistant:workspace_tab", args=[tab.pk])
    assert tab.source_id == question.pk
    assert tab.current().sql == SQL


def test_open_twice_reuses_the_same_tab(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("staff")
    question = _question(user)
    open_gate(monkeypatch)
    client.force_login(user)

    first = client.post(_open_url(question))
    second = client.post(_open_url(question))

    assert first["Location"] == second["Location"]
    assert WorkspaceTab.objects.filter(owner=user).count() == 1


def test_another_users_question_404(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = role_user("staff")
    intruder = role_user("staff")
    question = _question(owner)
    open_gate(monkeypatch)
    client.force_login(intruder)

    assert client.post(_open_url(question)).status_code == 404
    assert not WorkspaceTab.objects.filter(owner=intruder).exists()


def test_non_sql_question_404(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("staff")
    answered = _question(user, outcome=Outcome.ANSWERED)
    empty = _question(user, sql="")
    open_gate(monkeypatch)
    client.force_login(user)

    assert client.post(_open_url(answered)).status_code == 404
    assert client.post(_open_url(empty)).status_code == 404
    assert not WorkspaceTab.objects.filter(owner=user).exists()


def test_get_is_405(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("staff")
    question = _question(user)
    open_gate(monkeypatch)
    client.force_login(user)

    assert client.get(_open_url(question)).status_code == 405
    assert not WorkspaceTab.objects.filter(owner=user).exists()


def test_gate_off_404(db: None, client: Client, role_user) -> None:
    user = role_user("staff")
    question = _question(user)  # the switch stays off (autouse seam)
    client.force_login(user)

    assert client.post(_open_url(question)).status_code == 404
    assert not WorkspaceTab.objects.filter(owner=user).exists()


def test_anonymous_is_sent_to_login(db: None, client: Client, role_user) -> None:
    user = role_user("staff")
    question = _question(user)

    response = client.post(_open_url(question))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse(settings.LOGIN_URL))


def test_sql_that_no_longer_passes_the_checker_is_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    question = _question(user)
    monkeypatch.setattr(ws_service, "catalogue_for", lambda viewer: Catalogue(views=()))  # the view is gone now
    open_gate(monkeypatch)
    client.force_login(user)

    assert client.post(_open_url(question)).status_code == 404
    assert not WorkspaceTab.objects.filter(owner=user).exists()


def test_existing_tab_opens_even_at_the_tab_limit(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    question = _question(user)
    open_gate(monkeypatch)
    client.force_login(user)
    first = client.post(_open_url(question))  # the tab for this answer exists now
    for _ in range(MAX_TABS - 1):
        new_tab(user)  # the viewer is now at the tab limit
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS

    response = client.post(_open_url(question))

    assert response.status_code == 302
    assert response["Location"] == first["Location"]  # the reuse check comes before the limit
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS


def test_limit_reached_shows_message_and_redirects(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    question = _question(user)
    for _ in range(MAX_TABS):
        new_tab(user)
    open_gate(monkeypatch)
    client.force_login(user)

    response = client.post(_open_url(question), follow=True)

    assert response.status_code == 200  # the page renders; no 500
    assert response.redirect_chain[-1][0] == reverse("assistant:workspace")
    assert "Нээлттэй хүснэгт" in response.content.decode()
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS


def _answer_card(client: Client, monkeypatch: pytest.MonkeyPatch, sql_answer) -> str:
    """Ask one question through the real `ask` view; the SQL answer and the provider are the test seams."""
    monkeypatch.setattr(services, "_sql_answer", lambda asker, text, day, provider: sql_answer)
    monkeypatch.setattr(assistant_views, "get_provider", lambda: SqlPlanProvider(_plan()))
    return client.post(reverse("assistant:ask"), {"q": QUESTION}).content.decode()


def test_card_has_button_only_with_a_question_id_and_an_open_gate(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    client.force_login(user)

    # Gate closed: the SQL answer is logged (it has a question id) but the button stays hidden.
    html = _answer_card(client, monkeypatch, _ok())
    question = HelpQuestion.objects.filter(user=user, outcome=Outcome.SQL).latest("pk")
    assert "Зөв гэж тэмдэглэх" in html  # the verify button is there, so the card has its question id
    assert BUTTON not in html
    assert _open_url(question) not in html

    # Gate open: the same card now carries the button, whose data attribute holds this question's address. The card is a
    # plain button (no form, no CSRF token): the token is read live by palette.js, never stored in the thread.
    open_gate(monkeypatch)
    html = _answer_card(client, monkeypatch, _ok())
    question = HelpQuestion.objects.filter(user=user, outcome=Outcome.SQL).latest("pk")
    assert BUTTON in html
    assert f'data-ws-open-url="{_open_url(question)}"' in html
    assert "<form" not in html
    assert "csrfmiddlewaretoken" not in html
    # Hand-off mode: the panel shows no table, no SQL and no verify button; those are on the workspace page.
    assert GOOD_SQL not in html
    assert "Зөв гэж тэмдэглэх" not in html
    assert "<table" not in html


def test_refused_sql_card_has_no_button(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("hr")
    client.force_login(user)
    open_gate(monkeypatch)

    html = _answer_card(client, monkeypatch, _refused("no"))

    assert BUTTON not in html
    assert "/workspace/open/" not in html


def test_tab_opened_from_an_answer_starts_with_the_models_labels(db: None, role_user, monkeypatch: pytest.MonkeyPatch) -> None:
    from assistant.models import WorkspaceVersion
    from assistant.ws_service import open_from_question

    user = role_user("hr")
    open_gate(monkeypatch)
    question = HelpQuestion.objects.create(
        user=user, question=QUESTION, outcome=Outcome.SQL, sql=SQL, sql_labels='{"N": "Тоо"}'
    )
    tab = open_from_question(user, question)
    assert WorkspaceVersion.objects.get(tab=tab).labels == '{"N": "Тоо"}'

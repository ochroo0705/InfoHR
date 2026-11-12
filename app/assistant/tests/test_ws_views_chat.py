"""The workspace chat pane (Task 10): ws_chat, ws_ask and ws_undo in ws_views.py.

No Firebird and no model: the gate seams are patched on sqlanswer and ws_views, the host is a fake that ws_service
receives (HrHost is patched there), and the provider is a fake returned by ws_views.get_provider.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.urls import reverse
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, check_sql
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_service, ws_views
from assistant.ws_views import CHAT_EMPTY_TEXT, CHAT_TOO_LONG_TEXT
from assistant.models import WorkspaceMessage, WorkspaceTab
from assistant.ws_service import PROVIDER_LINE, REFINED_TEXT, REFUSED_LINE
from assistant.ws_sql import Spec, spec_to_json

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name"), Column("DEPT", "department")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
NEW_SQL = "SELECT ID, NAME, DEPT FROM GOV_EMPLOYEES"
BAD_SQL = "SELECT NAME FROM NO_SUCH_VIEW"
COLUMNS = ("ID", "NAME")
SETTINGS_ONE = spec_to_json(Spec(columns=("ID",)))
SETTINGS_TWO = spec_to_json(Spec(columns=("NAME",)))
ASK_URL_NAME = "assistant:ws_ask"


class FakeProvider:
    """Returns the queued replies in order and records every call (system, user)."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls.append((system, user))
        return self.replies.pop(0)


class FakeHost:
    """A host with one catalogue: every run answers the fixed columns and one row."""

    def __init__(self) -> None:
        self.execute_calls: list[CheckedQuery] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append(query)
        return Result(columns=COLUMNS, rows=(("1", "Aigerim"),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The gate is open for every user. A test may switch the setting off."""
    state: dict[str, object] = {"views": (EMPLOYEES,)}
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda user: state["views"])
    return state


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    fake = FakeHost()
    monkeypatch.setattr(ws_service, "HrHost", lambda: fake)
    return fake


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider | None) -> None:
    monkeypatch.setattr(ws_views, "get_provider", lambda: provider)


def _tab_with_version(user: Any, sql: str = SQL, settings: str = "") -> WorkspaceTab:
    tab = ws_service.new_tab(user, title="Ажилтнууд")
    ws_service.add_version(tab, "Ажилтнууд", sql, settings=settings)
    return tab


def _ask(client: Client, tab: WorkspaceTab, text: str) -> Any:
    return client.post(reverse(ASK_URL_NAME, args=[tab.pk]), {"q": text})


def _version_sqls(tab: WorkspaceTab) -> list[str]:
    return list(tab.versions.order_by("id").values_list("sql", flat=True))


def test_ask_adds_version_and_messages(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": NEW_SQL})
    _use_provider(monkeypatch, provider)
    client.force_login(user)

    response = _ask(client, tab, "Хэлтсийг нэм")

    assert response.status_code == 200
    assert response["HX-Trigger"] == "ws-table-changed"
    assert tab.versions.count() == 2
    assert tab.current().sql == check_sql(NEW_SQL, CATALOGUE).sql
    assert [m.text for m in WorkspaceMessage.objects.filter(tab=tab).order_by("id")] == [
        "Хэлтсийг нэм",
        REFINED_TEXT,
    ]
    content = response.content.decode()
    assert REFINED_TEXT in content
    assert "Хэлтсийг нэм" in content


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_question_400(
    db: None,
    client: Client,
    role_user,
    monkeypatch: pytest.MonkeyPatch,
    gate: dict[str, object],
    host: FakeHost,
    text: str,
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider()
    _use_provider(monkeypatch, provider)
    client.force_login(user)

    assert _ask(client, tab, text).status_code == 400
    assert client.post(reverse(ASK_URL_NAME, args=[tab.pk])).status_code == 400
    assert provider.calls == []
    assert WorkspaceMessage.objects.filter(tab=tab).count() == 0


def test_question_length_limit_is_500(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": NEW_SQL})
    _use_provider(monkeypatch, provider)
    client.force_login(user)

    assert _ask(client, tab, "я" * 501).status_code == 400
    assert provider.calls == []
    assert _ask(client, tab, "я" * 500).status_code == 200  # exactly 500 is allowed
    assert len(provider.calls) == 1


def test_provider_none_gives_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, None)
    client.force_login(user)

    assert _ask(client, tab, "Хэлтсийг нэм").status_code == 404
    assert tab.versions.count() == 1
    assert WorkspaceMessage.objects.filter(tab=tab).count() == 0


def test_other_users_tab_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    owner = role_user("staff")
    intruder = role_user("staff")
    tab = _tab_with_version(owner)
    provider = FakeProvider({"sql": NEW_SQL})
    _use_provider(monkeypatch, provider)
    client.force_login(intruder)

    assert client.get(reverse("assistant:ws_chat", args=[tab.pk])).status_code == 404
    assert _ask(client, tab, "Хэлтсийг нэм").status_code == 404
    assert client.post(reverse("assistant:ws_undo", args=[tab.pk])).status_code == 404

    assert provider.calls == []
    assert tab.versions.count() == 1
    assert WorkspaceMessage.objects.filter(tab=tab).count() == 0


def test_gate_off_gives_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    provider = FakeProvider({"sql": NEW_SQL})
    _use_provider(monkeypatch, provider)
    client.force_login(user)
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    cache.clear()  # the gate answer is cached per user

    assert client.get(reverse("assistant:ws_chat", args=[tab.pk])).status_code == 404
    assert _ask(client, tab, "Хэлтсийг нэм").status_code == 404
    assert client.post(reverse("assistant:ws_undo", args=[tab.pk])).status_code == 404
    assert provider.calls == []
    assert tab.versions.count() == 1


def test_undo_restores_previous_version_and_settings(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user, sql=SQL, settings=SETTINGS_ONE)
    ws_service.add_version(tab, "хоёр", NEW_SQL, settings=SETTINGS_TWO)
    client.force_login(user)

    response = client.post(reverse("assistant:ws_undo", args=[tab.pk]))

    assert response.status_code == 200
    assert response["HX-Trigger"] == "ws-table-changed"
    assert tab.versions.count() == 1
    current = tab.current()
    assert current.sql == SQL
    assert current.settings == SETTINGS_ONE


def test_failed_ask_shows_reason_and_keeps_table(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider({"sql": BAD_SQL}, {"sql": BAD_SQL}))
    client.force_login(user)

    response = _ask(client, tab, "Хэлтсийг нэм")

    assert response.status_code == 200
    assert "HX-Trigger" not in response
    assert REFUSED_LINE in response.content.decode()
    assert _version_sqls(tab) == [SQL]
    assert [m.text for m in WorkspaceMessage.objects.filter(tab=tab).order_by("id")] == [
        "Хэлтсийг нэм",
        REFUSED_LINE,
    ]


def test_message_text_is_escaped(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    client.force_login(user)

    content = _ask(client, tab, "<script>alert(1)</script>").content.decode()

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "<script>alert(1)</script>" not in content


def test_chat_shows_lines_sql_and_undo_only_with_two_versions(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="Нэгдүгээр асуулт")
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.ASSISTANT, text="Нэгдүгээр хариулт")
    client.force_login(user)
    url = reverse("assistant:ws_chat", args=[tab.pk])

    content = client.get(url).content.decode()
    assert "Нэгдүгээр асуулт" in content and "Нэгдүгээр хариулт" in content
    assert "SQL харах" in content
    assert "GOV_EMPLOYEES" in content  # the current SQL, folded in the details
    assert "Буцаах" not in content  # one version: nothing to undo

    ws_service.add_version(tab, "хоёр", NEW_SQL)
    assert "Буцаах" in client.get(url).content.decode()


def test_new_tab_phrase_is_not_special_cased(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    tabs_before = WorkspaceTab.objects.filter(owner=user).count()
    provider = FakeProvider({"sql": NEW_SQL})
    _use_provider(monkeypatch, provider)
    client.force_login(user)

    response = _ask(client, tab, "шинэ хүснэгт")

    assert response.status_code == 200
    assert len(provider.calls) == 1  # the line went to the model like any other
    assert "шинэ хүснэгт" in provider.calls[0][1]
    assert WorkspaceTab.objects.filter(owner=user).count() == tabs_before  # no new tab was made
    assert tab.versions.count() == 2


def test_ask_calls_refine_outside_any_atomic_block(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    """refine_tab locks the tab row and asks the model, so the view must not open a transaction around it. Checked by
    the number of open savepoints: the test's own transaction is the outer one and adds none, so a view-level
    transaction.atomic() would show here as one more."""
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    real_refine = ws_views.refine_tab
    seen: list[int] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(len(connection.savepoint_ids))
        return real_refine(*args, **kwargs)

    monkeypatch.setattr(ws_views, "refine_tab", spy)
    client.force_login(user)
    baseline = len(connection.savepoint_ids)

    assert _ask(client, tab, "Хэлтсийг нэм").status_code == 200
    assert seen == [baseline]


def test_first_question_in_empty_tab_refreshes_the_page(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    """The first question renames the tab; the heading and the tab strip only change on a full page load."""
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    _use_provider(monkeypatch, FakeProvider({"sql": SQL}))
    client.force_login(user)

    response = _ask(client, tab, "Нийт ажилтан")

    assert response.status_code == 200
    assert response["HX-Refresh"] == "true"
    tab.refresh_from_db()
    assert tab.title == "Нийт ажилтан"


def test_later_question_does_not_refresh_the_page(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    client.force_login(user)

    response = _ask(client, tab, "Хэлтсийг нэм")

    assert response.status_code == 200
    assert "HX-Refresh" not in response


def test_undo_with_one_version_changes_nothing(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user, sql=SQL, settings=SETTINGS_ONE)
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="Нэг мессеж")
    client.force_login(user)

    response = client.post(reverse("assistant:ws_undo", args=[tab.pk]))

    assert response.status_code == 200
    assert "HX-Trigger" not in response
    assert "Нэг мессеж" in response.content.decode()
    assert _version_sqls(tab) == [SQL]
    assert tab.current().settings == SETTINGS_ONE


@pytest.mark.parametrize(
    ("text", "message", "status"),
    [("", CHAT_EMPTY_TEXT, 400), ("я" * 501, CHAT_TOO_LONG_TEXT, 400)],
)
def test_refused_line_shows_a_visible_message(
    db: None,
    client: Client,
    role_user,
    monkeypatch: pytest.MonkeyPatch,
    gate: dict[str, object],
    host: FakeHost,
    text: str,
    message: str,
    status: int,
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider())
    client.force_login(user)

    response = _ask(client, tab, text)

    assert response.status_code == status
    assert response["X-Chat-Error"] == "1"
    assert message in response.content.decode()
    assert "Илгээх" in response.content.decode()  # the form comes back with the message


def test_provider_none_shows_a_visible_message_with_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, None)
    client.force_login(user)

    response = _ask(client, tab, "Хэлтсийг нэм")

    assert response.status_code == 404
    assert response["X-Chat-Error"] == "1"
    assert PROVIDER_LINE in response.content.decode()


def test_error_hook_is_on_the_chat_pane_not_the_form(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    """htmx 2 fires htmx:beforeSwap on the swap target (#ws-chat-pane), an ancestor of the form, so the X-Chat-Error
    hook must sit on the pane. String check only: the browser behaviour is not verified here."""
    user = role_user("staff")
    tab = _tab_with_version(user)
    client.force_login(user)

    page = client.get(reverse("assistant:workspace_tab", args=[tab.pk])).content.decode()
    pane_tag = re.search(r'<aside id="ws-chat-pane"[^>]*>', page)
    assert pane_tag is not None
    assert "X-Chat-Error" in pane_tag.group(0)
    assert page.count("X-Chat-Error") == 1

    fragment = client.get(reverse("assistant:ws_chat", args=[tab.pk])).content.decode()
    form_tag = re.search(r"<form method=\"post\" action=\"[^\"]*ask/\"[^>]*>", fragment)
    assert form_tag is not None
    assert "X-Chat-Error" not in form_tag.group(0)
    assert "X-Chat-Error" not in fragment


class CountingHost(FakeHost):
    """A FakeHost whose count runs (SELECT COUNT(*) AS N ...) answer the queued numbers, in order."""

    def __init__(self, *counts: int) -> None:
        super().__init__()
        self.counts = list(counts)

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        if "COUNT(*) AS N" in query.sql.upper():
            self.execute_calls.append(query)
            return Result(columns=("N",), rows=((self.counts.pop(0),),), truncated=False)
        return super().execute(user, query, limits)


def _counting_host(monkeypatch: pytest.MonkeyPatch, *counts: int) -> CountingHost:
    fake = CountingHost(*counts)
    monkeypatch.setattr(ws_service, "HrHost", lambda: fake)
    return fake


def test_reply_names_the_row_counts(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _counting_host(monkeypatch, 98, 12)  # the old version's rows, then the new version's
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    client.force_login(user)

    content = _ask(client, tab, "Хэлтсийг нэм").content.decode()

    assert WorkspaceMessage.objects.filter(tab=tab).order_by("id").last().text == "Хүснэгтийг шинэчиллээ: 98 → 12 мөр."
    assert "Хүснэгтийг шинэчиллээ: 98 → 12 мөр." in content
    assert "нэг ч мөр үлдсэнгүй" not in content


def test_zero_rows_after_a_refinement_shows_the_caution_line(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _counting_host(monkeypatch, 98, 0)
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    client.force_login(user)

    content = _ask(client, tab, "Зөвхөн удирдлага").content.decode()

    assert "Хүснэгтийг шинэчиллээ: 98 → 0 мөр." in content
    assert "нэг ч мөр үлдсэнгүй" in content
    assert "«Буцаах» товчоор" in content  # two versions now: the caution line points at undo
    # The caution belongs to the answer that caused it: a plain reload of the pane does not repeat it.
    assert "нэг ч мөр үлдсэнгүй" not in client.get(reverse("assistant:ws_chat", args=[tab.pk])).content.decode()


def test_failed_count_falls_back_to_the_plain_line(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    """FakeHost answers a count run with text, which is not a count: the line is written without numbers."""
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, FakeProvider({"sql": NEW_SQL}))
    client.force_login(user)

    content = _ask(client, tab, "Хэлтсийг нэм").content.decode()

    assert WorkspaceMessage.objects.filter(tab=tab).order_by("id").last().text == REFINED_TEXT
    assert "нэг ч мөр үлдсэнгүй" not in content


def test_undo_stores_a_line_with_the_row_count(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    ws_service.add_version(tab, "хоёр", NEW_SQL)
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="хоёр")
    _counting_host(monkeypatch, 98)
    client.force_login(user)

    content = client.post(reverse("assistant:ws_undo", args=[tab.pk])).content.decode()

    assert [m.text for m in WorkspaceMessage.objects.filter(tab=tab).order_by("id")] == [
        "хоёр",
        "Өмнөх хувилбар руу буцлаа: 98 мөр.",
    ]
    assert "Өмнөх хувилбар руу буцлаа: 98 мөр." in content


def test_undo_with_one_version_stores_no_line(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    client.force_login(user)

    client.post(reverse("assistant:ws_undo", args=[tab.pk]))

    assert WorkspaceMessage.objects.filter(tab=tab).count() == 0


def test_refused_line_comes_back_in_the_box(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user)
    _use_provider(monkeypatch, None)
    client.force_login(user)

    content = _ask(client, tab, 'Хэлтсийг "нэм" <b>').content.decode()

    assert 'value="Хэлтсийг &quot;нэм&quot; &lt;b&gt;"' in content  # kept, and escaped


def test_chat_fragment_carries_the_waiting_parts(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    """String check only: workspace.js copies the template into the log while a line is on its way."""
    user = role_user("staff")
    tab = _tab_with_version(user)
    ws_service.add_version(tab, "хоёр", NEW_SQL)
    client.force_login(user)

    content = client.get(reverse("assistant:ws_chat", args=[tab.pk])).content.decode()

    assert "data-ws-pending-tpl" in content and "Боловсруулж байна…" in content
    assert " data-ws-ask" in content and " data-ws-undo" in content
    assert "Хувилбар 2" in content
    assert "анхны байдалд нь оруулна" in content  # the hint: a new question resets the table tools
    assert 'value=""' in content  # no draft on a plain load


def test_chat_offers_verify_only_for_the_source_answer_with_one_version(
    db: None, client: Client, role_user
) -> None:
    from assistant.models import HelpQuestion, Outcome, VerifiedQuery, WorkspaceVersion
    from assistant.ws_views import _chat_context

    user = role_user("hr")
    question = HelpQuestion.objects.create(
        user=user, question="Хэлтсээр", outcome=Outcome.SQL, sql="SELECT 1 FROM GOV_EMPLOYEES"
    )
    tab = WorkspaceTab.objects.create(owner=user, title="Хэлтсээр", source=question)
    WorkspaceVersion.objects.create(tab=tab, question="Хэлтсээр", sql="SELECT 1 FROM GOV_EMPLOYEES")
    assert _chat_context(tab)["verify_id"] == question.pk
    assert _chat_context(tab)["verified"] is False
    VerifiedQuery.objects.create(question="q", sql="SELECT 1", views="", source=question, proposed_by=user)
    assert _chat_context(tab)["verified"] is True
    WorkspaceVersion.objects.create(tab=tab, question="өөр", sql="SELECT 2 FROM GOV_EMPLOYEES")
    assert _chat_context(tab)["verify_id"] is None

"""Tests for the Claude adapter and the admin-console settings (provider, key, model, timeout)."""

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from assistant import config
from assistant.catalog import MODELS
from assistant.entries import ENTRIES
from assistant.models import AssistantSettings
from assistant.plan import Plan
from assistant.prompt import JSON_REPLY, question_block
from assistant.providers import CLAUDE_URL, Choice, ClaudeProvider, ProviderError, get_provider, is_enabled
from assistant.tests.helpers import fake_plan

PASSWORD = "Test-pass-1"  # noqa: S105
SECRET = "sk-ant-test-secret"  # noqa: S105
QUESTION = "ажилтанд чөлөө яаж оруулах вэ"
PAGE = reverse("admin:assistant_assistantsettings_change", args=[1])


def _reply(text: str) -> bytes:
    return json.dumps({"content": [{"type": "text", "text": text}]}).encode()


class FakePost:
    def __init__(self, reply: bytes | None = None, exc: BaseException | None = None) -> None:
        self.reply, self.exc = reply, exc
        self.calls: list[tuple[str, dict[str, Any], dict[str, str], int]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: int) -> bytes:
        self.calls.append((url, json.loads(body), headers, timeout))
        if self.exc is not None:
            raise self.exc
        assert self.reply is not None
        return self.reply


def _claude(post: FakePost) -> ClaudeProvider:
    return ClaudeProvider(api_key=SECRET, model="claude-haiku-5-5", timeout=7, post=post)


def test_claude_choice_parsed() -> None:
    post = FakePost(_reply('{"entry":"leave.record","also":"","lead":"Ингэж бүртгэнэ."}'))
    assert _claude(post).choose(QUESTION, ENTRIES) == Choice("leave.record", "", "Ингэж бүртгэнэ.")


def test_claude_tolerates_text_around_the_object() -> None:
    post = FakePost(_reply('Here: ```json\n{"entry":"","also":"","lead":""}\n```'))
    assert _claude(post).choose(QUESTION, ENTRIES) == Choice("", "", "")


def test_claude_request_shape() -> None:
    post = FakePost(_reply('{"entry":"","also":"","lead":""}'))
    _claude(post).choose(QUESTION, ENTRIES)
    url, body, headers, timeout = post.calls[0]
    assert url == CLAUDE_URL
    assert headers["x-api-key"] == SECRET
    assert headers["anthropic-version"]
    assert timeout == 7
    assert body["model"] == "claude-haiku-5-5"
    assert "temperature" not in body  # newer Claude models reject the parameter (HTTP 400)
    assert body["system"].endswith(JSON_REPLY)
    assert body["messages"] == [{"role": "user", "content": question_block(QUESTION)}]


@pytest.mark.parametrize(
    "reply", [b"not json", _reply("no object here"), _reply('{"entry": 5, "also": "", "lead": ""}')]
)
def test_claude_bad_reply_is_provider_error(reply: bytes) -> None:
    with pytest.raises(ProviderError):
        _claude(FakePost(reply)).choose(QUESTION, ENTRIES)


def test_claude_http_error_keeps_status_but_not_the_key() -> None:
    err = urllib.error.HTTPError(CLAUDE_URL, 401, "bad " + SECRET, Message(), None)
    with pytest.raises(ProviderError, match="HTTP 401") as info:
        _claude(FakePost(exc=err)).choose(QUESTION, ENTRIES)
    assert SECRET not in str(info.value)
    assert info.value.__cause__ is None


def test_claude_network_error_is_provider_error() -> None:
    with pytest.raises(ProviderError):
        _claude(FakePost(exc=TimeoutError("slow"))).choose(QUESTION, ENTRIES)


def test_every_listed_model_belongs_to_a_known_provider() -> None:
    assert set(MODELS) == {"claude", "gemini", "groq"}
    assert all(models for models in MODELS.values())


# --- the live configuration ------------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_env_is_used_until_the_row_is_saved(settings: Any) -> None:
    settings.ASSISTANT_PROVIDER, settings.ASSISTANT_API_KEY = "claude", "k"
    settings.ASSISTANT_MODEL, settings.ASSISTANT_TIMEOUT = "claude-haiku-5-5", 9
    assert config.current() == config.AssistantConfig("claude", "k", "claude-haiku-5-5", 9)
    assert is_enabled()


@pytest.mark.django_db
def test_saved_row_overrides_env(settings: Any) -> None:
    settings.ASSISTANT_PROVIDER, settings.ASSISTANT_API_KEY = "claude", "env-key"
    settings.ASSISTANT_MODEL = "claude-haiku-5-5"
    AssistantSettings.objects.create(
        pk=1, provider="groq", api_key="db-key", model="llama-3.3-70b-versatile", timeout=20
    )
    assert config.current() == config.AssistantConfig("groq", "db-key", "llama-3.3-70b-versatile", 20)
    provider = get_provider()
    assert provider is not None and provider.name == "groq"


@pytest.mark.django_db
def test_saved_row_with_no_provider_switches_the_assistant_off(settings: Any) -> None:
    settings.ASSISTANT_PROVIDER, settings.ASSISTANT_API_KEY = "claude", "k"
    settings.ASSISTANT_MODEL = "claude-haiku-5-5"
    AssistantSettings.objects.create(pk=1, provider="", api_key="k", model="", timeout=15)
    assert not is_enabled()
    assert get_provider() is None


@pytest.mark.django_db
def test_get_provider_builds_claude() -> None:
    AssistantSettings.objects.create(pk=1, provider="claude", api_key="k", model="claude-haiku-5-5", timeout=11)
    provider = get_provider()
    assert isinstance(provider, ClaudeProvider)
    assert provider.model == "claude-haiku-5-5"


# --- the admin page --------------------------------------------------------------------------------------------------


def _login(client: Client, group: str | None) -> None:
    user = User.objects.create_user(f"set_{group}", password=PASSWORD, is_staff=True)
    if group is not None:
        user.groups.add(Group.objects.get(name=group))
    client.force_login(user)


def _form(**over: Any) -> dict[str, Any]:
    data = {"provider": "claude", "api_key": SECRET, "model": "claude-sonnet-5-5", "timeout": "20"}
    data.update(over)
    return data


@pytest.mark.django_db
def test_admin_group_can_open_and_save(client: Client) -> None:
    _login(client, "Admin")
    assert client.get(PAGE).status_code == 200
    response = client.post(PAGE, _form())
    assert response.status_code == 302
    row = AssistantSettings.objects.get(pk=1)
    assert (row.provider, row.api_key, row.model, row.timeout) == ("claude", SECRET, "claude-sonnet-5-5", 20)


@pytest.mark.django_db
def test_changelist_goes_straight_to_the_page(client: Client) -> None:
    _login(client, "Admin")
    response = client.get(reverse("admin:assistant_assistantsettings_changelist"))
    assert response.status_code == 302 and response["Location"] == PAGE


@pytest.mark.django_db
def test_other_roles_are_refused(client: Client) -> None:
    _login(client, "HR")
    assert client.get(PAGE).status_code == 403
    assert client.post(PAGE, _form()).status_code == 403
    assert not AssistantSettings.objects.exists()


@pytest.mark.django_db
def test_opening_the_page_writes_nothing(client: Client, settings: Any) -> None:
    settings.ASSISTANT_PROVIDER, settings.ASSISTANT_API_KEY = "claude", "env-key"
    settings.ASSISTANT_MODEL = "claude-haiku-5-5"
    _login(client, "Admin")
    html = client.get(PAGE).content.decode()
    assert not AssistantSettings.objects.exists()
    assert "env-key" not in html
    assert "Түлхүүр хадгалагдсан" in html  # the .env key is known, only its value is hidden


@pytest.mark.django_db
def test_first_save_keeps_the_env_key_when_the_box_is_empty(client: Client, settings: Any) -> None:
    settings.ASSISTANT_PROVIDER, settings.ASSISTANT_API_KEY = "claude", "env-key"
    settings.ASSISTANT_MODEL = "claude-haiku-5-5"
    _login(client, "Admin")
    assert client.post(PAGE, _form(api_key="")).status_code == 302
    assert AssistantSettings.objects.get(pk=1).api_key == "env-key"


@pytest.mark.django_db
def test_saved_key_is_never_rendered_and_empty_box_keeps_it(client: Client) -> None:
    AssistantSettings.objects.create(pk=1, provider="claude", api_key=SECRET, model="claude-haiku-5-5", timeout=15)
    _login(client, "Admin")
    assert SECRET not in client.get(PAGE).content.decode()
    assert client.post(PAGE, _form(api_key="", timeout="30")).status_code == 302
    row = AssistantSettings.objects.get(pk=1)
    assert (row.api_key, row.timeout) == (SECRET, 30)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"model": ""}, "model"),
        ({"model": "bad model!"}, "model"),
        ({"model": "x" * 61}, "model"),
        ({"api_key": ""}, "api_key"),  # nothing saved and nothing typed
        ({"timeout": "2"}, "timeout"),
        ({"timeout": "61"}, "timeout"),
        ({"timeout": "abc"}, "timeout"),
        ({"provider": "openai"}, "provider"),
    ],
)
def test_invalid_input_is_refused(client: Client, settings: Any, over: dict[str, Any], field: str) -> None:
    settings.ASSISTANT_API_KEY = ""  # no .env key to fall back on
    _login(client, "Admin")
    response = client.post(PAGE, _form(**over))
    assert response.status_code == 200
    assert field in response.context["adminform"].form.errors
    assert not AssistantSettings.objects.exists()


@pytest.mark.django_db
def test_provider_off_needs_no_key_or_model(client: Client) -> None:
    _login(client, "Admin")
    assert client.post(PAGE, _form(provider="", api_key="", model="")).status_code == 302
    assert not is_enabled()


@pytest.mark.django_db
def test_page_suggests_every_known_model(client: Client) -> None:
    _login(client, "Admin")
    html = client.get(PAGE).content.decode()
    for provider, models in MODELS.items():
        assert f'<datalist id="assistant-models-{provider}">' in html
        for model_id, _label in models:
            assert f'<option value="{model_id}">' in html


@pytest.mark.django_db
def test_a_model_not_in_the_list_can_be_typed(client: Client) -> None:
    _login(client, "Admin")
    assert client.post(PAGE, _form(model="claude-some-new-model-9")).status_code == 302
    assert AssistantSettings.objects.get(pk=1).model == "claude-some-new-model-9"


@pytest.mark.django_db
def test_model_is_trimmed(client: Client) -> None:
    _login(client, "Admin")
    client.post(PAGE, _form(model="  claude-haiku-5-5 "))
    assert AssistantSettings.objects.get(pk=1).model == "claude-haiku-5-5"


# --- why a call failed, visible in the admin log ----------------------------------------------------------------------


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(CLAUDE_URL, code, "x", Message(), io.BytesIO(body.encode()))


def test_claude_http_error_carries_the_providers_message() -> None:
    err = _http_error(401, '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}')
    with pytest.raises(ProviderError) as info:
        _claude(FakePost(exc=err)).choose(QUESTION, ENTRIES)
    assert str(info.value) == "HTTP 401: invalid x-api-key"


def test_provider_message_never_contains_the_key() -> None:
    err = _http_error(400, json.dumps({"error": {"message": f"bad key {SECRET} here"}}))
    with pytest.raises(ProviderError) as info:
        _claude(FakePost(exc=err)).choose(QUESTION, ENTRIES)
    assert SECRET not in str(info.value)


def test_non_http_failure_names_the_exception_type() -> None:
    with pytest.raises(ProviderError, match="TimeoutError"):
        _claude(FakePost(exc=TimeoutError("slow"))).choose(QUESTION, ENTRIES)


@pytest.mark.django_db
def test_failed_question_logs_the_reason(client: Client) -> None:
    from datetime import date

    from assistant.models import HelpQuestion, Outcome
    from assistant.services import answer

    class Failing:
        name, model = "claude", "claude-haiku-5-5"

        def choose(self, *args: Any, **kwargs: Any) -> Choice:
            raise ProviderError("HTTP 401: invalid x-api-key")

        def plan(
            self,
            question: str,
            entries: Any,
            words: Any,
            phrases: Any,
            today: Any,
            previous: str = "",
            refusals: Any = (),
            table_examples: Any = (),
            field_hints: Any = (),
        ) -> Plan:
            return fake_plan(self, question, entries)

    user = User.objects.create_superuser("asker", password=PASSWORD)
    result = answer(user, QUESTION, date(2026, 11, 5), Failing())
    assert result.outcome == Outcome.ERROR
    row = HelpQuestion.objects.get()
    assert row.error == "HTTP 401: invalid x-api-key"
    _login(client, "Admin")
    html = client.get(reverse("admin:assistant_helpquestion_changelist")).content.decode()
    assert "HTTP 401: invalid x-api-key" in html


# --- «Холболт шалгах» -------------------------------------------------------------------------------------------------

TEST_URL = reverse("admin:assistant_assistantsettings_test")


class _Stub:
    name, model = "claude", "claude-haiku-5-5"

    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc

    def choose(self, *args: Any, **kwargs: Any) -> Choice:
        if self.exc is not None:
            raise self.exc
        return Choice("", "", "")

    def plan(
        self,
        question: str,
        entries: Any,
        words: Any,
        phrases: Any,
        today: Any,
        previous: str = "",
        refusals: Any = (),
        table_examples: Any = (),
        field_hints: Any = (),
    ) -> Plan:
        return fake_plan(self, question, entries)


@pytest.mark.django_db
def test_connection_ok_saves_nothing(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("assistant.check.build_provider", lambda cfg: _Stub())
    _login(client, "Admin")
    data = client.post(TEST_URL, _form()).json()
    assert data["ok"] is True and "Холбогдлоо" in data["message"]
    assert not AssistantSettings.objects.exists()


@pytest.mark.django_db
def test_connection_failure_shows_the_reason(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "assistant.check.build_provider", lambda cfg: _Stub(ProviderError("HTTP 401: invalid x-api-key"))
    )
    _login(client, "Admin")
    data = client.post(TEST_URL, _form()).json()
    assert data == {"ok": False, "message": "Холбогдсонгүй: HTTP 401: invalid x-api-key"}


@pytest.mark.django_db
def test_connection_uses_the_saved_key_when_the_box_is_empty(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    AssistantSettings.objects.create(pk=1, provider="claude", api_key=SECRET, model="claude-haiku-5-5", timeout=15)
    seen: list[config.AssistantConfig] = []

    def build(cfg: config.AssistantConfig) -> _Stub:
        seen.append(cfg)
        return _Stub()

    monkeypatch.setattr("assistant.check.build_provider", build)
    _login(client, "Admin")
    client.post(TEST_URL, _form(api_key="", timeout="9"))
    assert seen[0].api_key == SECRET and seen[0].timeout == 9


@pytest.mark.django_db
def test_connection_reports_form_problems_and_provider_off(client: Client, settings: Any) -> None:
    settings.ASSISTANT_API_KEY = ""
    _login(client, "Admin")
    bad = client.post(TEST_URL, _form(model="bad model!")).json()
    assert bad["ok"] is False and "Загвар" in bad["message"]
    off = client.post(TEST_URL, _form(provider="", api_key="", model="")).json()
    assert off["ok"] is False and "унтарсан" in off["message"]


@pytest.mark.django_db
def test_connection_needs_post_and_the_change_permission(client: Client) -> None:
    _login(client, "Admin")
    assert client.get(TEST_URL).status_code == 405
    other = Client()
    _login(other, "HR")
    assert other.post(TEST_URL, _form()).status_code == 403


@pytest.mark.django_db
def test_page_has_the_button(client: Client) -> None:
    _login(client, "Admin")
    assert "Холболт шалгах" in client.get(PAGE).content.decode()

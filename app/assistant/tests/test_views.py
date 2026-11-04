"""Tests for the ask view: login, method, blank and off cases, the answer card, and escaping."""

from collections.abc import Callable, Sequence

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from assistant import views
from assistant.entries import HelpEntry
from assistant.models import HelpQuestion, Outcome
from assistant.providers import Choice, ProviderError
from assistant.services import ASK_PER_HOUR

URL = reverse("assistant:ask")


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, choice: Choice) -> None:
        self.choice = choice

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        return self.choice


def test_anonymous_redirects_to_login(client: Client) -> None:
    response = client.post(URL, {"q": "яаж"})
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_get_is_405(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    assert client.get(URL).status_code == 405


@pytest.mark.django_db
def test_blank_question_400(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "  "}).status_code == 400


@pytest.mark.django_db
def test_ask_404_when_off(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: None)
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "яаж"}).status_code == 404


@pytest.mark.django_db
def test_answer_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө бүртгэх хэсэг."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    response = client.post(URL, {"q": "ажилтанд чөлөө яаж оруулах вэ"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "Чөлөө бүртгэх" in body
    assert "Нээх →" in body
    assert 'href="/leave/new/"' in body
    assert "data-palette-modal" in body
    assert 'role="status"' in body


@pytest.mark.django_db
def test_none_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="", also="", lead=""))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    response = client.post(URL, {"q": "пицца захиалах вэ"})
    body = response.content.decode()
    assert "Энэ асуултад хариулт олдсонгүй" in body
    assert "data-palette-item" not in body


@pytest.mark.django_db
def test_lead_and_question_are_escaped(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="<script>x</script>"))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "<script>x</script> чөлөө яаж вэ"}).content.decode()
    assert "&lt;script&gt;" in body
    assert "<script>x" not in body


class ErrorProvider:
    name = "fake"
    model = "fake-model"

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise ProviderError("boom")


@pytest.mark.django_db
def test_csrf_required(role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: FakeProvider(Choice(entry="", also="", lead="")))
    client = Client(enforce_csrf_checks=True)
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "яаж"}).status_code == 403


@pytest.mark.django_db
def test_error_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: ErrorProvider())
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "яаж чөлөө бүртгэх вэ"}).content.decode()
    assert "Хариулт авч чадсангүй. Дахин оролдоно уу." in body


@pytest.mark.django_db
def test_limited_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    user = role_user("hr")
    for _ in range(ASK_PER_HOUR):
        HelpQuestion.objects.create(user=user, question="чөлөө", outcome=Outcome.ANSWERED)
    client.force_login(user)
    body = client.post(URL, {"q": "чөлөө яаж авах вэ"}).content.decode()
    assert "Нэг цагт 20-оос олон асуулт асуух боломжгүй" in body

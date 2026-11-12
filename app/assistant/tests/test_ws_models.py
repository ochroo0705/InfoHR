"""The workspace models: a tab keeps its versions, its current version is the last one, and rows go with the owner."""

import pytest
from accounts.models import User

from assistant.models import HelpQuestion, WorkspaceMessage, WorkspaceTab, WorkspaceVersion


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user("ws_owner", password="x-long-pass-123")  # noqa: S106


def test_tab_current_is_last_version(owner: User) -> None:
    tab = WorkspaceTab.objects.create(owner=owner, title="Ажилчид")
    assert tab.current() is None
    WorkspaceVersion.objects.create(tab=tab, question="q1", sql="SELECT 1 FROM t")
    second = WorkspaceVersion.objects.create(tab=tab, question="q2", sql="SELECT 2 FROM t", settings="{}")
    assert tab.current() == second
    assert second.settings == "{}"


def test_deleting_user_deletes_tabs(owner: User) -> None:
    tab = WorkspaceTab.objects.create(owner=owner, title="Таб")
    WorkspaceVersion.objects.create(tab=tab, question="q", sql="SELECT 1 FROM t")
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="hi")
    owner.delete()
    assert not WorkspaceTab.objects.filter(pk=tab.pk).exists()
    assert not WorkspaceVersion.objects.exists()
    assert not WorkspaceMessage.objects.exists()


def test_deleting_source_question_keeps_tab(owner: User) -> None:
    source = HelpQuestion.objects.create(question="асуулт", outcome="answered")
    tab = WorkspaceTab.objects.create(owner=owner, title="Таб", source=source)
    source.delete()
    tab.refresh_from_db()
    assert tab.source is None

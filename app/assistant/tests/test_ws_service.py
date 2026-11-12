import pytest
from assistant import ws_service
from assistant.models import HelpQuestion, Outcome, WorkspaceMessage, WorkspaceTab, WorkspaceVersion
from assistant.ws_limits import MAX_TABS, MAX_VERSIONS
from sqlcore.catalogue import Catalogue, Column, View

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name"), Column("DEPT", "department")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"


@pytest.fixture(autouse=True)
def _fixed_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_service, "catalogue_for", lambda user: CATALOGUE)


def _question(user, *, sql: str = SQL, outcome: str = Outcome.SQL, text: str = "Нийт ажилтан") -> HelpQuestion:
    return HelpQuestion.objects.create(user=user, question=text, outcome=outcome, sql=sql)


def test_open_twice_reuses_tab(db: None, role_user) -> None:
    user = role_user("staff")
    question = _question(user)

    first = ws_service.open_from_question(user, question)
    second = ws_service.open_from_question(user, question)

    assert first.pk == second.pk
    assert WorkspaceTab.objects.filter(owner=user).count() == 1
    assert first.current().sql == SQL


def test_open_someone_elses_question_refused(db: None, role_user) -> None:
    owner = role_user("staff")
    other = role_user("staff")
    question = _question(owner)

    with pytest.raises(PermissionError):
        ws_service.open_from_question(other, question)
    assert WorkspaceTab.objects.filter(owner=other).count() == 0


def test_open_refuses_non_sql_question(db: None, role_user) -> None:
    user = role_user("staff")
    question = _question(user, outcome=Outcome.ANSWERED, sql=SQL)

    with pytest.raises(PermissionError):
        ws_service.open_from_question(user, question)
    assert WorkspaceTab.objects.filter(owner=user).count() == 0
    assert WorkspaceVersion.objects.count() == 0


def test_tab_limit(db: None, role_user) -> None:
    user = role_user("staff")
    for _ in range(MAX_TABS):
        ws_service.new_tab(user)

    with pytest.raises(ws_service.WorkspaceLimit) as excinfo:
        ws_service.new_tab(user)

    assert str(excinfo.value) == f"Нээлттэй хүснэгт {MAX_TABS} байна. Нэгийг хаагаад дахин оролдоно уу."
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS


def test_tab_limit_still_reuses_existing_tab(db: None, role_user) -> None:
    user = role_user("staff")
    question = _question(user)
    ws_service.open_from_question(user, question)
    for _ in range(MAX_TABS - 1):
        ws_service.new_tab(user)

    reused = ws_service.open_from_question(user, question)

    assert reused.source_id == question.pk
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS


def test_version_limit_drops_oldest(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    for number in range(MAX_VERSIONS + 2):
        ws_service.add_version(tab, question=f"q{number}", sql=f"SELECT {number} FROM GOV_EMPLOYEES")

    remaining = list(tab.versions.order_by("id").values_list("question", flat=True))

    assert len(remaining) == MAX_VERSIONS
    assert remaining[0] == "q2"
    assert remaining[-1] == f"q{MAX_VERSIONS + 1}"


def test_undo_keeps_first_version(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    assert ws_service.undo(tab) is None

    first = ws_service.add_version(tab, question="first", sql=SQL)
    assert ws_service.undo(tab) == first
    assert tab.versions.count() == 1

    ws_service.add_version(tab, question="second", sql=SQL)
    back = ws_service.undo(tab)

    assert back == first
    assert WorkspaceVersion.objects.filter(tab=tab).count() == 1


def test_unsafe_sql_is_not_stored(db: None, role_user) -> None:
    user = role_user("staff")
    question = _question(user, sql="DELETE FROM GOV_EMPLOYEES")

    with pytest.raises(PermissionError):
        ws_service.open_from_question(user, question)
    assert WorkspaceTab.objects.filter(owner=user).count() == 0
    assert WorkspaceVersion.objects.count() == 0


def test_rename_and_close(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)

    ws_service.rename(tab, "x" * 200)
    tab.refresh_from_db()
    assert len(tab.title) == ws_service.TITLE_MAX

    assert [t.pk for t in ws_service.tabs_of(user)] == [tab.pk]
    ws_service.close(tab)
    assert ws_service.tabs_of(user) == []


def test_close_deletes_versions_and_messages(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    ws_service.add_version(tab, question="first", sql=SQL)
    WorkspaceMessage.objects.create(tab=tab, role=WorkspaceMessage.Role.USER, text="строка")

    ws_service.close(tab)

    assert not WorkspaceTab.objects.filter(pk=tab.pk).exists()
    assert not WorkspaceVersion.objects.filter(tab_id=tab.pk).exists()
    assert not WorkspaceMessage.objects.filter(tab_id=tab.pk).exists()


def test_close_of_an_already_deleted_tab_is_quiet(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    WorkspaceTab.objects.filter(pk=tab.pk).delete()  # gone under our feet, as if another request closed it

    ws_service.close(tab)  # must not raise

    assert ws_service.tabs_of(user) == []


def test_add_version_stores_labels(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    labels = '{"ACTIVE_COUNT": "Ажилтны тоо"}'

    version = ws_service.add_version(tab, question="first", sql=SQL, labels=labels)

    version.refresh_from_db()
    assert version.labels == labels
    assert ws_service.add_version(tab, question="second", sql=SQL).labels == ""


def test_carried_labels_keep_old_and_take_new() -> None:
    import json

    from assistant.ws_service import _carried_labels

    merged = json.loads(_carried_labels('{"A": "Нэг", "B": "Хоёр"}', '{"B": "Шинэ"}'))
    assert merged == {"A": "Нэг", "B": "Шинэ"}
    assert json.loads(_carried_labels("not json", "")) == {}

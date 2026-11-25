"""GET /api/v1/recruitment: the vacancy list, the vacancy page, the vacancy form options, the budget line, the candidate
page and the purge list, as the React pages read them. The rules come from recruitment.services; these tests pin the
API's shape, its rights, its paging, the 404 of a hidden object, and the module gate (404 on every route while off)."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from accounts import modules
from accounts.models import AccessScope, User
from config import batching
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from employees import daily_sync
from employees.models import CompanySettings
from employees.services import macs_writes
from macs.models import Branch, Employee
from recruitment.models import Candidate, CandidateFile, Stage, Vacancy, VacancyStatus
from recruitment.services import candidate_page, pipeline, slot_line, vacancy_page
from recruitment.tests.conftest import make_manager, make_vacancy

from api.recruitment import _recruitment_auth, recruitment_router

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BASE = "/api/v1/recruitment"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
LIST_KEYS = {"status", "q", "rows", "next_offset", "can_manage", "empty_text"}
ROW_KEYS = {
    "id",
    "title",
    "position",
    "department",
    "hiring_manager",
    "status",
    "status_label",
    "headcount",
    "deadline",
    "counts",
}
COUNT_KEYS = {"new", "screening", "interview", "offer", "hired"}
OPTIONS_KEYS = {"positions", "departments", "branches", "managers", "statuses"}
CHOICE_KEYS = {"id", "label"}
SLOT_KEYS = {"numbers", "warning"}
VACANCY_KEYS = {
    "id",
    "title",
    "status",
    "status_label",
    "position",
    "department",
    "branch",
    "headcount",
    "deadline",
    "desired_start",
    "description",
    "can_manage",
    "is_open",
    "slot_line",
    "stage_key",
    "stage_bar",
    "candidates",
    "next_offset",
}
STAGE_ITEM_KEYS = {"key", "label", "count"}
CANDIDATE_ROW_KEYS = {"id", "name", "stage", "stage_label", "phone", "source", "created"}
CANDIDATE_KEYS = {
    "id",
    "name",
    "vacancy_id",
    "vacancy_title",
    "stage",
    "stage_label",
    "source",
    "phone",
    "email",
    "notes",
    "reject_reason",
    "employee_id",
    "progress",
    "move_to",
    "move_confirm",
    "can_manage",
    "can_reject",
    "can_reopen",
    "can_convert",
    "events",
    "comments",
    "files",
    "max_mb",
    "extensions",
}
PROGRESS_KEYS = {"key", "label", "state"}
EVENT_KEYS = {"at", "from_label", "to_label", "note", "by"}
COMMENT_KEYS = {"id", "text", "by", "at"}
FILE_KEYS = {"id", "name", "uploaded", "by"}
PURGE_KEYS = {"rows", "months", "is_admin"}
PURGE_ROW_KEYS = {"id", "name", "vacancy_title", "stage_label", "closed"}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write anything."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("rec_api_actor", password=PASSWORD)  # noqa: S106


def _manage_permission() -> Permission:
    return Permission.objects.get(codename="manage_recruitment")


def _see_all_employees(user: User) -> User:
    """The user may see every employee (the manager pick list and the linked person need that right)."""
    user.user_permissions.add(Permission.objects.get(codename="view_employees", content_type__app_label="macs"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def hr(db: None) -> User:
    user = User.objects.create_user("rec_api_hr", password=PASSWORD)  # noqa: S106
    user.user_permissions.add(_manage_permission())
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def manager(actor: User) -> tuple[User, Employee]:
    """A hiring manager: a login linked to its own employee record, with no recruitment right."""
    return make_manager(actor, "rec_api_mgr", "УБ10000021")


@pytest.fixture
def manager_user(manager: tuple[User, Employee]) -> User:
    return User.objects.get(pk=manager[0].pk)


@pytest.fixture
def position_branch(db: None) -> Branch:
    return Branch.objects.create(name="Төв")


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _all_keys(value: Any) -> set[str]:
    """Every key of every object in a JSON value, at any depth."""
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _all_keys(item)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found |= _all_keys(item)
        return found
    return set()


def _add(vacancy: Vacancy, by: User, surname: str) -> Candidate:
    return pipeline.add_candidate(vacancy, by=by, surname=surname, given_name="Бат")


def _read_urls(vacancy: Vacancy, candidate: Candidate) -> list[str]:
    return [
        f"{BASE}/vacancies",
        f"{BASE}/vacancies/options",
        f"{BASE}/vacancies/slot-line",
        f"{BASE}/vacancies/{vacancy.pk}",
        f"{BASE}/candidates/{candidate.pk}",
        f"{BASE}/purge",
    ]


@pytest.fixture
def vacancy(actor: User) -> Vacancy:
    return make_vacancy("Нягтлан")


@pytest.fixture
def candidate(vacancy: Vacancy, actor: User) -> Candidate:
    return _add(vacancy, actor, "Дорж")


# --- rights, login and the module gate -----------------------------------------------------------------------------


def test_every_route_needs_a_signed_in_user(vacancy: Vacancy, candidate: Candidate) -> None:
    anonymous = Client()
    for url in _read_urls(vacancy, candidate):
        response = anonymous.get(url)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN, url


def test_module_off_is_404_on_every_route(hr: User, manager_user: User, vacancy: Vacancy, candidate: Candidate) -> None:
    modules.set_state({"recruitment": False})
    for user in (hr, manager_user):
        for url in _read_urls(vacancy, candidate):
            response = _client(user).get(url)
            assert response.status_code == 404, url
            assert response.json() == NOT_FOUND, url


def test_hiring_manager_gets_403_on_manage_reads(manager_user: User) -> None:
    client = _client(manager_user)
    assert client.get(f"{BASE}/vacancies/options").json() == FORBIDDEN
    assert client.get(f"{BASE}/vacancies/slot-line").json() == FORBIDDEN
    assert client.get(f"{BASE}/purge").json() == FORBIDDEN
    assert client.get(f"{BASE}/purge").status_code == 403


def test_every_read_answers_no_store(hr: User, manager_user: User, vacancy: Vacancy, candidate: Candidate) -> None:
    for user in (hr, manager_user):
        for url in _read_urls(vacancy, candidate):
            response = _client(user).get(url)
            if response.status_code == 200:
                assert response["Cache-Control"] == "no-store", url


# --- vacancy list --------------------------------------------------------------------------------------------------


def test_list_shape_and_rows_equal_the_service(hr: User, actor: User, vacancy: Vacancy) -> None:
    other = make_vacancy("Хоёр")
    response = _client(hr).get(f"{BASE}/vacancies", {"status": "all"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == LIST_KEYS
    assert set(body["rows"][0]) == ROW_KEYS
    assert set(body["rows"][0]["counts"]) == COUNT_KEYS
    expected, _ = vacancy_page.vacancy_batch(hr, "all", "", 0, batching.LIST_BATCH)
    assert [row["id"] for row in body["rows"]] == [v.pk for v in expected]
    assert {row["id"] for row in body["rows"]} == {vacancy.pk, other.pk}
    assert body["can_manage"] is True
    assert body["status"] == "all"


def test_list_row_names_and_deadline_come_from_the_records(hr: User, vacancy: Vacancy) -> None:
    row = _client(hr).get(f"{BASE}/vacancies").json()["rows"][0]
    assert row["title"] == "Нягтлан"
    assert row["position"] == vacancy.position.name
    assert row["department"] == vacancy.department.name
    assert row["status"] == "open" and row["status_label"] == "Нээлттэй"
    assert row["deadline"] is None


def test_hiring_manager_sees_only_own_vacancies(
    manager: tuple[User, Employee], manager_user: User, actor: User
) -> None:
    employee = manager[1]
    other_employee = make_manager(actor, "rec_api_other", "УБ10000022")[1]
    mine = make_vacancy("Миний", manager=employee)
    make_vacancy("Бусдын", manager=other_employee)
    body = _client(manager_user).get(f"{BASE}/vacancies").json()
    assert [row["id"] for row in body["rows"]] == [mine.pk]
    assert body["can_manage"] is False


def test_garbage_status_is_open_and_offset_abc_is_the_first_batch(hr: User, vacancy: Vacancy) -> None:
    client = _client(hr)
    plain = client.get(f"{BASE}/vacancies").json()
    garbage = client.get(f"{BASE}/vacancies", {"status": "garbage", "offset": "abc"}).json()
    assert garbage["status"] == "open"
    assert garbage["rows"] == plain["rows"]


def test_q_is_cut_to_100_characters(hr: User, vacancy: Vacancy) -> None:
    body = _client(hr).get(f"{BASE}/vacancies", {"q": "Б" * 500}).json()
    assert body["q"] == "Б" * 100


def test_next_offset_follows_the_batch_size(monkeypatch: pytest.MonkeyPatch, hr: User, actor: User) -> None:
    for name in ("Нэг", "Хоёр", "Гурав"):
        make_vacancy(name)
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    client = _client(hr)
    first = client.get(f"{BASE}/vacancies", {"status": "all"}).json()
    assert len(first["rows"]) == 2
    assert first["next_offset"] == 2
    second = client.get(f"{BASE}/vacancies", {"status": "all", "offset": "2"}).json()
    assert len(second["rows"]) == 1
    assert second["next_offset"] is None


def test_counts_per_stage(hr: User, actor: User) -> None:
    vacancy = make_vacancy("Тоолуур", headcount=5)
    _add(vacancy, actor, "А")
    second = _add(vacancy, actor, "Б")
    pipeline.move(second, Stage.SCREENING, by=actor)
    row = next(r for r in _client(hr).get(f"{BASE}/vacancies").json()["rows"] if r["id"] == vacancy.pk)
    assert row["counts"] == {"new": 1, "screening": 1, "interview": 0, "offer": 0, "hired": 0}
    assert row["headcount"] == 5


# --- vacancy form options ------------------------------------------------------------------------------------------


def test_options_shape_for_a_new_vacancy(hr: User, vacancy: Vacancy, manager: tuple[User, Employee]) -> None:
    body = _client(_see_all_employees(hr)).get(f"{BASE}/vacancies/options").json()
    assert set(body) == OPTIONS_KEYS
    assert body["managers"] and set(body["managers"][0]) == CHOICE_KEYS
    assert body["statuses"] == []  # a new vacancy has no status field


def test_options_edit_includes_the_current_manager_out_of_scope(
    actor: User, hr: User, manager: tuple[User, Employee]
) -> None:
    employee = manager[1]
    vacancy = make_vacancy("Засах", manager=employee)
    # The user may see only the other department: the manager's employee is outside the scope.
    other_dept = macs_writes.save_department("Бусад")
    scoped = User.objects.create_user("rec_api_scoped", password=PASSWORD)  # noqa: S106
    scoped.user_permissions.add(_manage_permission())
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[other_dept.pk])
    scoped = User.objects.get(pk=scoped.pk)
    client = _client(scoped)
    plain_ids = {m["id"] for m in client.get(f"{BASE}/vacancies/options").json()["managers"]}
    edit = client.get(f"{BASE}/vacancies/options", {"vacancy": str(vacancy.pk)})
    assert edit.status_code == 200
    edit_ids = {m["id"] for m in edit.json()["managers"]}
    assert employee.pk not in plain_ids
    assert employee.pk in edit_ids
    assert {s["value"] for s in edit.json()["statuses"]} == {"open", "closed"}


def test_options_unknown_vacancy_is_404(hr: User) -> None:
    assert _client(hr).get(f"{BASE}/vacancies/options", {"vacancy": "999999"}).status_code == 404


# --- budget line ---------------------------------------------------------------------------------------------------


def _switch_slots(on: bool) -> None:
    row = CompanySettings.get()
    row.enforce_position_slots = on
    row.save()


def test_slot_line_is_null_with_the_switch_off(hr: User, vacancy: Vacancy, position_branch: Branch) -> None:
    _switch_slots(False)
    response = _client(hr).get(
        f"{BASE}/vacancies/slot-line", {"position": str(vacancy.position_id), "branch": str(position_branch.pk)}
    )
    assert response.status_code == 200
    assert response.json() is None


def test_slot_line_shape_and_junk_headcount_is_one(hr: User, vacancy: Vacancy, position_branch: Branch) -> None:
    _switch_slots(True)
    client = _client(hr)
    params = {"position": str(vacancy.position_id), "branch": str(position_branch.pk), "desired_start": "2026-12-01"}
    body = client.get(f"{BASE}/vacancies/slot-line", {**params, "headcount": "abc"}).json()
    assert set(body) == SLOT_KEYS
    expected = slot_line.describe(
        position=vacancy.position,
        branch=position_branch,
        start=date(2026, 12, 1),
        headcount=1,
    )
    assert expected is not None
    assert body == {"numbers": expected.numbers, "warning": expected.warning}


def test_slot_line_without_a_branch_asks_for_one(hr: User, vacancy: Vacancy) -> None:
    _switch_slots(True)
    body = _client(hr).get(f"{BASE}/vacancies/slot-line", {"position": str(vacancy.position_id)}).json()
    assert body["numbers"] == ""
    assert body["warning"] == "Орон тоо шалгахын тулд салбар сонгоно уу."


# --- vacancy page --------------------------------------------------------------------------------------------------


def test_vacancy_page_shape_and_rows_equal_the_service(hr: User, vacancy: Vacancy, candidate: Candidate) -> None:
    body = _client(hr).get(f"{BASE}/vacancies/{vacancy.pk}").json()
    assert set(body) == VACANCY_KEYS
    assert set(body["stage_bar"][0]) == STAGE_ITEM_KEYS
    assert set(body["candidates"][0]) == CANDIDATE_ROW_KEYS
    assert [item["key"] for item in body["stage_bar"]] == [item.key for item in vacancy_page.stage_bar(vacancy)]
    rows, _ = vacancy_page.candidate_batch(vacancy, "open", 0, batching.LIST_BATCH)
    assert [row["id"] for row in body["candidates"]] == [c.pk for c in rows]
    assert body["candidates"][0]["name"] == f"{candidate.surname} {candidate.given_name}"
    assert body["is_open"] is True
    assert body["can_manage"] is True


def test_vacancy_page_hides_other_managers_vacancies_with_404(
    manager: tuple[User, Employee], manager_user: User, actor: User
) -> None:
    other = make_manager(actor, "rec_api_other2", "УБ10000023")[1]
    theirs = make_vacancy("Бусдын", manager=other)
    mine = make_vacancy("Миний", manager=manager[1])
    client = _client(manager_user)
    assert client.get(f"{BASE}/vacancies/{mine.pk}").status_code == 200
    response = client.get(f"{BASE}/vacancies/{theirs.pk}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _client(manager_user).get(f"{BASE}/vacancies/999999").status_code == 404


def test_hiring_manager_is_not_a_manager_on_the_vacancy_page(
    manager: tuple[User, Employee], manager_user: User
) -> None:
    mine = make_vacancy("Миний", manager=manager[1])
    body = _client(manager_user).get(f"{BASE}/vacancies/{mine.pk}").json()
    assert body["can_manage"] is False
    assert body["slot_line"] is None


def test_slot_line_on_the_vacancy_page_only_for_a_manager_on_an_open_vacancy(
    hr: User, vacancy: Vacancy, position_branch: Branch
) -> None:
    _switch_slots(True)
    vacancy.branch = position_branch
    vacancy.save(update_fields=["branch"])
    client = _client(hr)
    assert client.get(f"{BASE}/vacancies/{vacancy.pk}").json()["slot_line"] is not None
    vacancy.status = VacancyStatus.CLOSED
    vacancy.save(update_fields=["status"])
    assert client.get(f"{BASE}/vacancies/{vacancy.pk}").json()["slot_line"] is None


def test_garbage_stage_is_open_and_rows_match_the_service(hr: User, vacancy: Vacancy, candidate: Candidate) -> None:
    body = _client(hr).get(f"{BASE}/vacancies/{vacancy.pk}", {"stage": "garbage"}).json()
    assert body["stage_key"] == "open"
    rows, _ = vacancy_page.candidate_batch(vacancy, "open", 0, batching.LIST_BATCH)
    assert [row["id"] for row in body["candidates"]] == [c.pk for c in rows]


def test_second_batch_repeats_the_body_and_moves_the_candidates(
    monkeypatch: pytest.MonkeyPatch, hr: User, vacancy: Vacancy, actor: User
) -> None:
    _add(vacancy, actor, "Нэг")
    _add(vacancy, actor, "Хоёр")
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    client = _client(hr)
    first = client.get(f"{BASE}/vacancies/{vacancy.pk}").json()
    second = client.get(f"{BASE}/vacancies/{vacancy.pk}", {"offset": "1"}).json()
    assert first["next_offset"] == 1 and second["next_offset"] is None
    assert second["stage_bar"] == first["stage_bar"]
    assert len(first["candidates"]) == 1 and len(second["candidates"]) == 1
    assert second["candidates"][0]["id"] != first["candidates"][0]["id"]


# --- candidate page ------------------------------------------------------------------------------------------------


def test_candidate_shape_and_flags_equal_the_service(hr: User, candidate: Candidate) -> None:
    body = _client(hr).get(f"{BASE}/candidates/{candidate.pk}").json()
    assert set(body) == CANDIDATE_KEYS
    assert set(body["progress"][0]) == PROGRESS_KEYS
    page = candidate_page.candidate_page(hr, candidate)
    assert body["can_manage"] is page.can_manage
    assert body["can_reject"] is page.can_reject
    assert body["can_reopen"] is page.can_reopen
    assert body["can_convert"] is page.can_convert
    assert body["move_to"] == page.move_to
    assert body["move_confirm"] == page.move_confirm
    assert [(p["key"], p["label"], p["state"]) for p in body["progress"]] == page.progress
    assert body["vacancy_title"] == candidate.vacancy.title


def test_candidate_outside_scope_is_404(manager: tuple[User, Employee], manager_user: User, actor: User) -> None:
    other = make_manager(actor, "rec_api_other3", "УБ10000024")[1]
    theirs = make_vacancy("Бусдын", manager=other)
    outsider = _add(theirs, actor, "Гадны")
    response = _client(manager_user).get(f"{BASE}/candidates/{outsider.pk}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_employee_id_is_null_for_a_hiring_manager(
    manager: tuple[User, Employee], manager_user: User, new_person: Employee
) -> None:
    mine = make_vacancy("Миний", manager=manager[1])
    linked = _add(mine, manager[0], "Холбоотой")
    Candidate.objects.filter(pk=linked.pk).update(employee=new_person)
    body = _client(manager_user).get(f"{BASE}/candidates/{linked.pk}").json()
    assert body["employee_id"] is None
    assert body["can_manage"] is False


@pytest.fixture
def new_person(actor: User) -> Employee:
    return make_manager(actor, "rec_api_person", "УБ10000025")[1]


def test_manager_sees_the_linked_employee_id(hr: User, candidate: Candidate, new_person: Employee) -> None:
    hr = _see_all_employees(hr)  # the link shows only to a user who may see every employee
    Candidate.objects.filter(pk=candidate.pk).update(employee=new_person)
    body = _client(hr).get(f"{BASE}/candidates/{candidate.pk}").json()
    candidate.refresh_from_db()
    assert candidate_page.candidate_page(hr, candidate).employee_visible is True
    assert body["employee_id"] == new_person.pk


def test_candidate_body_has_no_storage_path_or_audit_or_salary(hr: User, actor: User, candidate: Candidate) -> None:
    CandidateFile.objects.create(
        candidate=candidate, file="secret/private-cv-path.pdf", name="cv.pdf", uploaded_by=actor
    )
    pipeline.comment(candidate, by=actor, text="Сэтгэгдэл")
    response = _client(hr).get(f"{BASE}/candidates/{candidate.pk}")
    body = response.json()
    assert set(body["files"][0]) == FILE_KEYS
    assert set(body["comments"][0]) == COMMENT_KEYS
    assert set(body["events"][0]) == EVENT_KEYS
    keys = _all_keys(body)
    assert {"created_by", "salary", "file"}.isdisjoint(keys)
    assert "secret/private-cv-path.pdf" not in response.content.decode()


def test_history_and_comment_times_use_the_page_format(hr: User, actor: User, candidate: Candidate) -> None:
    pipeline.move(candidate, Stage.SCREENING, by=actor)
    body = _client(hr).get(f"{BASE}/candidates/{candidate.pk}").json()
    event = body["events"][-1]
    assert event["from_label"] == "Шинэ" and event["to_label"] == "Шалгаруулалт"
    assert event["by"] == (actor.get_full_name() or actor.username)
    assert len(event["at"]) == 16 and event["at"][10] == " "


# --- purge ---------------------------------------------------------------------------------------------------------


def test_purge_lists_only_old_closed_candidates(hr: User, actor: User, vacancy: Vacancy) -> None:
    old = _add(vacancy, actor, "Хуучин")
    recent = _add(vacancy, actor, "Шинэ")
    open_one = _add(vacancy, actor, "Нээлттэй")
    Candidate.objects.filter(pk=old.pk).update(stage=Stage.REJECTED, closed_at=datetime(2020, 1, 1, tzinfo=UTC))
    Candidate.objects.filter(pk=recent.pk).update(stage=Stage.REJECTED, closed_at=timezone.now())
    body = _client(hr).get(f"{BASE}/purge").json()
    assert set(body) == PURGE_KEYS
    assert [row["id"] for row in body["rows"]] == [old.pk]
    assert set(body["rows"][0]) == PURGE_ROW_KEYS
    assert body["rows"][0]["closed"] == "2020-01-01"
    assert body["months"] == 12
    assert body["is_admin"] is False  # the manage right alone does not change the retention setting
    assert _client(actor).get(f"{BASE}/purge").json()["is_admin"] is True
    assert open_one.pk not in {row["id"] for row in body["rows"]}


def test_purge_is_not_shown_to_a_hiring_manager(manager_user: User) -> None:
    assert _client(manager_user).get(f"{BASE}/purge").status_code == 403


def test_every_operation_of_the_router_runs_the_module_gate() -> None:
    """A route that passed its own auth= would skip the login and module gate; every operation must list the router's
    auth callable. Walks whatever routes exist, so routes added later are checked too."""
    operations = [
        (path, operation)
        for path, path_view in recruitment_router.path_operations.items()
        for operation in path_view.operations
    ]
    assert operations, "the router has no operations to check"
    for path, operation in operations:
        methods = ",".join(sorted(operation.methods))
        assert _recruitment_auth in operation.auth_callbacks, (
            f"{methods} {path} does not run _recruitment_auth (the login and module gate); "
            "it must not pass its own auth="
        )


# --- the vacancy edit form's values (the manage right) ---------------------------------------------------------------

FORM_KEYS = {
    "title",
    "position",
    "department",
    "branch",
    "headcount",
    "hiring_manager",
    "deadline",
    "desired_start",
    "status",
    "description",
}


def test_form_needs_a_signed_in_user(vacancy: Vacancy) -> None:
    response = Client().get(f"{BASE}/vacancies/{vacancy.pk}/form")
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_form_module_off_is_404(hr: User, vacancy: Vacancy) -> None:
    modules.set_state({"recruitment": False})
    response = _client(hr).get(f"{BASE}/vacancies/{vacancy.pk}/form")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_form_unknown_or_foreign_vacancy_is_404_for_a_hiring_manager(
    manager: tuple[User, Employee], manager_user: User, actor: User, vacancy: Vacancy
) -> None:
    other = make_manager(actor, "rec_api_form_other", "УБ10000026")[1]
    theirs = make_vacancy("Бусдын форм", manager=other)
    client = _client(manager_user)
    for pk in (999999, theirs.pk, vacancy.pk):
        response = client.get(f"{BASE}/vacancies/{pk}/form")
        assert response.status_code == 404, pk
        assert response.json() == NOT_FOUND, pk


def test_form_is_403_for_a_hiring_manager_on_their_own_vacancy(
    manager: tuple[User, Employee], manager_user: User
) -> None:
    mine = make_vacancy("Миний форм", manager=manager[1])
    response = _client(manager_user).get(f"{BASE}/vacancies/{mine.pk}/form")
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_form_gives_the_ids_and_values_of_a_filled_vacancy(
    hr: User, manager: tuple[User, Employee], position_branch: Branch
) -> None:
    vacancy = make_vacancy("Бүрэн", headcount=3, manager=manager[1])
    vacancy.branch = position_branch
    vacancy.deadline = date(2026, 12, 31)
    vacancy.desired_start = date(2027, 1, 15)
    vacancy.description = "Тайлбар\nмөр"
    vacancy.status = VacancyStatus.CLOSED
    vacancy.save()
    response = _client(hr).get(f"{BASE}/vacancies/{vacancy.pk}/form")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {
        "title": "Бүрэн",
        "position": vacancy.position_id,
        "department": vacancy.department_id,
        "branch": position_branch.pk,
        "headcount": 3,
        "hiring_manager": manager[1].pk,
        "deadline": "2026-12-31",
        "desired_start": "2027-01-15",
        "status": "closed",
        "description": "Тайлбар\nмөр",
    }


def test_form_gives_nulls_for_the_blank_optional_fields(hr: User, vacancy: Vacancy) -> None:
    body = _client(hr).get(f"{BASE}/vacancies/{vacancy.pk}/form").json()
    assert set(body) == FORM_KEYS
    assert body["branch"] is None
    assert body["hiring_manager"] is None
    assert body["deadline"] is None
    assert body["desired_start"] is None
    assert body["status"] == "open"
    assert body["position"] == vacancy.position_id

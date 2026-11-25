"""The vacancy page service: parsing of the page's filters, the list rows, the stage bar, the candidate rows, the form
choices, and the create and edit rules. The views only call these, so the rules are tested here."""

import pytest
from accounts.models import SystemLogEntry, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.access import manager_choices
from macs.models import Employee

from recruitment.forms import VacancyForm
from recruitment.models import Candidate, Stage, Vacancy, VacancyStatus
from recruitment.services import pipeline, vacancy_page

from .conftest import make_manager, make_vacancy


def _batch(user: User, status: str = "all", q: str = "", offset: int = 0, size: int = 50) -> tuple[list[Vacancy], bool]:
    return vacancy_page.vacancy_batch(user, status, q, offset, size)


def _pks(user: User, status: str = "all", q: str = "") -> set[int]:
    return {row.pk for row in _batch(user, status, q)[0]}


def _add(vacancy: Vacancy, by: User, name: str) -> Candidate:
    return pipeline.add_candidate(vacancy, by=by, surname=name, given_name="Бат")


@pytest.mark.parametrize("status", [VacancyStatus.CLOSED, VacancyStatus.FILLED])
def test_candidate_add_refusal_is_not_open_text_unless_open(vacancy: Vacancy, status: str) -> None:
    assert vacancy_page.candidate_add_refusal(vacancy) == ""  # the fixture vacancy is open
    vacancy.status = status
    assert vacancy_page.candidate_add_refusal(vacancy) == vacancy_page.NOT_OPEN


def _edit_data(vacancy: Vacancy, **changes: str) -> dict[str, str]:
    data = {
        "title": vacancy.title,
        "position": str(vacancy.position_id),
        "department": str(vacancy.department_id),
        "headcount": str(vacancy.headcount),
        "status": vacancy.status,
        "description": "",
    }
    data.update(changes)
    return data


# ---- parse_status / parse_stage ----


@pytest.mark.parametrize("raw", ["open", "closed", "filled", "all"])
def test_parse_status_keeps_every_valid_value(raw: str) -> None:
    assert vacancy_page.parse_status(raw) == raw


@pytest.mark.parametrize("raw", ["garbage", "", None])
def test_parse_status_falls_back_to_open(raw: str | None) -> None:
    assert vacancy_page.parse_status(raw) == "open"


@pytest.mark.parametrize("raw", [*Stage.values, "open", "all"])
def test_parse_stage_keeps_every_valid_value(raw: str) -> None:
    assert vacancy_page.parse_stage(raw) == raw


@pytest.mark.parametrize("raw", ["garbage", "", None])
def test_parse_stage_falls_back_to_open(raw: str | None) -> None:
    assert vacancy_page.parse_stage(raw) == "open"


# ---- vacancy_batch: visibility, filters, search, order, batches ----


def test_manager_sees_every_vacancy(actor: User, hr_user: User) -> None:
    first = make_vacancy("Эхний")
    second = make_vacancy("Хоёр")
    assert _pks(hr_user) == {first.pk, second.pk}


def test_hiring_manager_sees_only_own_vacancies(actor: User) -> None:
    user, employee = make_manager(actor, "mgr_own", "УБ10000011")
    other_employee = make_manager(actor, "mgr_other", "УБ10000012")[1]
    mine = make_vacancy("Миний", manager=employee)
    theirs = make_vacancy("Бусдын", manager=other_employee)
    pks = _pks(user)
    assert mine.pk in pks
    assert theirs.pk not in pks


def test_status_filters_the_list_and_all_does_not(hr_user: User) -> None:
    open_one = make_vacancy("Нээлттэй")
    closed_one = make_vacancy("Хаагдсан")
    closed_one.status = VacancyStatus.CLOSED
    closed_one.save(update_fields=["status"])
    assert _pks(hr_user, "open") == {open_one.pk}
    assert _pks(hr_user, "closed") == {closed_one.pk}
    assert _pks(hr_user, "all") == {open_one.pk, closed_one.pk}


def test_every_search_word_must_match(hr_user: User) -> None:
    target = make_vacancy("Нягтлан ахлах")  # the department is «Санхүү»
    assert target.pk in _pks(hr_user, q="ахлах санхүү")  # one word in the title, one in the department
    assert target.pk not in _pks(hr_user, q="ахлах ззз")  # a word that matches nothing removes the row


def test_search_is_cut_to_its_first_100_characters(hr_user: User) -> None:
    fitting = make_vacancy("Б" * 100)
    make_vacancy("Бусад")
    rows, _ = _batch(hr_user, q="Б" * 100 + "Я" * 400)
    assert [row.pk for row in rows] == [fitting.pk]
    assert rows == _batch(hr_user, q="Б" * 100)[0]


def test_list_is_newest_first(hr_user: User) -> None:
    older = make_vacancy("Эхний")
    newer = make_vacancy("Сүүлийн")
    assert [row.pk for row in _batch(hr_user)[0]] == [newer.pk, older.pk]


def test_each_row_counts_its_stages(hr_user: User, actor: User, new_employee: Employee) -> None:
    vacancy = make_vacancy("Тоолуур", headcount=5)
    _add(vacancy, actor, "А")
    _add(vacancy, actor, "Б")
    third = _add(vacancy, actor, "В")
    pipeline.mark_hired(third, new_employee, by=actor)
    row = next(row for row in _batch(hr_user)[0] if row.pk == vacancy.pk)
    assert (row.c_new, row.c_screening, row.c_hired) == (2, 0, 1)


def test_size_offset_and_more_flag(hr_user: User) -> None:
    for number in range(3):
        make_vacancy(f"Ажлын байр {number}")
    rows, more = _batch(hr_user, size=2)
    assert len(rows) == 2 and more is True  # the extra third row is looked at, not returned
    rows, more = _batch(hr_user, size=3)
    assert len(rows) == 3 and more is False
    rows, more = _batch(hr_user, offset=2, size=2)
    assert len(rows) == 1 and more is False


def _list_queries(user: User) -> int:
    """Queries for one list request, touching the relations the list shows so a missing select_related is caught."""
    with CaptureQueriesContext(connection) as queries:
        rows, _ = _batch(user)
        for row in rows:
            _ = (row.position.name, row.department.name, row.hiring_manager, row.c_new, row.c_hired)
    return len(queries)


def test_query_count_does_not_grow_with_vacancies(hr_user: User) -> None:
    for name in ("Нэг", "Хоёр", "Гурав"):
        make_vacancy(name)
    _list_queries(hr_user)  # warm up (caches, first-request writes)
    before = _list_queries(hr_user)  # 3 vacancies
    for number in range(5):
        make_vacancy(f"Нэмэлт {number}")
    assert _list_queries(hr_user) == before  # 8 vacancies


# ---- stage_bar ----


def test_stage_bar_sums_the_active_stages_and_the_total(actor: User) -> None:
    vacancy = make_vacancy()
    _add(vacancy, actor, "Нэг")  # stays new
    second = _add(vacancy, actor, "Хоёр")
    third = _add(vacancy, actor, "Гурав")
    fourth = _add(vacancy, actor, "Дөрөв")
    pipeline.move(second, Stage.SCREENING, by=actor)
    pipeline.move(third, Stage.INTERVIEW, by=actor)
    pipeline.reject(fourth, by=actor, reason="туршлага хүрэлцэхгүй")
    bar = {item.key: item for item in vacancy_page.stage_bar(vacancy)}
    assert bar["open"].label == "Идэвхтэй" and bar["open"].count == 3
    assert bar["all"].label == "Бүгд" and bar["all"].count == 4
    assert bar["rejected"].count == 1


def test_stage_bar_lists_open_then_the_seven_stages_then_all(vacancy: Vacancy) -> None:
    keys = [item.key for item in vacancy_page.stage_bar(vacancy)]
    assert keys == ["open", *Stage.values, "all"]
    between = keys[1:-1]
    assert len(between) == 7 and between == [stage.value for stage in Stage]


# ---- candidate_batch ----


def test_open_hides_rejected_withdrawn_and_hired(actor: User, new_employee: Employee) -> None:
    vacancy = make_vacancy(headcount=9)
    fresh = _add(vacancy, actor, "Шинэ")
    interview = _add(vacancy, actor, "Ярилцлага")
    pipeline.move(interview, Stage.INTERVIEW, by=actor)
    rejected = _add(vacancy, actor, "Татгалзсан")
    pipeline.reject(rejected, by=actor, reason="туршлага")
    withdrawn = _add(vacancy, actor, "Өөрөө")
    pipeline.reject(withdrawn, by=actor, reason="", withdrawn=True)
    hired = _add(vacancy, actor, "Ажилд")
    pipeline.mark_hired(hired, new_employee, by=actor)
    rows, more = vacancy_page.candidate_batch(vacancy, "open", 0, 50)
    assert {row.pk for row in rows} == {fresh.pk, interview.pk}
    assert more is False


def test_a_stage_key_filters_the_candidates(actor: User) -> None:
    vacancy = make_vacancy()
    _add(vacancy, actor, "Нэг")
    screened = _add(vacancy, actor, "Хоёр")
    pipeline.move(screened, Stage.SCREENING, by=actor)
    rows, _ = vacancy_page.candidate_batch(vacancy, Stage.SCREENING, 0, 50)
    assert [row.pk for row in rows] == [screened.pk]


def test_all_shows_every_candidate(actor: User, new_employee: Employee) -> None:
    vacancy = make_vacancy(headcount=9)
    _add(vacancy, actor, "Нэг")
    rejected = _add(vacancy, actor, "Хоёр")
    pipeline.reject(rejected, by=actor, reason="туршлага")
    hired = _add(vacancy, actor, "Гурав")
    pipeline.mark_hired(hired, new_employee, by=actor)
    rows, _ = vacancy_page.candidate_batch(vacancy, "all", 0, 50)
    assert len(rows) == 3


def test_candidates_are_newest_first(actor: User) -> None:
    vacancy = make_vacancy()
    first = _add(vacancy, actor, "Эхний")
    second = _add(vacancy, actor, "Сүүлийн")
    rows, _ = vacancy_page.candidate_batch(vacancy, "all", 0, 50)
    assert [row.pk for row in rows] == [second.pk, first.pk]


def test_candidate_batch_size_and_more_flag(actor: User) -> None:
    vacancy = make_vacancy()
    for name in ("Нэг", "Хоёр", "Гурав"):
        _add(vacancy, actor, name)
    rows, more = vacancy_page.candidate_batch(vacancy, "all", 0, 2)
    assert len(rows) == 2 and more is True
    rows, more = vacancy_page.candidate_batch(vacancy, "all", 0, 3)
    assert len(rows) == 3 and more is False


# ---- vacancy_options ----


def test_options_equal_the_form_choices(hr_user: User, vacancy: Vacancy) -> None:
    options = vacancy_page.vacancy_options(hr_user, vacancy)
    form = VacancyForm(user=hr_user, instance=vacancy)
    for name, choices in (
        ("position", options.positions),
        ("department", options.departments),
        ("branch", options.branches),
        ("hiring_manager", options.managers),
    ):
        assert {pk for pk, _ in choices} == set(form.fields[name].queryset.values_list("pk", flat=True)), name
    assert dict(options.positions)[vacancy.position_id] == str(vacancy.position)
    assert options.statuses == [(value, str(label)) for value, label in form.fields["status"].choices]


def test_a_new_vacancy_has_no_status_choices(hr_user: User) -> None:
    assert vacancy_page.vacancy_options(hr_user, None).statuses == []


def test_hiring_manager_choices_are_the_manager_choices_rule(actor: User) -> None:
    user, employee = make_manager(actor, "mgr_opt", "УБ10000021")
    make_manager(actor, "mgr_opt2", "УБ10000022")
    vacancy = make_vacancy("Миний", manager=employee)
    options = vacancy_page.vacancy_options(user, vacancy)
    assert {pk for pk, _ in options.managers} == set(manager_choices(user, employee).values_list("pk", flat=True))


def test_current_manager_stays_in_the_choices_even_when_out_of_scope(actor: User) -> None:
    user, _ = make_manager(actor, "mgr_scope", "УБ10000023")
    other = make_manager(actor, "mgr_scope2", "УБ10000024")[1]
    vacancy = make_vacancy("Чужой", manager=other)
    assert other.pk not in set(manager_choices(user).values_list("pk", flat=True))
    assert other.pk in {pk for pk, _ in vacancy_page.vacancy_options(user, vacancy).managers}


# ---- create_vacancy ----


def test_create_opens_the_vacancy_and_logs_it(hr_user: User, vacancy: Vacancy) -> None:
    data = {
        "title": "Шинэ ажлын байр",
        "position": str(vacancy.position_id),
        "department": str(vacancy.department_id),
        "headcount": "2",
        "status": "closed",  # a new vacancy ignores this: it is always open
    }
    created, form = vacancy_page.create_vacancy(hr_user, data)
    assert created is not None and form.is_valid()
    created.refresh_from_db()
    assert created.status == VacancyStatus.OPEN
    assert created.created_by == hr_user
    assert created.headcount == 2
    assert SystemLogEntry.objects.filter(action="vacancy_created", message="Шинэ ажлын байр").exists()


def test_create_with_an_empty_title_writes_nothing(hr_user: User, vacancy: Vacancy) -> None:
    data = {
        "title": "",
        "position": str(vacancy.position_id),
        "department": str(vacancy.department_id),
        "headcount": "1",
    }
    created, form = vacancy_page.create_vacancy(hr_user, data)
    assert created is None
    assert "title" in form.errors
    assert Vacancy.objects.count() == 1  # only the fixture's vacancy
    assert not SystemLogEntry.objects.filter(action="vacancy_created").exists()


# ---- update_vacancy ----


def test_edit_saves_and_logs_the_change(hr_user: User, vacancy: Vacancy) -> None:
    updated, _ = vacancy_page.update_vacancy(hr_user, vacancy, _edit_data(vacancy, title="Ново нэр"))
    assert updated is not None
    vacancy.refresh_from_db()
    assert vacancy.title == "Ново нэр"
    assert SystemLogEntry.objects.filter(action="vacancy_changed", message="Ново нэр").exists()


def test_filled_cannot_be_picked_by_hand(hr_user: User, vacancy: Vacancy) -> None:
    updated, form = vacancy_page.update_vacancy(hr_user, vacancy, _edit_data(vacancy, status="filled"))
    assert updated is None
    # Refused with an error under status. Known gap (see task report): on an open vacancy `filled` is not among the
    # status choices, so Django's invalid-choice text shows instead of the service text in VacancyForm.clean_status.
    assert "status" in form.errors
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN


def test_raising_the_headcount_of_a_filled_vacancy_reopens_it(
    hr_user: User, vacancy: Vacancy, new_employee: Employee, actor: User
) -> None:
    candidate = _add(vacancy, actor, "Хирэгдсэн")
    pipeline.mark_hired(candidate, new_employee, by=actor)
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.FILLED
    updated, _ = vacancy_page.update_vacancy(hr_user, vacancy, _edit_data(vacancy, headcount="2"))
    assert updated is not None
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN and vacancy.headcount == 2
    assert SystemLogEntry.objects.filter(action="vacancy_changed", message=vacancy.title).exists()

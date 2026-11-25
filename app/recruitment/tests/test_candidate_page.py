"""The candidate page service: the progress steps, the move targets and the moves that ask first, the page's flags for
each user and state, the purge page and the convert answer. The views only call these, so the rules are tested here."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from accounts.models import User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from macs.models import Employee

from recruitment.models import Candidate, RecruitmentSettings, Stage, Vacancy, VacancyStatus
from recruitment.services import candidate_page, convert, files, pipeline

from .conftest import make_manager, make_vacancy


def _closed(vacancy: Vacancy, actor: User, surname: str, months_ago: int) -> Candidate:
    cand = pipeline.add_candidate(vacancy, by=actor, surname=surname, given_name="Х")
    pipeline.reject(cand, by=actor, reason="Тохирохгүй")
    Candidate.objects.filter(pk=cand.pk).update(closed_at=timezone.now() - timedelta(days=31 * months_ago))
    return cand


def _fresh(candidate: Candidate) -> Candidate:
    return Candidate.objects.select_related("vacancy").get(pk=candidate.pk)


def _states(candidate: Candidate) -> dict[str, str]:
    return {stage: state for stage, _label, state in candidate_page.progress(candidate)}


# ---- progress ----


def test_progress_lights_the_steps_up_to_a_new_candidate(candidate: Candidate) -> None:
    assert _states(candidate) == {
        "new": "current",
        "screening": "todo",
        "interview": "todo",
        "offer": "todo",
        "hired": "todo",
    }


def test_progress_marks_the_steps_before_an_offer_done(candidate: Candidate, actor: User) -> None:
    for target in (Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER):
        pipeline.move(candidate, target, by=actor)
    assert _states(_fresh(candidate)) == {
        "new": "done",
        "screening": "done",
        "interview": "done",
        "offer": "current",
        "hired": "todo",
    }


def test_progress_marks_every_step_done_for_a_hired_candidate(
    candidate: Candidate, new_employee: Employee, actor: User
) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    assert _states(_fresh(candidate)) == {
        "new": "done",
        "screening": "done",
        "interview": "done",
        "offer": "done",
        "hired": "current",
    }


def test_progress_has_no_lit_step_when_rejected_or_withdrawn(vacancy: Vacancy, actor: User) -> None:
    rejected = pipeline.add_candidate(vacancy, by=actor, surname="Татгалзсан", given_name="Х")
    pipeline.reject(rejected, by=actor, reason="туршлага")
    withdrawn = pipeline.add_candidate(vacancy, by=actor, surname="Өөрөө", given_name="Х")
    pipeline.reject(withdrawn, by=actor, reason="", withdrawn=True)
    for cand in (_fresh(rejected), _fresh(withdrawn)):
        assert set(_states(cand).values()) == {"todo"}


def test_progress_labels_are_the_stage_labels(candidate: Candidate) -> None:
    labels = [label for _stage, label, _state in candidate_page.progress(candidate)]
    assert labels == [
        str(stage.label) for stage in (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER, Stage.HIRED)
    ]


# ---- move_targets and confirm_moves ----


def test_move_targets_exclude_the_current_stage_and_hired(candidate: Candidate) -> None:
    targets = candidate_page.move_targets(candidate)
    assert targets == ["screening", "interview", "offer"]
    assert "new" not in targets and "hired" not in targets


def test_confirm_moves_skip_the_next_step_from_new(candidate: Candidate) -> None:
    assert candidate_page.confirm_moves(candidate) == ["interview", "offer"]  # screening is the next step: no question


def test_confirm_moves_ask_for_every_target_from_offer(candidate: Candidate, actor: User) -> None:
    for target in (Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER):
        pipeline.move(candidate, target, by=actor)
    current = _fresh(candidate)
    assert candidate_page.confirm_moves(current) == ["new", "screening", "interview"]


# ---- candidate_page: flags per user and state ----


def test_manager_on_an_open_candidate_gets_reject_convert_and_moves(hr_user: User, candidate: Candidate) -> None:
    page = candidate_page.candidate_page(hr_user, candidate)
    assert page.can_manage is True
    assert page.can_reject is True
    assert page.can_convert is True
    assert page.can_reopen is False
    assert page.move_to == ["screening", "interview", "offer"]
    assert page.move_confirm == ["interview", "offer"]


def test_hiring_manager_gets_no_manage_actions(actor: User) -> None:
    manager_user, manager_emp = make_manager(actor, "cp_mgr", "УБ20000001")
    hiring = make_vacancy("Миний", manager=manager_emp)
    own = pipeline.add_candidate(hiring, by=actor, surname="Миний", given_name="Х")
    page = candidate_page.candidate_page(manager_user, own)
    assert page.can_manage is False
    assert page.can_reject is False
    assert page.can_convert is False
    assert page.can_reopen is False
    assert page.move_to == []
    assert page.move_confirm == []


def test_rejected_candidate_gets_reopen_and_no_moves(hr_user: User, candidate: Candidate, actor: User) -> None:
    pipeline.reject(candidate, by=actor, reason="туршлага")
    page = candidate_page.candidate_page(hr_user, _fresh(candidate))
    assert page.can_reopen is True
    assert page.can_reject is False
    assert page.can_convert is False
    assert page.move_to == [] and page.move_confirm == []


def test_hired_candidate_gets_none_of_reject_reopen_convert_and_moves(
    hr_user: User, candidate: Candidate, new_employee: Employee, actor: User
) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    page = candidate_page.candidate_page(hr_user, _fresh(candidate))
    assert page.can_reject is False
    assert page.can_reopen is False
    assert page.can_convert is False
    assert page.move_to == [] and page.move_confirm == []


def test_employee_visible_only_when_the_employee_is_in_the_users_scope(
    hr_user: User, candidate: Candidate, new_employee: Employee, actor: User
) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    current = _fresh(candidate)
    assert candidate_page.candidate_page(hr_user, current).employee_visible is False  # no view-employees right
    hr_user.groups.add(Group.objects.get(name="HR"))  # HR may see the employee record
    reloaded = User.objects.get(pk=hr_user.pk)  # permissions are cached on the user object: read it again
    assert candidate_page.candidate_page(reloaded, current).employee_visible is True


def test_page_carries_the_file_limits(hr_user: User, candidate: Candidate) -> None:
    page = candidate_page.candidate_page(hr_user, candidate)
    assert page.max_mb == files.MAX_BYTES // (1024 * 1024)
    assert page.extensions == ", ".join(sorted(files.ALLOWED_EXTENSIONS))


# ---- candidate_page: history, comments, files in model order, no query growth ----


def test_history_is_oldest_first_and_names_the_mover(hr_user: User, candidate: Candidate, actor: User) -> None:
    pipeline.move(candidate, Stage.SCREENING, by=actor)
    pipeline.move(candidate, Stage.INTERVIEW, by=hr_user)
    page = candidate_page.candidate_page(hr_user, _fresh(candidate))
    assert [event.to_stage for event in page.events] == ["new", "screening", "interview"]
    assert page.events[-1].by == hr_user


def _grow(candidate: Candidate, actor: User, count: int) -> None:
    targets = [Stage.SCREENING, Stage.INTERVIEW]
    for number in range(count):
        pipeline.move(candidate, targets[number % 2], by=actor)
        pipeline.comment(candidate, by=actor, text=f"Сэтгэгдэл {number}")
        files.save(candidate, SimpleUploadedFile(f"cv{number}.pdf", b"%PDF-1.4 test"), by=actor)


def _page_queries(user: User, candidate: Candidate) -> int:
    with CaptureQueriesContext(connection) as queries:
        page = candidate_page.candidate_page(user, candidate)
        for event in page.events:
            _ = event.by
        for comment in page.comments:
            _ = comment.by
        for row in page.files:
            _ = row.uploaded_by
    return len(queries)


def test_query_count_does_not_grow_with_history_comments_and_files(
    hr_user: User, vacancy: Vacancy, actor: User
) -> None:
    cand = pipeline.add_candidate(vacancy, by=actor, surname="Тоолуур", given_name="Х")
    _grow(cand, actor, 2)
    _page_queries(hr_user, cand)  # warm up
    before = _page_queries(hr_user, cand)  # 2 moves, comments and files
    _grow(cand, actor, 6)
    assert _page_queries(hr_user, cand) == before  # 8 moves, comments and files


# ---- purge_page ----


def test_purge_page_lists_only_old_closed_candidates(hr_user: User, vacancy: Vacancy, actor: User) -> None:
    old = _closed(vacancy, actor, "Хуучин", 14)
    recent = _closed(vacancy, actor, "Шинэхэн", 0)
    Candidate.objects.filter(pk=recent.pk).update(closed_at=timezone.now() - timedelta(days=1))
    live = pipeline.add_candidate(vacancy, by=actor, surname="Идэвхтэй", given_name="Х")
    page = candidate_page.purge_page(hr_user, timezone.localdate())
    assert [row.pk for row in page.rows] == [old.pk]
    assert page.months == RecruitmentSettings.get().retention_months == 12
    assert live.pk not in [row.pk for row in page.rows]
    assert recent.pk not in [row.pk for row in page.rows]


def test_purge_page_is_admin_for_the_admin_group_and_superusers_only(hr_user: User, actor: User) -> None:
    assert candidate_page.purge_page(hr_user, timezone.localdate()).is_admin is False
    admin_user = User.objects.create_user("cp_admin", password="x-long-pass-123")  # noqa: S106
    admin_user.groups.add(Group.objects.get(name="Admin"))
    assert candidate_page.purge_page(admin_user, timezone.localdate()).is_admin is True
    superuser = User.objects.create_user("cp_super", password="x-long-pass-123")  # noqa: S106
    superuser.is_superuser = True
    superuser.save()
    assert candidate_page.purge_page(superuser, timezone.localdate()).is_admin is True


# ---- convert_answer ----


def test_convert_answer_gives_the_hire_form_path_with_the_prefill(hr_user: User, candidate: Candidate) -> None:
    today = timezone.localdate()
    path, error = candidate_page.convert_answer(hr_user, candidate, today)
    assert error == ""
    target = urlparse(path)
    assert target.path == reverse("employees:add")
    query = {key: value[0] for key, value in parse_qs(target.query).items()}
    assert query["family_name"] == "Дорж" and query["given_name"] == "Бат"
    assert query["candidate"] == str(candidate.pk)
    assert query["position"] == str(candidate.vacancy.position_id)
    assert query == convert.prefill_params(_fresh(candidate), today)


def test_convert_answer_refuses_a_closed_vacancy(hr_user: User, candidate: Candidate) -> None:
    Vacancy.objects.filter(pk=candidate.vacancy_id).update(status=VacancyStatus.CLOSED)
    path, error = candidate_page.convert_answer(hr_user, _fresh(candidate), timezone.localdate())
    assert path == ""
    assert error == convert.VACANCY_NOT_OPEN


def test_convert_answer_refuses_a_hired_candidate(
    hr_user: User, candidate: Candidate, new_employee: Employee, actor: User
) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    path, error = candidate_page.convert_answer(hr_user, _fresh(candidate), timezone.localdate())
    assert path == ""
    assert error == convert.NOT_CONVERTIBLE

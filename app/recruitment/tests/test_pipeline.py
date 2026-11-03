from datetime import date, datetime, time
from pathlib import Path

import pytest
from accounts.models import SystemLogEntry, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from macs.models import Employee

from recruitment.models import (
    Candidate,
    CandidateComment,
    CandidateEvent,
    RecruitmentSettings,
    Stage,
    Vacancy,
    VacancyStatus,
)
from recruitment.services import files, pipeline

from .conftest import make_vacancy


def test_add_candidate_writes_first_event(vacancy: Vacancy, actor: User) -> None:
    c = pipeline.add_candidate(vacancy, by=actor, surname="Дорж", given_name="Бат", phone="99")
    assert c.stage == Stage.NEW
    event = CandidateEvent.objects.get(candidate=c)
    assert (event.from_stage, event.to_stage, event.by) == ("", Stage.NEW, actor)
    assert SystemLogEntry.objects.filter(action="candidate_added").exists()


def test_move_records_event(candidate: Candidate, actor: User) -> None:
    pipeline.move(candidate, Stage.INTERVIEW, by=actor, note="ok")
    candidate.refresh_from_db()
    assert candidate.stage == Stage.INTERVIEW
    event = candidate.events.last()
    assert event is not None
    assert (event.from_stage, event.to_stage, event.note) == (Stage.NEW, Stage.INTERVIEW, "ok")


@pytest.mark.parametrize("target", [Stage.HIRED, Stage.REJECTED, Stage.WITHDRAWN, "bogus"])
def test_move_refuses_special_stages(candidate: Candidate, actor: User, target: str) -> None:
    with pytest.raises(pipeline.PipelineError) as exc:
        pipeline.move(candidate, target, by=actor)
    assert exc.value.message
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW


def test_move_refuses_closed_and_hired(candidate: Candidate, actor: User, new_employee: Employee) -> None:
    pipeline.reject(candidate, by=actor, reason="no")
    with pytest.raises(pipeline.PipelineError):
        pipeline.move(candidate, Stage.SCREENING, by=actor)
    pipeline.reopen(candidate, by=actor)
    pipeline.mark_hired(candidate, new_employee, by=actor)
    with pytest.raises(pipeline.PipelineError):
        pipeline.move(candidate, Stage.SCREENING, by=actor)


def test_reject_needs_reason_unless_withdrawn(candidate: Candidate, actor: User) -> None:
    with pytest.raises(pipeline.PipelineError):
        pipeline.reject(candidate, by=actor, reason="   ")
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.closed_at is None
    pipeline.reject(candidate, by=actor, reason="", withdrawn=True)
    candidate.refresh_from_db()
    assert candidate.stage == Stage.WITHDRAWN and candidate.closed_at is not None


def test_reject_from_later_stage_sets_closed_at(candidate: Candidate, actor: User) -> None:
    pipeline.move(candidate, Stage.OFFER, by=actor)
    pipeline.reject(candidate, by=actor, reason="Цалин")
    candidate.refresh_from_db()
    assert (candidate.stage, candidate.reject_reason) == (Stage.REJECTED, "Цалин")
    assert candidate.closed_at is not None
    last = candidate.events.last()
    assert last is not None and (last.from_stage, last.to_stage) == (Stage.OFFER, Stage.REJECTED)
    with pytest.raises(pipeline.PipelineError):
        pipeline.reject(candidate, by=actor, reason="again")


def test_reopen_only_from_closed(candidate: Candidate, actor: User) -> None:
    with pytest.raises(pipeline.PipelineError):
        pipeline.reopen(candidate, by=actor)
    pipeline.reject(candidate, by=actor, reason="x")
    pipeline.reopen(candidate, by=actor)
    candidate.refresh_from_db()
    assert (candidate.stage, candidate.closed_at, candidate.reject_reason) == (Stage.NEW, None, "")


def test_comment(candidate: Candidate, actor: User) -> None:
    row = pipeline.comment(candidate, by=actor, text=" сайн ")
    assert isinstance(row, CandidateComment) and row.text == "сайн"
    with pytest.raises(pipeline.PipelineError):
        pipeline.comment(candidate, by=actor, text="  ")


def test_hired_candidate_cannot_be_rejected(candidate: Candidate, actor: User, new_employee: Employee) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    with pytest.raises(pipeline.PipelineError):
        pipeline.reject(candidate, by=actor, reason="x")


def test_mark_hired_links_and_fills_vacancy(candidate: Candidate, actor: User, new_employee: Employee) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    candidate.refresh_from_db()
    assert (candidate.stage, candidate.employee) == (Stage.HIRED, new_employee)
    assert candidate.vacancy.status == VacancyStatus.FILLED
    assert candidate.events.last().to_stage == Stage.HIRED  # type: ignore[union-attr]


def test_mark_hired_twice_refused(candidate: Candidate, actor: User, new_employee: Employee) -> None:
    pipeline.mark_hired(candidate, new_employee, by=actor)
    stale = Candidate.objects.get(pk=candidate.pk)
    with pytest.raises(pipeline.PipelineError):
        pipeline.mark_hired(stale, new_employee, by=actor)
    assert CandidateEvent.objects.filter(candidate=candidate, to_stage=Stage.HIRED).count() == 1


def test_mark_hired_refuses_closed(candidate: Candidate, actor: User, new_employee: Employee) -> None:
    pipeline.reject(candidate, by=actor, reason="x")
    with pytest.raises(pipeline.PipelineError):
        pipeline.mark_hired(candidate, new_employee, by=actor)
    candidate.refresh_from_db()
    assert candidate.employee is None


def test_vacancy_filled_only_at_headcount(actor: User, new_employee: Employee) -> None:
    vacancy = make_vacancy(headcount=2)
    first = pipeline.add_candidate(vacancy, by=actor, surname="a", given_name="a")
    second = pipeline.add_candidate(vacancy, by=actor, surname="b", given_name="b")
    pipeline.mark_hired(first, new_employee, by=actor)
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN
    pipeline.mark_hired(second, new_employee, by=actor)
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.FILLED


# --- purge ---------------------------------------------------------------------------------------------------------


def _closed(vacancy: Vacancy, actor: User, closed: datetime, *, withdrawn: bool = False) -> Candidate:
    c = pipeline.add_candidate(vacancy, by=actor, surname="Нууц", given_name="Нэр")
    pipeline.reject(c, by=actor, reason="x", withdrawn=withdrawn)
    Candidate.objects.filter(pk=c.pk).update(closed_at=timezone.make_aware(closed))
    return c


def test_purge_cutoff_is_strict(vacancy: Vacancy, actor: User) -> None:
    assert RecruitmentSettings.get().retention_months == 12
    today = date(2026, 11, 2)
    on_boundary = _closed(vacancy, actor, datetime.combine(date(2025, 11, 2), time(0, 0)))
    just_after = _closed(vacancy, actor, datetime.combine(date(2025, 11, 2), time(0, 1)))
    before = _closed(vacancy, actor, datetime.combine(date(2025, 11, 1), time(23, 59)), withdrawn=True)
    # exactly at the boundary is not yet purgeable; the day before is
    assert pipeline.purge(by=actor, today=today) == 1
    remaining = set(Candidate.objects.values_list("pk", flat=True))
    assert remaining == {on_boundary.pk, just_after.pk}
    assert not Candidate.objects.filter(pk=before.pk).exists()


def test_purge_keeps_open_and_hired(vacancy: Vacancy, actor: User, new_employee: Employee) -> None:
    open_c = pipeline.add_candidate(vacancy, by=actor, surname="a", given_name="a")
    hired_c = pipeline.add_candidate(vacancy, by=actor, surname="b", given_name="b")
    pipeline.mark_hired(hired_c, new_employee, by=actor)
    Candidate.objects.update(created_at=timezone.make_aware(datetime(2020, 1, 1)))
    old = _closed(vacancy, actor, datetime(2020, 1, 1))
    assert pipeline.purge(by=actor, today=date(2026, 11, 2)) == 1
    assert set(Candidate.objects.values_list("pk", flat=True)) == {open_c.pk, hired_c.pk}
    assert not Candidate.objects.filter(pk=old.pk).exists()


def test_purge_month_end_clamp(vacancy: Vacancy, actor: User) -> None:
    RecruitmentSettings.objects.update_or_create(pk=1, defaults={"retention_months": 1})
    # 31 March minus 1 month = 28 Feb 2026
    gone = _closed(vacancy, actor, datetime(2026, 2, 27, 12, 0))
    kept = _closed(vacancy, actor, datetime(2026, 2, 28, 12, 0))
    assert pipeline.purge(by=actor, today=date(2026, 3, 31)) == 1
    assert not Candidate.objects.filter(pk=gone.pk).exists()
    assert Candidate.objects.filter(pk=kept.pk).exists()


def test_purge_removes_files_and_logs_no_names(vacancy: Vacancy, actor: User, settings: object) -> None:
    c = _closed(vacancy, actor, datetime(2020, 1, 1))
    row = files.save(c, SimpleUploadedFile("cv.pdf", b"%PDF-1"), by=actor)
    on_disk = Path(files.storage().path(row.file))
    assert on_disk.exists()
    assert pipeline.purge(by=actor, today=date(2026, 11, 2)) == 1
    assert not on_disk.exists()
    assert not on_disk.parent.exists()
    entries = list(SystemLogEntry.objects.filter(action="candidates_purged"))
    assert len(entries) == 1
    text = f"{entries[0].message} {entries[0].target_label} {entries[0].changes}"
    assert "Нууц" not in text and "cv.pdf" not in text
    assert "1" in entries[0].message


def test_purge_nothing_logs_nothing(vacancy: Vacancy, actor: User) -> None:
    assert pipeline.purge(by=actor, today=date(2026, 11, 2)) == 0
    assert not SystemLogEntry.objects.filter(action="candidates_purged").exists()

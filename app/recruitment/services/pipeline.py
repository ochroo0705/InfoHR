"""Stage moves, rejection, comments, conversion link and purge. No permission checks: the views check.

Candidate history (CandidateEvent) and comments are append-only. Every write is also logged through the system log;
the log never carries a candidate's name (the target is "Ажил хүсэгч #id").
"""

import calendar
from datetime import date, datetime, time

from accounts.audit import Category, record_safe
from accounts.models import User
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from macs.models import Employee

from recruitment.models import (
    Candidate,
    CandidateComment,
    CandidateEvent,
    CandidateFile,
    RecruitmentSettings,
    Stage,
    Vacancy,
    VacancyStatus,
)
from recruitment.services import files

CLOSED_STAGES = (Stage.REJECTED, Stage.WITHDRAWN)
MOVABLE_STAGES = (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER)


class PipelineError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _log(action: str, candidate: Candidate, by: User | None, message: str = "") -> None:
    record_safe(
        Category.HR,
        action,
        actor=by,
        target_type="Ажил хүсэгч",
        target_label=f"Ажил хүсэгч #{candidate.pk}",
        message=message,
    )


def _stage_label(stage: str) -> str:
    return str(Stage(stage).label)


def add_candidate(
    vacancy: Vacancy,
    *,
    by: User,
    surname: str,
    given_name: str,
    phone: str = "",
    email: str = "",
    source: str = "",
    notes: str = "",
) -> Candidate:
    with transaction.atomic():
        candidate = Candidate.objects.create(
            vacancy=vacancy,
            surname=surname,
            given_name=given_name,
            phone=phone,
            email=email,
            source=source,
            notes=notes,
            stage=Stage.NEW,
            created_by=by,
        )
        CandidateEvent.objects.create(candidate=candidate, from_stage="", to_stage=Stage.NEW, by=by)
    _log("candidate_added", candidate, by, f"Ажлын байр #{vacancy.pk}")
    return candidate


def move(candidate: Candidate, to_stage: str, *, by: User, note: str = "") -> Candidate:
    """Move to new/screening/interview/offer. Never to hired (conversion only) or rejected (use reject)."""
    if to_stage not in MOVABLE_STAGES:
        if to_stage == Stage.HIRED:
            raise PipelineError("«Ажилд авсан» шатанд зөвхөн ажилтан болгож хөрвүүлэх замаар оруулна.")
        if to_stage in CLOSED_STAGES:
            raise PipelineError("Татгалзахдаа «Татгалзах» үйлдлийг ашиглана уу.")
        raise PipelineError("Тодорхойгүй шат байна.")
    with transaction.atomic():
        locked = Candidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.stage == Stage.HIRED:
            raise PipelineError("Ажилд авсан ажил хүсэгчийн шатыг өөрчлөх боломжгүй.")
        if locked.stage in CLOSED_STAGES:
            raise PipelineError("Татгалзсан ажил хүсэгчийг эхлээд дахин нээнэ үү.")
        from_stage = locked.stage
        if from_stage == to_stage:
            return locked
        locked.stage = to_stage
        locked.save(update_fields=["stage"])
        CandidateEvent.objects.create(
            candidate=locked, from_stage=from_stage, to_stage=to_stage, note=note.strip(), by=by
        )
    _log("candidate_moved", locked, by, f"{_stage_label(from_stage)} -> {_stage_label(to_stage)}")
    candidate.stage = locked.stage
    return locked


def reject(candidate: Candidate, *, by: User, reason: str, withdrawn: bool = False) -> Candidate:
    reason = reason.strip()
    if not withdrawn and not reason:
        raise PipelineError("Татгалзсан шалтгаанаа бичнэ үү.")
    target = Stage.WITHDRAWN if withdrawn else Stage.REJECTED
    with transaction.atomic():
        locked = Candidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.stage == Stage.HIRED:
            raise PipelineError("Ажилд авсан ажил хүсэгчийг татгалзах боломжгүй.")
        if locked.stage in CLOSED_STAGES:
            raise PipelineError("Ажил хүсэгч аль хэдийн хаагдсан байна.")
        from_stage = locked.stage
        locked.stage = target
        locked.reject_reason = reason
        locked.closed_at = timezone.now()
        locked.save(update_fields=["stage", "reject_reason", "closed_at"])
        CandidateEvent.objects.create(candidate=locked, from_stage=from_stage, to_stage=target, note=reason, by=by)
    _log("candidate_rejected", locked, by, f"{_stage_label(from_stage)} -> {_stage_label(target)}")
    candidate.stage, candidate.reject_reason, candidate.closed_at = locked.stage, locked.reject_reason, locked.closed_at
    return locked


def reopen(candidate: Candidate, *, by: User) -> Candidate:
    with transaction.atomic():
        locked = Candidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.stage not in CLOSED_STAGES:
            raise PipelineError("Зөвхөн татгалзсан ажил хүсэгчийг дахин нээнэ.")
        from_stage = locked.stage
        locked.stage = Stage.NEW
        locked.reject_reason = ""
        locked.closed_at = None
        locked.save(update_fields=["stage", "reject_reason", "closed_at"])
        CandidateEvent.objects.create(candidate=locked, from_stage=from_stage, to_stage=Stage.NEW, by=by)
    _log("candidate_reopened", locked, by)
    candidate.stage, candidate.reject_reason, candidate.closed_at = locked.stage, locked.reject_reason, locked.closed_at
    return locked


def comment(candidate: Candidate, *, by: User, text: str) -> CandidateComment:
    text = text.strip()
    if not text:
        raise PipelineError("Сэтгэгдэл хоосон байна.")
    row = CandidateComment.objects.create(candidate=candidate, text=text, by=by)
    _log("candidate_commented", candidate, by)
    return row


def refresh_filled(vacancy: Vacancy) -> Vacancy:
    """Keep `filled` true to the headcount: an open vacancy whose hired count reached it becomes filled, and a filled
    one whose headcount now exceeds the hired count is open again. A closed vacancy stays closed."""
    with transaction.atomic():
        locked = Vacancy.objects.select_for_update().get(pk=vacancy.pk)
        hired_count = Candidate.objects.filter(vacancy=locked, stage=Stage.HIRED).count()
        if locked.status == VacancyStatus.OPEN and hired_count >= locked.headcount:
            locked.status = VacancyStatus.FILLED
        elif locked.status == VacancyStatus.FILLED and hired_count < locked.headcount:
            locked.status = VacancyStatus.OPEN
        else:
            return locked
        locked.save(update_fields=["status"])
    vacancy.status = locked.status
    return locked


def mark_hired(candidate: Candidate, employee: Employee, *, by: User) -> Candidate:
    """Link the hired employee, set `hired`, and mark the vacancy filled once its headcount is reached."""
    with transaction.atomic():
        locked = Candidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.stage == Stage.HIRED or locked.employee_id is not None:
            raise PipelineError("Энэ ажил хүсэгчийг аль хэдийн ажилтан болгосон байна.")
        if locked.stage in CLOSED_STAGES:
            raise PipelineError("Татгалзсан ажил хүсэгчийг ажилд авах боломжгүй.")
        from_stage = locked.stage
        locked.stage = Stage.HIRED
        locked.employee = employee
        locked.save(update_fields=["stage", "employee"])
        CandidateEvent.objects.create(candidate=locked, from_stage=from_stage, to_stage=Stage.HIRED, by=by)
        refresh_filled(Vacancy.objects.get(pk=locked.vacancy_id))
    _log("candidate_hired", locked, by, f"Ажилтан #{employee.pk}")
    candidate.stage, candidate.employee = locked.stage, locked.employee
    return locked


def _months_back(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def purgeable(*, today: date) -> QuerySet[Candidate]:
    """Rejected/withdrawn candidates closed strictly before `today` minus the retention months."""
    cutoff = _months_back(today, RecruitmentSettings.get().retention_months)
    limit = timezone.make_aware(datetime.combine(cutoff, time.min))
    return Candidate.objects.filter(stage__in=CLOSED_STAGES, closed_at__lt=limit)


def purge(*, by: User | None, today: date) -> int:
    """Delete the `purgeable` candidates with their files; one log line with counts, no names."""
    with transaction.atomic():
        ids = list(purgeable(today=today).values_list("pk", flat=True))
        if not ids:
            return 0
        vacancy_ids = sorted(Candidate.objects.filter(pk__in=ids).values_list("vacancy_id", flat=True).distinct())
        paths = list(CandidateFile.objects.filter(candidate_id__in=ids).values_list("file", flat=True))
        Candidate.objects.filter(pk__in=ids).delete()
    files.delete_stored(paths)
    record_safe(
        Category.HR,
        "candidates_purged",
        actor=by,
        target_type="Ажил хүсэгч",
        message=f"{len(ids)} ажил хүсэгч, {len(vacancy_ids)} ажлын байр: " + ", ".join(f"#{pk}" for pk in vacancy_ids),
    )
    return len(ids)

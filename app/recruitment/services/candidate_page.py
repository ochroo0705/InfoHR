"""Candidate page and purge: what the candidate screen shows and which actions it offers, the purge list, and the answer
of the convert link. The rules behind the Django views and the API; this module does not check the right to manage
or visibility (the views and the API look the candidate up first)."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

from accounts.models import User
from accounts.roles import ADMIN
from django.urls import reverse
from employees import access as employee_access

from recruitment.models import (
    Candidate,
    CandidateComment,
    CandidateEvent,
    CandidateFile,
    RecruitmentSettings,
    Stage,
    Vacancy,
)
from recruitment.services import convert, files, pipeline, vacancy_page, visibility


def move_targets(candidate: Candidate) -> list[str]:
    """The stages the candidate may be moved to (each step of the row on the page is a button for these)."""
    return [stage.value for stage in pipeline.MOVABLE_STAGES if stage != candidate.stage]


def confirm_moves(candidate: Candidate) -> list[str]:
    """Moves that ask first: every target except the next step of the process (a back-move or a skip is deliberate)."""
    steps = [stage.value for stage in pipeline.MOVABLE_STAGES]
    here = steps.index(candidate.stage) if candidate.stage in steps else -1
    following = steps[here + 1] if here + 1 < len(steps) else None
    return [stage for stage in steps if stage != candidate.stage and stage != following]


def progress(candidate: Candidate) -> list[tuple[str, str, str]]:
    """(stage, label, state) for each step of the process, state being done, current or todo; none lit when closed."""
    steps = vacancy_page.COUNT_STAGES
    here = steps.index(candidate.stage) if candidate.stage in steps else -1
    return [
        (stage.value, str(stage.label), "done" if i < here else "current" if i == here else "todo")
        for i, stage in enumerate(steps)
    ]


def _comments_context(candidate: Candidate, error: str = "") -> dict[str, Any]:
    return {
        "candidate": candidate,
        "comments": candidate.comments.select_related("by"),
        "comment_error": error,
    }


def _files_context(user: Any, candidate: Candidate, error: str = "") -> dict[str, Any]:
    return {
        "candidate": candidate,
        "cand_files": candidate.files.select_related("uploaded_by"),
        "file_error": error,
        "can_manage": visibility.can_manage(user),
        "max_mb": files.MAX_BYTES // (1024 * 1024),
        "extensions": ", ".join(sorted(files.ALLOWED_EXTENSIONS)),
    }


@dataclass(frozen=True)
class CandidatePage:
    candidate: Candidate
    vacancy: Vacancy
    events: list[CandidateEvent]  # oldest first, with `by`
    comments: list[CandidateComment]  # oldest first, with `by`
    files: list[CandidateFile]  # oldest first, with `uploaded_by`
    can_manage: bool
    progress: list[tuple[str, str, str]]
    move_to: list[str]
    move_confirm: list[str]
    can_reopen: bool
    can_reject: bool
    can_convert: bool
    employee_visible: bool
    max_mb: int
    extensions: str


def candidate_page(user: User, candidate: Candidate) -> CandidatePage:
    """Everything the candidate screen shows for `user`, read in a fixed number of queries per list."""
    manage = visibility.can_manage(user)
    closed = candidate.stage in pipeline.CLOSED_STAGES
    moving = manage and not closed and candidate.stage != Stage.HIRED
    return CandidatePage(
        candidate=candidate,
        vacancy=candidate.vacancy,
        events=list(candidate.events.select_related("by")),
        comments=list(candidate.comments.select_related("by")),
        files=list(candidate.files.select_related("uploaded_by")),
        can_manage=manage,
        progress=progress(candidate),
        move_to=move_targets(candidate) if moving else [],
        move_confirm=confirm_moves(candidate) if moving else [],
        can_reopen=manage and closed,
        can_reject=manage and not closed and candidate.stage != Stage.HIRED,
        can_convert=manage and convert.can_convert(candidate),
        employee_visible=manage
        and candidate.employee_id is not None
        and employee_access.visible_employees(user).filter(pk=candidate.employee_id).exists(),
        max_mb=files.MAX_BYTES // (1024 * 1024),
        extensions=", ".join(sorted(files.ALLOWED_EXTENSIONS)),
    )


# ---- purge ----


@dataclass(frozen=True)
class PurgePage:
    rows: list[Candidate]
    months: int
    is_admin: bool


def purge_page(user: User, today: date) -> PurgePage:
    """The candidates the purge would remove today, with the retention setting and whether the user may change it."""
    rows = list(pipeline.purgeable(today=today).select_related("vacancy").order_by("closed_at", "pk"))
    return PurgePage(
        rows=rows,
        months=RecruitmentSettings.get().retention_months,
        is_admin=user.is_superuser or user.groups.filter(name=ADMIN).exists(),
    )


# ---- convert answer ----


def convert_answer(user: User, candidate: Candidate, today: date) -> tuple[str, str]:
    """(path, error) for the convert link: the hire form path prefilled from the candidate, or the refusal text.

    `user` is kept for the callers' signature; the right to manage is checked by the caller."""
    if not convert.can_convert(candidate):
        return "", convert.refusal(candidate)
    query = urlencode(convert.prefill_params(candidate, today))
    return f"{reverse('employees:add')}?{query}", ""

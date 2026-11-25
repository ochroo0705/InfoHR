"""Vacancy list, vacancy page and vacancy form: the rules behind the vacancy screens (Django views and the API).

Every vacancy and candidate row is read through `recruitment.services.visibility`, so a hiring manager sees only their
own vacancies. The views check the right to manage and pick the HTTP answers; this module does not check rights.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from accounts.audit import Category, record_safe
from accounts.models import User
from django import forms
from django.db.models import Count, Q, QuerySet
from macs.dialect import search_match

from recruitment.forms import VacancyForm
from recruitment.models import Candidate, Stage, Vacancy, VacancyStatus
from recruitment.services import pipeline, visibility

NOT_OPEN = "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. Эхлээд ажлын байрыг нээнэ үү."
STATUS_FILTERS = {"open", "closed", "filled", "all"}
ACTIVE_STAGES = (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER)
COUNT_STAGES = (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER, Stage.HIRED)
MAX_SEARCH = 100


def parse_status(raw: str | None) -> str:
    """The list's status filter: one of open, closed, filled or all; anything else means open."""
    if raw in STATUS_FILTERS:
        return str(raw)
    return "open"


def parse_stage(raw: str | None) -> str:
    """The vacancy page's stage filter: a stage value, open (the active stages) or all; anything else means open."""
    if raw in Stage.values or raw in ("open", "all"):
        return str(raw)
    return "open"


def clean_search(raw: str | None) -> str:
    """The typed search text, stripped and cut to MAX_SEARCH characters."""
    return (raw or "").strip()[:MAX_SEARCH]


def _log(action: str, vacancy: Vacancy, actor: User, message: str = "") -> None:
    record_safe(
        Category.HR,
        action,
        actor=actor,
        target_type="Ажлын байр",
        target_label=f"Ажлын байр #{vacancy.pk}",
        message=message,
    )


# ---- vacancy list ----


def _stage_counts() -> dict[str, Any]:
    return {f"c_{stage.value}": Count("candidates", filter=Q(candidates__stage=stage)) for stage in COUNT_STAGES}


def vacancy_batch(user: User, status: str, q: str, offset: int, size: int) -> tuple[list[Vacancy], bool]:
    """One batch of the vacancy list: the rows from `offset` (at most `size`) and whether more follow.

    `status` is already parsed by `parse_status`; `q` is cut by `clean_search`. Every word must match the title,
    position or department."""
    rows = visibility.visible_vacancies(user)
    if status != "all":
        rows = rows.filter(status=status)
    for word in clean_search(q).split():
        rows = rows.filter(search_match(word, "title", "position__name", "department__name", icase=True))
    rows = (
        rows.select_related("position", "department", "hiring_manager")
        .annotate(**_stage_counts())
        .order_by("-created_at", "-pk")
    )
    page = list(rows[offset : offset + size + 1])
    return page[:size], len(page) > size


# ---- vacancy page ----


@dataclass(frozen=True)
class StageItem:
    key: str
    label: str
    count: int


def stage_bar(vacancy: Vacancy) -> list[StageItem]:
    """The stage bar: «Идэвхтэй» (still in the running), each stage with its count, and «Бүгд». One query."""
    counts = {row["stage"]: row["n"] for row in vacancy.candidates.values("stage").annotate(n=Count("pk"))}
    active = sum(counts.get(stage, 0) for stage in ACTIVE_STAGES)
    return [
        StageItem("open", "Идэвхтэй", active),
        *(StageItem(stage.value, str(stage.label), counts.get(stage.value, 0)) for stage in Stage),
        StageItem("all", "Бүгд", sum(counts.values())),
    ]


def _stage_filter(rows: QuerySet[Candidate], key: str) -> QuerySet[Candidate]:
    if key == "all":
        return rows
    if key in Stage.values:
        return rows.filter(stage=key)
    return rows.filter(stage__in=ACTIVE_STAGES)


def candidate_batch(vacancy: Vacancy, stage_key: str, offset: int, size: int) -> tuple[list[Candidate], bool]:
    """One batch of the vacancy's candidates for a stage key (`parse_stage` output), newest first."""
    rows = _stage_filter(vacancy.candidates.all(), stage_key).order_by("-created_at", "-pk")
    page = list(rows[offset : offset + size + 1])
    return page[:size], len(page) > size


# ---- vacancy form ----


@dataclass(frozen=True)
class VacancyOptions:
    positions: list[tuple[int, str]]
    departments: list[tuple[int, str]]
    branches: list[tuple[int, str]]
    managers: list[tuple[int, str]]
    statuses: list[tuple[str, str]]  # empty for a new vacancy, which has no status field


def _choices(form: VacancyForm, name: str) -> list[tuple[int, str]]:
    field = form.fields[name]
    assert isinstance(field, forms.ModelChoiceField)  # noqa: S101
    return [(obj.pk, field.label_from_instance(obj)) for obj in field.queryset]


def vacancy_options(user: User, current: Vacancy | None) -> VacancyOptions:
    """The choices of the vacancy form, read from the form itself so the form stays the one source."""
    form = VacancyForm(user=user, instance=current)
    statuses: list[tuple[str, str]] = []
    if "status" in form.fields:
        status = form.fields["status"]
        assert isinstance(status, forms.ChoiceField)  # noqa: S101
        statuses = [(str(value), str(label)) for value, label in status.choices]
    return VacancyOptions(
        positions=_choices(form, "position"),
        departments=_choices(form, "department"),
        branches=_choices(form, "branch"),
        managers=_choices(form, "hiring_manager"),
        statuses=statuses,
    )


def candidate_add_refusal(vacancy: Vacancy) -> str:
    """Why a candidate may not be added to this vacancy, or "" when it may. Candidates are added only to an open
    vacancy (ruling 2026-11-02); pipeline.add_candidate does not check it, so the views and the API ask here."""
    return "" if vacancy.status == VacancyStatus.OPEN else NOT_OPEN


def create_vacancy(user: User, data: Mapping[str, Any]) -> tuple[Vacancy | None, VacancyForm]:
    """Save a new vacancy: always open, created by `user`. Returns (None, form) when the form has errors."""
    form = VacancyForm(data, user=user)
    if not form.is_valid():
        return None, form
    vacancy = form.save(commit=False)
    vacancy.status = VacancyStatus.OPEN
    vacancy.created_by = user
    vacancy.save()
    _log("vacancy_created", vacancy, user, vacancy.title)
    return vacancy, form


def update_vacancy(user: User, vacancy: Vacancy, data: Mapping[str, Any]) -> tuple[Vacancy | None, VacancyForm]:
    """Save an edit, then keep `filled` true to the headcount. Returns (None, form) when the form has errors."""
    form = VacancyForm(data, instance=vacancy, user=user)
    if not form.is_valid():
        return None, form
    form.save()
    pipeline.refresh_filled(vacancy)  # a new headcount may fill, or reopen, the vacancy
    _log("vacancy_changed", vacancy, user, vacancy.title)
    return vacancy, form

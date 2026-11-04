"""Recruitment screens: vacancy list and page, candidate page and its actions.

Every vacancy, candidate and file is looked up through `recruitment.access` (so `services.visibility`): an object the
user may not see answers 404. Hiring managers read, download CVs and comment; everything else needs the right to
manage recruitment (403). The rules themselves (stage moves, rejection, files) live in `recruitment.services`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

from accounts.audit import Category, record_safe
from accounts.roles import ADMIN
from config import batching
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST
from employees import access as employee_access
from macs.models import Branch, Position

from recruitment import access
from recruitment.forms import SOURCE_LIST_ID, SOURCE_SUGGESTIONS, CandidateForm, RejectForm, VacancyForm
from recruitment.models import Candidate, RecruitmentSettings, Stage, Vacancy, VacancyStatus
from recruitment.services import convert, files, pipeline, slot_line, visibility

STATUS_FILTERS = {"open", "closed", "filled", "all"}
ACTIVE_STAGES = (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER)
COUNT_STAGES = (Stage.NEW, Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER, Stage.HIRED)
MAX_SEARCH = 100


CONVERT_NOTICE_KEY = "recruitment_convert_notice"


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _problem(message: str) -> HttpResponse:
    """A refusal shown as a red line in place (htmx swaps it into the page's message box)."""
    return HttpResponse(format_html('<p class="rounded bg-red-50 p-2 text-sm text-red-700">{}</p>', message))


def _log(action: str, vacancy: Vacancy, request: HttpRequest, message: str = "") -> None:
    record_safe(
        Category.HR,
        action,
        actor=access.user_of(request),
        target_type="Ажлын байр",
        target_label=f"Ажлын байр #{vacancy.pk}",
        message=message,
    )


# ---- vacancy list ----


def _stage_counts() -> dict[str, Any]:
    return {f"c_{stage.value}": Count("candidates", filter=Q(candidates__stage=stage)) for stage in COUNT_STAGES}


@login_required
@require_GET
def vacancies(request: HttpRequest) -> HttpResponse:
    user = access.user_of(request)
    status = request.GET.get("status", "open")
    if status not in STATUS_FILTERS:
        status = "open"
    q = request.GET.get("q", "").strip()[:MAX_SEARCH]
    rows = visibility.visible_vacancies(user)
    if status != "all":
        rows = rows.filter(status=status)
    for word in q.split():  # every word must match the title, position or department
        rows = rows.filter(
            Q(title__icontains=word) | Q(position__name__icontains=word) | Q(department__name__icontains=word)
        )
    rows = (
        rows.select_related("position", "department", "hiring_manager")
        .annotate(**_stage_counts())
        .order_by("-created_at", "-pk")
    )

    def fetch(offset: int, size: int) -> tuple[list[Vacancy], bool]:
        page = list(rows[offset : offset + size + 1])
        return page[:size], len(page) > size

    batch = batching.paged(request, fetch)
    context = {
        "rows": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "q": q,
        "status": status,
        "can_manage": visibility.can_manage(user),
    }
    template = (
        "recruitment/_vacancy_rows.html" if request.headers.get("HX-Request") else "recruitment/vacancy_list.html"
    )
    return render(request, template, context)


# ---- vacancy add / edit ----


def _vacancy_modal(request: HttpRequest, form: VacancyForm, vacancy: Vacancy | None) -> HttpResponse:
    return render(
        request,
        "recruitment/vacancy_form.html",
        {
            "form": form,
            "title": "Ажлын байр засах" if vacancy else "Ажлын байр нээх",
            "action": request.path,
            "vacancy": vacancy,
        },
    )


def _id_param(raw: str | None) -> int | None:
    return int(raw) if raw and raw.isascii() and raw.isdigit() else None


def _date_param(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


@login_required
@require_GET
def vacancy_slot_line(request: HttpRequest) -> HttpResponse:
    """The budget line for the position, branch and date picked in the vacancy pop-up (htmx, on every change)."""
    access.require_manage(access.user_of(request))
    get = request.GET
    headcount = _id_param(get.get("headcount")) or 1
    position_id, branch_id = _id_param(get.get("position")), _id_param(get.get("branch"))
    line = slot_line.describe(
        position=Position.objects.filter(pk=position_id).first() if position_id is not None else None,
        branch=Branch.objects.filter(pk=branch_id).first() if branch_id is not None else None,
        start=_date_param(get.get("desired_start")),
        headcount=headcount,
        exclude_vacancy=_id_param(get.get("vacancy")),
    )
    return render(request, "recruitment/_slot_line.html", {"line": line})


@login_required
def vacancy_add(request: HttpRequest) -> HttpResponse:
    user = access.user_of(request)
    access.require_manage(user)
    if request.method != "POST":
        return _vacancy_modal(request, VacancyForm(user=user), None)
    form = VacancyForm(request.POST, user=user)
    if not form.is_valid():
        return _vacancy_modal(request, form, None)
    vacancy = form.save(commit=False)
    vacancy.status = VacancyStatus.OPEN
    vacancy.created_by = user
    vacancy.save()
    _log("vacancy_created", vacancy, request, vacancy.title)
    return _done()


@login_required
def vacancy_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    access.require_manage(user)
    if request.method != "POST":
        return _vacancy_modal(request, VacancyForm(instance=vacancy, user=user), vacancy)
    form = VacancyForm(request.POST, instance=vacancy, user=user)
    if not form.is_valid():
        return _vacancy_modal(request, form, vacancy)
    form.save()
    pipeline.refresh_filled(vacancy)  # a new headcount may fill, or reopen, the vacancy
    _log("vacancy_changed", vacancy, request, vacancy.title)
    return _done()


# ---- vacancy page ----


@dataclass(frozen=True)
class StageItem:
    key: str
    label: str
    count: int


def _stage_bar(vacancy: Vacancy) -> list[StageItem]:
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


@login_required
@require_GET
def vacancy_detail(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    key = request.GET.get("stage", "open")
    if key not in Stage.values and key not in ("open", "all"):
        key = "open"
    rows = _stage_filter(vacancy.candidates.all(), key).order_by("-created_at", "-pk")

    def fetch(offset: int, size: int) -> tuple[list[Candidate], bool]:
        page = list(rows[offset : offset + size + 1])
        return page[:size], len(page) > size

    batch = batching.paged(request, fetch)
    manage = visibility.can_manage(user)
    context = {
        "vacancy": vacancy,
        "slot_line": slot_line.describe(
            position=vacancy.position,
            branch=vacancy.branch,
            start=vacancy.desired_start,
            headcount=vacancy.headcount,
            exclude_vacancy=vacancy.pk,
        )
        if manage and vacancy.status == VacancyStatus.OPEN
        else None,
        "stage_bar": _stage_bar(vacancy),
        "stage_key": key,
        "rows": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "can_manage": visibility.can_manage(user),
        "is_open": vacancy.status == VacancyStatus.OPEN,
    }
    if request.headers.get("HX-Request") and batch.offset:  # the «Цааш харуулах» pill asks for rows only
        return render(request, "recruitment/_candidate_rows.html", context)
    return render(request, "recruitment/vacancy_detail.html", context)


# ---- candidate add ----


def _candidate_modal(
    request: HttpRequest, vacancy: Vacancy, form: CandidateForm | None, error: str = ""
) -> HttpResponse:
    return render(
        request,
        "recruitment/candidate_form.html",
        {
            "form": form,
            "vacancy": vacancy,
            "title": "Ажил хүсэгч нэмэх",
            "action": request.path,
            "error": error,
            "source_list_id": SOURCE_LIST_ID,
            "source_suggestions": SOURCE_SUGGESTIONS,
        },
    )


NOT_OPEN = "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. Эхлээд ажлын байрыг нээнэ үү."


@login_required
def candidate_add(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    access.require_manage(user)
    # Ruling (2026-11-02): candidates are added only to an open vacancy; the service itself does not check this.
    if vacancy.status != VacancyStatus.OPEN:
        return _candidate_modal(request, vacancy, None, NOT_OPEN)
    if request.method != "POST":
        return _candidate_modal(request, vacancy, CandidateForm())
    form = CandidateForm(request.POST)
    if not form.is_valid():
        return _candidate_modal(request, vacancy, form)
    pipeline.add_candidate(vacancy, by=user, **form.cleaned_data)
    return _done()


# ---- candidate page ----


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


@login_required
@require_GET
def candidate_detail(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    manage = visibility.can_manage(user)
    closed = candidate.stage in pipeline.CLOSED_STAGES
    context: dict[str, Any] = {
        "candidate": candidate,
        "vacancy": candidate.vacancy,
        "events": candidate.events.select_related("by"),
        "can_manage": manage,
        "progress": _progress(candidate),
        "move_to": _move_targets(candidate) if manage and not closed and candidate.stage != Stage.HIRED else [],
        "move_confirm": _confirm_moves(candidate) if manage and not closed and candidate.stage != Stage.HIRED else [],
        "can_reopen": manage and closed,
        "can_reject": manage and not closed and candidate.stage != Stage.HIRED,
        "can_convert": manage and convert.can_convert(candidate),
        "notice": request.session.pop(CONVERT_NOTICE_KEY, "") if manage else "",
        "employee_visible": manage
        and candidate.employee_id is not None
        and employee_access.visible_employees(user).filter(pk=candidate.employee_id).exists(),
        **_comments_context(candidate),
        **_files_context(user, candidate),
    }
    return render(request, "recruitment/candidate_detail.html", context)


def _move_targets(candidate: Candidate) -> list[str]:
    """The stages the candidate may be moved to (each step of the row on the page is a button for these)."""
    return [stage.value for stage in pipeline.MOVABLE_STAGES if stage != candidate.stage]


def _confirm_moves(candidate: Candidate) -> list[str]:
    """Moves that ask first: every target except the next step of the process (a back-move or a skip is deliberate)."""
    steps = [stage.value for stage in pipeline.MOVABLE_STAGES]
    here = steps.index(candidate.stage) if candidate.stage in steps else -1
    following = steps[here + 1] if here + 1 < len(steps) else None
    return [stage for stage in steps if stage != candidate.stage and stage != following]


def _progress(candidate: Candidate) -> list[tuple[str, str, str]]:
    """(stage, label, state) for each step of the process, state being done, current or todo; none lit when closed."""
    here = COUNT_STAGES.index(candidate.stage) if candidate.stage in COUNT_STAGES else -1
    return [
        (stage.value, str(stage.label), "done" if i < here else "current" if i == here else "todo")
        for i, stage in enumerate(COUNT_STAGES)
    ]


# ---- candidate actions ----


@login_required
@require_POST
def candidate_move(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    access.require_manage(user)
    try:
        pipeline.move(candidate, request.POST.get("to", ""), by=user, note=request.POST.get("note", ""))
    except pipeline.PipelineError as error:
        return _problem(error.message)
    return _done()


def _reject_modal(request: HttpRequest, candidate: Candidate, form: RejectForm, error: str = "") -> HttpResponse:
    return render(
        request,
        "recruitment/candidate_reject.html",
        {"form": form, "candidate": candidate, "action": request.path, "error": error},
    )


@login_required
def candidate_reject(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    access.require_manage(user)
    if request.method != "POST":
        return _reject_modal(request, candidate, RejectForm())
    form = RejectForm(request.POST)
    if not form.is_valid():
        return _reject_modal(request, candidate, form)
    try:
        pipeline.reject(
            candidate, by=user, reason=form.cleaned_data["reason"], withdrawn=form.cleaned_data["withdrawn"]
        )
    except pipeline.PipelineError as error:
        return _reject_modal(request, candidate, form, error.message)
    return _done()


@login_required
@require_POST
def candidate_reopen(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    access.require_manage(user)
    try:
        pipeline.reopen(candidate, by=user)
    except pipeline.PipelineError as error:
        return _problem(error.message)
    return _done()


@login_required
@require_POST
def candidate_comment(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)  # any user who sees the candidate may comment
    error = ""
    try:
        pipeline.comment(candidate, by=user, text=request.POST.get("text", ""))
    except pipeline.PipelineError as exc:
        error = exc.message
    return render(request, "recruitment/_comments.html", _comments_context(candidate, error))


@login_required
@require_POST
def candidate_file_upload(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    access.require_manage(user)
    error = ""
    upload = request.FILES.get("file")
    if upload is None:
        error = "Файл сонгоно уу."
    else:
        try:
            files.save(candidate, upload, by=user)
        except files.FileRejected as exc:
            error = exc.message
    return render(request, "recruitment/_files.html", _files_context(user, candidate, error))


@login_required
@require_GET
def candidate_file(request: HttpRequest, pk: int) -> FileResponse:
    user = access.user_of(request)
    row = access.file_or_404(user, pk)
    try:
        return files.open(row, by=user)
    except FileNotFoundError as exc:  # the row exists but the stored file is gone
        raise Http404 from exc


# ---- convert to employee, purge ----


@login_required
@require_GET
def candidate_convert(request: HttpRequest, pk: int) -> HttpResponse:
    """Open the hire form prefilled from the candidate; the link is made only when the hire is saved."""
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    access.require_manage(user)
    if not convert.can_convert(candidate):
        request.session[CONVERT_NOTICE_KEY] = convert.refusal(candidate)  # shown once on the candidate page
        return redirect("recruitment:candidate_detail", pk=candidate.pk)
    query = urlencode(convert.prefill_params(candidate, timezone.localdate()))
    return redirect(f"{reverse('employees:add')}?{query}")


@login_required
def purge(request: HttpRequest) -> HttpResponse:
    user = access.user_of(request)
    access.require_manage(user)
    today = timezone.localdate()
    if request.method == "POST":
        count = pipeline.purge(by=user, today=today)
        return redirect(f"{reverse('recruitment:purge')}?done={count}")
    done = request.GET.get("done", "")
    rows = list(pipeline.purgeable(today=today).select_related("vacancy").order_by("closed_at", "pk"))
    context = {
        "rows": rows,
        "months": RecruitmentSettings.get().retention_months,
        "is_admin": user.is_superuser or user.groups.filter(name=ADMIN).exists(),
        "done": int(done) if done.isascii() and done.isdigit() and len(done) < 9 else None,
    }
    return render(request, "recruitment/purge.html", context)

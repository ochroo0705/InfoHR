"""Recruitment screens: vacancy list and page, candidate page and its actions.

Every vacancy, candidate and file is looked up through `recruitment.access` (so `services.visibility`): an object the
user may not see answers 404. Hiring managers read, download CVs and comment; everything else needs the right to
manage recruitment (403). The rules themselves (stage moves, rejection, files) live in `recruitment.services`.
"""

from datetime import date
from typing import Any

from config import batching
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST
from macs.models import Branch, Position

from recruitment import access
from recruitment.forms import SOURCE_LIST_ID, SOURCE_SUGGESTIONS, CandidateForm, RejectForm, VacancyForm
from recruitment.models import Candidate, Vacancy, VacancyStatus
from recruitment.services import candidate_page, files, pipeline, slot_line, vacancy_page, visibility
from recruitment.services.candidate_page import _comments_context, _files_context

CONVERT_NOTICE_KEY = "recruitment_convert_notice"


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _problem(message: str) -> HttpResponse:
    """A refusal shown as a red line in place (htmx swaps it into the page's message box)."""
    return HttpResponse(format_html('<p class="rounded bg-red-50 p-2 text-sm text-red-700">{}</p>', message))


# ---- vacancy list ----


@login_required
@require_GET
def vacancies(request: HttpRequest) -> HttpResponse:
    user = access.user_of(request)
    status = vacancy_page.parse_status(request.GET.get("status"))
    q = vacancy_page.clean_search(request.GET.get("q"))
    batch = batching.paged(request, lambda offset, size: vacancy_page.vacancy_batch(user, status, q, offset, size))
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
    created, form = vacancy_page.create_vacancy(user, request.POST)
    if created is None:
        return _vacancy_modal(request, form, None)
    return _done()


@login_required
def vacancy_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    access.require_manage(user)
    if request.method != "POST":
        return _vacancy_modal(request, VacancyForm(instance=vacancy, user=user), vacancy)
    updated, form = vacancy_page.update_vacancy(user, vacancy, request.POST)
    if updated is None:
        return _vacancy_modal(request, form, vacancy)
    return _done()


# ---- vacancy page ----


@login_required
@require_GET
def vacancy_detail(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    key = vacancy_page.parse_stage(request.GET.get("stage"))
    batch = batching.paged(request, lambda offset, size: vacancy_page.candidate_batch(vacancy, key, offset, size))
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
        "stage_bar": vacancy_page.stage_bar(vacancy),
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


NOT_OPEN = vacancy_page.NOT_OPEN  # re-exported: existing tests import it from this module


@login_required
def candidate_add(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    vacancy = access.vacancy_or_404(user, pk)
    access.require_manage(user)
    # Ruling (2026-11-02): candidates are added only to an open vacancy; the service itself does not check this.
    refusal = vacancy_page.candidate_add_refusal(vacancy)
    if refusal:
        return _candidate_modal(request, vacancy, None, refusal)
    if request.method != "POST":
        return _candidate_modal(request, vacancy, CandidateForm())
    form = CandidateForm(request.POST)
    if not form.is_valid():
        return _candidate_modal(request, vacancy, form)
    pipeline.add_candidate(vacancy, by=user, **form.cleaned_data)
    return _done()


# ---- candidate page ----


@login_required
@require_GET
def candidate_detail(request: HttpRequest, pk: int) -> HttpResponse:
    user = access.user_of(request)
    candidate = access.candidate_or_404(user, pk)
    page = candidate_page.candidate_page(user, candidate)
    context: dict[str, Any] = {
        "candidate": candidate,
        "vacancy": page.vacancy,
        "events": page.events,
        "can_manage": page.can_manage,
        "progress": page.progress,
        "move_to": page.move_to,
        "move_confirm": page.move_confirm,
        "can_reopen": page.can_reopen,
        "can_reject": page.can_reject,
        "can_convert": page.can_convert,
        "notice": request.session.pop(CONVERT_NOTICE_KEY, "") if page.can_manage else "",
        "employee_visible": page.employee_visible,
        "comments": page.comments,
        "comment_error": "",
        "cand_files": page.files,
        "file_error": "",
        "max_mb": page.max_mb,
        "extensions": page.extensions,
    }
    return render(request, "recruitment/candidate_detail.html", context)


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
    path, error = candidate_page.convert_answer(user, candidate, timezone.localdate())
    if error:
        request.session[CONVERT_NOTICE_KEY] = error  # shown once on the candidate page
        return redirect("recruitment:candidate_detail", pk=candidate.pk)
    return redirect(path)


@login_required
def purge(request: HttpRequest) -> HttpResponse:
    user = access.user_of(request)
    access.require_manage(user)
    today = timezone.localdate()
    if request.method == "POST":
        count = pipeline.purge(by=user, today=today)
        return redirect(f"{reverse('recruitment:purge')}?done={count}")
    done = request.GET.get("done", "")
    page = candidate_page.purge_page(user, today)
    context = {
        "rows": page.rows,
        "months": page.months,
        "is_admin": page.is_admin,
        "done": int(done) if done.isascii() and done.isdigit() and len(done) < 9 else None,
    }
    return render(request, "recruitment/purge.html", context)

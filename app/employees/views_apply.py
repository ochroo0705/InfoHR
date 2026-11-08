"""The public employee form: no login, reached only through the token in the link.

Spec: docs/superpowers/specs/2026-11-08-employee-self-form-design.md. The no-store and same-origin referrer headers are
set for every /apply/ response by employees.selfform.middleware.SelfFormHeadersMiddleware, not here.
"""

import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

from accounts import audit_context
from django import forms
from django.core.exceptions import SuspiciousOperation
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse, QueryDict
from django.shortcuts import render

from employees.forms import EducationRowForm, EmployeeForm, FamilyRowForm, HireContactForm
from employees.models import CompanySettings, SelfFormInvitation, SelfFormStatus
from employees.selfform import service, throttle
from employees.selfform.answers import (
    CONTACT_FIELDS,
    EDUCATION_FIELDS,
    FAMILY_FIELDS,
    MAX_BODY_BYTES,
    MSG_BODY_TOO_LARGE,
    PERSON_FIELDS,
    REQUIRED_PERSON,
    AnswerErrors,
    store_photo,
)
from employees.selfform.notice import notice_digest, notice_for
from employees.selfform.postform import EDU_PREFIX, FAM_PREFIX, answers_from_post, initial_from_answers
from employees.selfform.service import NoticeChangedError, SelfFormError

UNKNOWN_TOKEN_LIMIT = 20  # lookups of unknown tokens per IP ...
UNKNOWN_TOKEN_WINDOW = 600  # ... within this many seconds
FIELDS_TO_CHECK = "Доорх талбаруудыг шалгаад дахин илгээнэ үү."
MSG_TOO_MANY_FIELDS = "Оруулсан мэдээлэл хэт их байна. Энэ удаа хадгалагдсангүй."

_PREFIX_BY_KEY = {"education": EDU_PREFIX, "family": FAM_PREFIX}
ROW_PLACEHOLDER = "__i__"  # the index of a row in the <template data-row-template>; the script replaces it


@dataclass
class _Field:
    """One input as the template draws it. Names, labels and choices come from the real forms."""

    name: str
    label: str
    required: bool
    value: str
    input_type: str
    max_length: int | None
    choices: list[tuple[str, str]] | None
    errors: list[str] = field(default_factory=list)


def _page(request: HttpRequest, name: str, status: int = 200, **context: Any) -> HttpResponse:
    return render(request, f"employees/selfform/{name}", context, status=status)


def _unknown_token(request: HttpRequest) -> HttpResponse:
    """The answer for any token that is not a known invitation: 404, or 429 after too many tries from one IP.

    Every malformed or unknown path gets this same page, so no answer tells a guesser what the token looked like.
    """
    ip = audit_context.current_ip() or request.META.get("REMOTE_ADDR") or None
    if not throttle.allow(ip, "apply-unknown", limit=UNKNOWN_TOKEN_LIMIT, window_seconds=UNKNOWN_TOKEN_WINDOW):
        return _page(request, "not_found.html", status=429, too_many=True)
    return _page(request, "not_found.html", status=404)


def apply_not_found(request: HttpRequest, **_: Any) -> HttpResponse:
    """Any other path under /apply/ (a token with a slash, for example) gets the unknown-token answer."""
    return _unknown_token(request)


def _lookup(request: HttpRequest, token: str) -> SelfFormInvitation | HttpResponse:
    """The invitation for the token, or the unknown-token answer."""
    invitation = service.get_for_token(token)
    if invitation is not None:
        return invitation
    return _unknown_token(request)


def _stored_answers(invitation: SelfFormInvitation) -> dict[str, Any]:
    try:
        data = json.loads(invitation.answers or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _answer_list(answers: dict[str, Any], key: str) -> list[Any]:
    value = answers.get(key)
    return value if isinstance(value, list) else []


def _form_body_size(post: QueryDict) -> int:
    """Length of the posted text (names and values), files left out."""
    return sum(len(key) + len(value) for key, values in post.lists() for value in values)


def _html_name(path: str) -> str | None:
    """The input name for an error path such as person.register_no or education.2.start_year; None if no input."""
    parts = path.split(".")
    if len(parts) == 2 and parts[0] in ("person", "contact"):
        return f"{parts[0]}-{parts[1]}"
    if len(parts) == 3 and parts[0] in _PREFIX_BY_KEY and parts[1].isdigit():
        return f"{_PREFIX_BY_KEY[parts[0]]}-{parts[1]}-{parts[2]}"
    return None


def _split_errors(errors: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[str]]:
    """Errors that belong to one input (by input name), and the messages that belong to the whole form."""
    by_field: dict[str, list[str]] = {}
    whole: list[str] = []
    for path, messages in errors.items():
        name = _html_name(path)
        if name is None:
            whole.extend(messages)
        else:
            by_field.setdefault(name, []).extend(messages)
    return by_field, whole


def _field(
    form_field: forms.Field,
    name: str,
    initial: dict[str, str],
    errors: dict[str, list[str]],
    *,
    required: bool,
) -> _Field:
    choices: list[tuple[str, str]] | None = None
    if isinstance(form_field, forms.ModelChoiceField):
        queryset: Any = form_field.queryset
        choices = [("", "")] + [(str(obj.pk), form_field.label_from_instance(obj)) for obj in queryset]
    elif isinstance(form_field, forms.ChoiceField):
        options = cast("list[tuple[Any, Any]]", form_field.choices)
        choices = [("", "")] + [(str(value), str(label)) for value, label in options if value not in (None, "")]
    if isinstance(form_field, forms.DateField):
        input_type = "date"
    elif isinstance(form_field, forms.EmailField):
        input_type = "email"
    else:
        input_type = "text"
    max_length = getattr(form_field, "max_length", None)
    return _Field(
        name=name,
        label=str(form_field.label),
        required=required,
        value=initial.get(name, ""),
        input_type=input_type,
        max_length=max_length if isinstance(max_length, int) else None,
        choices=choices,
        errors=errors.get(name, []),
    )


def _rows(
    row_form: forms.Form,
    prefix: str,
    names: tuple[str, ...],
    stored: list[Any],
    initial: dict[str, str],
    errors: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """One entry per stored row, or one blank row when there are none. Each entry lists its inputs."""
    rows: list[dict[str, Any]] = []
    for index in range(max(1, len(stored))):
        inputs = [
            _field(
                row_form.fields[name],
                f"{prefix}-{index}-{name}",
                initial,
                errors,
                required=row_form.fields[name].required,
            )
            for name in names
        ]
        rows.append({"index": index, "fields": inputs})
    return rows


def _template_row(row_form: forms.Form, prefix: str, names: tuple[str, ...]) -> dict[str, Any]:
    """A blank row whose input names carry ROW_PLACEHOLDER instead of an index (the <template> the script clones)."""
    inputs = [
        _field(
            row_form.fields[name],
            f"{prefix}-{ROW_PLACEHOLDER}-{name}",
            {},
            {},
            required=row_form.fields[name].required,
        )
        for name in names
    ]
    return {"index": ROW_PLACEHOLDER, "fields": inputs}


def _form_page(
    request: HttpRequest,
    invitation: SelfFormInvitation,
    answers: dict[str, Any],
    errors: dict[str, list[str]],
    *,
    status: int,
    agreed: bool,
    consent: bool,
) -> HttpResponse:
    """The form filled with the given answers (stored or posted), with the errors next to their inputs."""
    initial = initial_from_answers(answers)
    by_field, whole = _split_errors(errors)
    if by_field:
        whole.insert(0, FIELDS_TO_CHECK)
    person_form = EmployeeForm()
    contact_form = HireContactForm()
    notice = notice_for(CompanySettings.get())
    context = {
        "person_fields": [
            _field(person_form.fields[name], f"person-{name}", initial, by_field, required=name in REQUIRED_PERSON)
            for name in PERSON_FIELDS
        ],
        "education_rows": _rows(
            EducationRowForm(),
            EDU_PREFIX,
            EDUCATION_FIELDS,
            _answer_list(answers, "education"),
            initial,
            by_field,
        ),
        "family_rows": _rows(
            FamilyRowForm(),
            FAM_PREFIX,
            FAMILY_FIELDS,
            _answer_list(answers, "family"),
            initial,
            by_field,
        ),
        "contact_fields": [
            _field(contact_form.fields[name], f"contact-{name}", initial, by_field, required=False)
            for name in CONTACT_FIELDS
        ],
        "education_template": _template_row(EducationRowForm(), EDU_PREFIX, EDUCATION_FIELDS),
        "family_template": _template_row(FamilyRowForm(), FAM_PREFIX, FAMILY_FIELDS),
        "token": invitation.token,
        "notice": notice,
        "notice_digest": notice_digest(notice),
        "hr_note": invitation.hr_note,
        "has_photo": bool(invitation.photo_b64),
        "errors": whole,
        "agreed_correct": agreed,
        "consent": consent,
    }
    return _page(request, "apply.html", status=status, **context)


def _keep_draft(invitation: SelfFormInvitation, answers: dict[str, Any]) -> None:
    """Saves what was posted, so a refused submit loses nothing. A draft that cannot be saved is ignored."""
    with suppress(AnswerErrors, SelfFormError):
        service.save_draft(invitation, answers)


def _submit(request: HttpRequest, invitation: SelfFormInvitation) -> HttpResponse:
    try:
        # The first access parses the body; Django raises SuspiciousOperation when it has too many fields or is too big.
        body_size = _form_body_size(request.POST)
        upload = request.FILES.get("photo")
    except SuspiciousOperation:
        return _form_page(
            request,
            invitation,
            _stored_answers(invitation),
            {"body": [MSG_TOO_MANY_FIELDS]},
            status=413,
            agreed=False,
            consent=False,
        )
    if body_size > MAX_BODY_BYTES:
        return _form_page(
            request,
            invitation,
            _stored_answers(invitation),
            {"body": [MSG_BODY_TOO_LARGE]},
            status=400,
            agreed=False,
            consent=False,
        )
    answers = answers_from_post(request.POST)
    agreed = bool(request.POST.get("agreed_correct"))
    consent = bool(request.POST.get("consent"))
    # The digest of the consent text the person read. A form without one (an old page) skips that check.
    posted_digest = request.POST.get("notice_digest") or None
    photo_b64 = ""
    errors: dict[str, list[str]] = {}
    try:
        if upload is not None:
            photo_b64 = store_photo(upload)
        service.submit(
            invitation,
            answers,
            photo_b64=photo_b64,
            agreed_correct=agreed,
            consent=consent,
            notice_digest=posted_digest,
        )
    except AnswerErrors as exc:
        errors = exc.errors
    except NoticeChangedError as exc:
        errors = {"form": [str(exc)]}
        agreed = consent = False  # the ticks were for the text they read, not for the new one
    except SelfFormError as exc:
        # Refused because the form is no longer open: a repeated send (a double tap, or a second tab) that came after
        # an earlier one. Answer by the row as it is now: sent means done, anything else means closed.
        invitation.refresh_from_db(fields=["status", "purged_at"])
        if invitation.status == SelfFormStatus.SUBMITTED:
            return _page(request, "done.html")
        if not service.is_fillable(invitation):
            return _page(request, "closed.html")
        errors = {"form": [str(exc)]}
    else:
        return _page(request, "done.html")
    _keep_draft(invitation, answers)
    return _form_page(request, invitation, answers, errors, status=400, agreed=agreed, consent=consent)


def apply_form(request: HttpRequest, token: str) -> HttpResponse:
    """GET: the form (with the stored answers and the HR note). POST: the final submit."""
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    found = _lookup(request, token)
    if isinstance(found, HttpResponse):
        return found
    if request.method == "POST" and found.status == SelfFormStatus.SUBMITTED:
        return _submit(request, found)  # a repeated send: _submit answers with the done page, not the closed one
    if not service.is_fillable(found):
        return _page(request, "closed.html")
    if request.method == "POST":
        return _submit(request, found)
    return _form_page(request, found, _stored_answers(found), {}, status=200, agreed=False, consent=False)


def apply_draft(request: HttpRequest, token: str) -> HttpResponse:
    """POST only, JSON answers: saves what the employee has typed so far and keeps the form open."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    found = _lookup(request, token)
    if isinstance(found, HttpResponse):
        return found
    if not service.is_fillable(found):
        return JsonResponse({"error": "closed"}, status=409)
    # The size is read from the header first, so an oversized body is not parsed.
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return JsonResponse({"error": "bad_request"}, status=400)
    if length > MAX_BODY_BYTES:
        return JsonResponse({"error": "too_large"}, status=413)
    try:
        answers = answers_from_post(request.POST)
    except SuspiciousOperation:
        return JsonResponse({"error": "too_large"}, status=413)
    try:
        service.save_draft(found, answers)
    except AnswerErrors as exc:
        return JsonResponse({"errors": exc.errors}, status=400)
    except SelfFormError:
        return JsonResponse({"error": "closed"}, status=409)
    return HttpResponse(status=204)

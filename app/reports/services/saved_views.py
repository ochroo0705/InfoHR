"""The saved views («Хадгалах», «Засах», «Устгах»), request-free: a save cleans the address for its author, the rules
for who may change a view and which default it may displace, and the name clash. The Django views and the React API
both call these, so a rule has one home. Nothing here reads a request: the caller passes the viewer, the report or
the view, and the data (a QueryDict or a dict of the form's fields). The errors come back in a SaveResult, as the
form's own field and form error lists, so each caller shows them its own way."""

from dataclasses import dataclass, field
from typing import Any

from accounts.models import User
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404

from reports import registry
from reports.filters import parse_filters, to_query
from reports.forms import SavedViewForm
from reports.models import SavedView
from reports.services.page_head import PRIVATE, SHARED, _cleaned_for, _may_change, _sees_private
from reports.types import Report

DUPLICATE_NAME = "Ийм нэртэй харагдац байна."
TOO_LONG = "Харагдац хэт урт байна."
NAME_CONSTRAINT = "reports_savedview_unique_name"  # UniqueConstraint(report, name) on SavedView
QUERY_LIMIT = SavedView._meta.get_field("query").max_length  # the stored query is cut at this many characters


@dataclass
class SaveResult:
    """The outcome of a save: the view when it was stored (else None), and the errors that refused it. The field
    errors map a form field to its messages; the form errors are the messages not tied to one field."""

    view: SavedView | None
    field_errors: dict[str, list[str]] = field(default_factory=dict)
    form_errors: list[str] = field(default_factory=list)


def saveable_report(user: User, key: str) -> Report:
    """The report of a saved view: 404 when it keeps no saved views, 403 when the user may not open it."""
    report = registry.get(key)
    if report is None or not report.saved_views:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    return report


def view_for(user: User, pk: int) -> SavedView:
    """A saved view the user may rename or delete: 404 if missing or another user's private view, 403 if the user may
    not change it."""
    view = get_object_or_404(SavedView, pk=pk)
    if view.visibility == PRIVATE and not _sees_private(user, view):
        raise Http404  # a private view is not visible to anyone else, a manager included
    saveable_report(user, view.report)
    if not _may_change(user, view):
        raise PermissionDenied
    return view


def initial_query(get: QueryDict) -> str:
    """The hidden query of the «Хадгалах» pop-up: the report address the user is looking at."""
    return to_query(parse_filters(get))


def default_allowed(user: User, report_key: str, pk: int | None) -> bool:
    """May this user make the view `pk` the report's default? Yes when no other view is the default, or when they may
    change the current default (its author, or a manager). A plain author cannot displace someone else's default."""
    current = SavedView.objects.filter(report=report_key, is_default=True)
    if pk is not None:
        current = current.exclude(pk=pk)
    current_default = current.first()
    return current_default is None or _may_change(user, current_default)


def clear_defaults(report_key: str, keep: int | None = None) -> None:
    """Unsets the report's default view, except `keep`: a report has at most one default. Runs inside the caller's
    transaction, so a refused save puts the old default back."""
    others = SavedView.objects.filter(report=report_key, is_default=True)
    if keep is not None:
        others = others.exclude(pk=keep)
    others.update(is_default=False)


def visibility_and_default(form: SavedViewForm) -> tuple[str, bool]:
    """The view's visibility (blank is shared) and whether it opens first. Only a shared view can be the default."""
    visibility = form.cleaned_data["visibility"] or SHARED
    return visibility, bool(form.cleaned_data["is_default"]) and visibility == SHARED


def is_name_clash(error: IntegrityError) -> bool:
    """True when the database refused the (report, name) pair; any other integrity error is not ours to hide.
    Accepted (decision, low impact): the name is unique across private views too, so a clash reveals that another
    user's private view has that name; removing it needs a schema change."""
    diag = getattr(error.__cause__, "diag", None)  # psycopg puts the violated constraint's name here
    if getattr(diag, "constraint_name", None) == NAME_CONSTRAINT:
        return True
    # Firebird has no such attribute: its message names the (upper-case) index, e.g. ... "REPORTS_SAVEDVIEW_UNIQUE..."
    return diag is None and NAME_CONSTRAINT in str(error).lower()


def _refused(form: SavedViewForm) -> SaveResult:
    """The form's own errors, as the save's result (the form did not validate, so nothing is stored)."""
    field_errors = {name: [str(m) for m in msgs] for name, msgs in form.errors.items() if name != NON_FIELD_ERRORS}
    return SaveResult(view=None, field_errors=field_errors, form_errors=[str(m) for m in form.non_field_errors()])


def create_view(user: User, report: Report, data: QueryDict | dict[str, Any]) -> SaveResult:
    """Stores the cleaned address of the report under the posted name. Every user who can open the report sees it."""
    form = SavedViewForm(data)
    if not form.is_valid():
        return _refused(form)
    # never the raw text: what the author may not use or see (a hidden filter, rule, sort or group) is not stored
    query = to_query(_cleaned_for(user, report, parse_filters(QueryDict(form.cleaned_data["query"]))))
    if QUERY_LIMIT is not None and len(query) > QUERY_LIMIT:
        return SaveResult(view=None, form_errors=[TOO_LONG])
    visibility, wants_default = visibility_and_default(form)
    make_default = wants_default and default_allowed(user, report.key, None)  # not displacing someone else's default
    try:
        with transaction.atomic():
            if make_default:
                clear_defaults(report.key)
            view = SavedView.objects.create(
                report=report.key,
                name=form.cleaned_data["name"],
                query=query,
                author=user,
                visibility=visibility,
                is_default=make_default,
            )
    except IntegrityError as error:
        if not is_name_clash(error):
            raise
        return SaveResult(view=None, field_errors={"name": [DUPLICATE_NAME]})
    return SaveResult(view=view)


def update_view(user: User, view: SavedView, data: QueryDict | dict[str, Any]) -> SaveResult:
    """Renames the view and changes who sees it and whether it opens first. A post that names no visibility keeps the
    view's own."""
    data = data.copy()
    data.setdefault("visibility", view.visibility)
    form = SavedViewForm(data)
    if not form.is_valid():
        return _refused(form)
    name = form.cleaned_data["name"]
    visibility, wants_default = visibility_and_default(form)
    is_default = wants_default and default_allowed(user, view.report, view.pk)
    original = (view.name, view.visibility, view.is_default)
    view.name, view.visibility, view.is_default = name, visibility, is_default  # the save writes these
    try:
        with transaction.atomic():
            if view.is_default:
                clear_defaults(view.report, keep=view.pk)
            view.save(update_fields=["name", "visibility", "is_default", "updated_at"])
    except IntegrityError as error:
        view.name, view.visibility, view.is_default = original  # a refused save leaves the caller's object as it was
        if not is_name_clash(error):
            raise
        return SaveResult(view=None, field_errors={"name": [DUPLICATE_NAME]})
    return SaveResult(view=view)


def delete_view(user: User, view: SavedView) -> str:
    """Deletes the view and returns its report key. Only the author or a manager may delete it."""
    if not _may_change(user, view):
        raise PermissionDenied
    key = view.report
    view.delete()
    return key

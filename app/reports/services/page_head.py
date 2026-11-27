"""The report page's head, request-free: the default-view redirect, the saved views (the options, the starter templates,
the one the address matches and whether the viewer may change it), the tool flags with their export and selection
rights, the staff actions, the title and the layout switcher. The Django report page and the React API both call these,
so a rule has one home. Nothing here reads a request: the caller passes the QueryDict, the path and the viewer.

default_view_redirect() is split out so the Django view can answer the redirect before it builds the table (the old
order); page_head() calls it too, for the API. page_head() takes the request method as a keyword (default "GET"): the
API is read-only, and the Django view checks the real method itself before calling default_view_redirect()."""

from dataclasses import dataclass, replace
from typing import Any

from accounts.models import User
from checklists import access as checklist_access
from django.db.models import Q, QuerySet
from django.http import QueryDict
from django.urls import reverse
from employees import access

from reports import marks as marks_mod
from reports import rules as rules_mod
from reports import selection as selection_mod
from reports import totals as totals_mod
from reports.filters import Filters, parse_filters, to_query
from reports.layouts import offered_layouts
from reports.models import SavedView
from reports.page_rules import PLAIN_VIEW, added_names, address, offered_adds
from reports.starter import resolved_query
from reports.table import Table, allowed_columns, offered_filters, restricted_filters, usable_filters
from reports.types import Report, Template

EXPORT_PERM = "accounts.export_lists"  # the Excel file and its button
SHARED = "shared"  # SavedView.visibility: every user who may open the report sees the view
PRIVATE = "private"  # SavedView.visibility: only the author sees the view
MANAGE_PERM = "reports.manage_saved_views"  # may change any saved view, and see private views with no author
SELECTION_KEYS = ("excel", "csv", "print", "copy", "checklist")  # the bulk actions of the selection bar
LAYOUT_LABELS = {  # the switcher's labels (UI_RULES §4b)
    "table": "Хүснэгт",
    "board": "Самбар",
    "calendar": "Хуанли",
    "timeline": "Цагийн шугам",
    "cards": "Карт",
    "chart": "Диаграм",
    "pivot": "Хөрвүүлэлт",
}
# the nine parameters of the newer layouts: blanked wherever a layout's own parameters are blanked
NEW_LAYOUT_BLANKS: dict[str, Any] = {
    name: "" for name in ("lgrain", "lshow", "lsort", "lorder", "lrep", "lweek", "lyear", "lgroup", "lval2")
}


@dataclass(frozen=True)
class SavedOption:
    name: str
    url: str  # the report's address with this view's query
    selected: bool  # the address shows this view's setup now


@dataclass(frozen=True)
class LayoutOption:
    """One segment of the switcher: its key, label, address and whether it is the layout on screen."""

    name: str
    label: str
    url: str
    current: bool


@dataclass(frozen=True)
class SavedHead:
    """The title-row controls of a report with saved views. `current_view` is the view object (the template reads its
    pk for the «Засах» address), None when the address matches no view."""

    plain_url: str  # the «—» option: the report with no saved setup
    options: list[SavedOption]  # the saved views this viewer may see
    templates: list[SavedOption]  # the starter templates («Загвар») this viewer may use
    current_view: SavedView | None
    template_current: bool  # a template matches the address (it wins the selection when no view matches)
    can_edit_view: bool  # the current view may be renamed or deleted by this viewer


@dataclass(frozen=True)
class PageTools:
    """The tool ribbon's flags and addresses. The rights are already decided: an address the viewer may not use is «»
    (or an empty dict of URLs for the selection bar)."""

    columns: bool  # the «Багана» pop-up (the report picks its columns)
    rules: bool  # the «Шүүлтүүр» pop-up (the report has a count line)
    format: bool  # the «Хэлбэр» pop-up: a count line and not a chart or pivot
    print_url: str
    excel_url: str  # "" without the export right
    selectable: bool  # the «Сонгох» toggle: a table of a report that names its people
    selection_urls: dict[str, str]  # the selection bar's actions; "" for one the viewer may not use
    staff_actions: bool  # the hire and import buttons beside the title (the staff list, for managers)


@dataclass(frozen=True)
class PageHead:
    redirect: str  # the default view's address for a bare GET; "" when there is nothing to follow
    saved: SavedHead | None  # None when the report keeps no saved views
    tools: PageTools
    title: str
    layout_options: list[LayoutOption]  # the switcher; the template draws it with two or more
    selection_max: int  # the most people one bulk action covers: the live selection.MAX_PEOPLE, for every report


def _may_change(user: User, view: SavedView) -> bool:
    """A saved view is renamed and deleted by its author, or by a user with reports.manage_saved_views."""
    return view.author_id == user.pk or user.has_perm("reports.manage_saved_views")


def _sees_private(user: User, view: SavedView) -> bool:
    """A private view is seen by its author; one whose author was deleted (no author) only by a manager."""
    return view.author_id == user.pk or (view.author_id is None and user.has_perm(MANAGE_PERM))


def _visible_views(user: User, report_key: str) -> QuerySet[SavedView]:
    """The report's saved views this user sees: every shared one, the user's own private ones, and the private ones
    with no author left when the user may manage saved views."""
    visible = Q(visibility=SHARED) | Q(author=user)
    if user.has_perm(MANAGE_PERM):
        visible |= Q(author__isnull=True, visibility=PRIVATE)
    return SavedView.objects.filter(report=report_key).filter(visible)


def _view_url(report_url: str, query: str) -> str:
    return f"{report_url}?{query}" if query else f"{report_url}?{PLAIN_VIEW}"


def _option_name(view: SavedView) -> str:
    """The select's text: a star on the default view, and a suffix on a private one."""
    name = f"★ {view.name}" if view.is_default else view.name
    return f"{name} (хувийн)" if view.visibility == PRIVATE else name


def _known_keys(text: str, known: set[str], *, sort: bool) -> str:
    """A comma-separated list of keys with only the known ones kept, in order. A sort key may start with «-»; a group
    key may not, so a «-» part is dropped from a group list (parse_filters would drop the whole list anyway)."""
    parts = text.split(",") if sort else [p for p in text.split(",") if not p.startswith("-")]
    return ",".join(part for part in parts if part.lstrip("-") in known)


def _known_only(report: Report, f: Filters) -> Filters:
    """The address with only the column, group and sort keys this report has, so a saved view stores nothing unknown.
    Rules, totals and marks keep only the report's own columns too."""
    known = {c.key for c in report.columns}
    kept_rules = rules_mod.dump_rules(rules_mod.restrict(rules_mod.parse_rules(f.rules), known))
    kept_totals = totals_mod.dump_totals([pair for pair in totals_mod.parse_totals(f.totals) if pair[0] in known])
    kept_marks = marks_mod.dump_marks([mark for mark in marks_mod.parse_marks(f.marks) if mark.column in known])
    return replace(
        f,
        columns=tuple(k for k in f.columns if k in known),
        group=_known_keys(f.group, known, sort=False),
        sort=_known_keys(f.sort, known, sort=True),
        rules=kept_rules,
        totals=kept_totals,
        marks=kept_marks,
    )


def _cleaned_for(user: User, report: Report, f: Filters) -> Filters:
    """An address as this user may use it: the filters they may not use (column filters on hidden columns included)
    are reset, the columns, sort and group keys they may not see are dropped, and rules, totals and marks keep only
    their columns. Used for what a user saves and for each saved view a user sees."""
    usable = usable_filters(report, user, f)
    known = _known_only(report, usable)
    allowed = {c.key for c in allowed_columns(report, user)}
    visible = replace(
        known,
        columns=tuple(k for k in known.columns if k in allowed),
        group=_known_keys(known.group, allowed, sort=False),
        sort=_known_keys(known.sort, allowed, sort=True),
    )
    return restricted_filters(report, user, visible)


def _viewer_query(user: User, report: Report, stored: str) -> str:
    """A saved view's query as this viewer may see it. A view whose rules all vanish for this viewer is the plain
    address."""
    return to_query(_cleaned_for(user, report, parse_filters(QueryDict(stored))))


def _template_allowed(user: User, report: Report, template: Template) -> bool:
    """A template is offered when its rules parse and use only columns this user may see."""
    f = parse_filters(QueryDict(resolved_query(template)))
    tree = rules_mod.parse_rules(f.rules)
    if tree is None and f.rules:
        return False  # rules that do not parse
    used = set(rules_mod.rule_columns(tree)) if tree is not None else set()
    used |= {k for k in (*f.columns, f.lby, f.lby2) if k}  # the columns and the layout's categories it names
    return used <= {c.key for c in allowed_columns(report, user)}


def saved_head(user: User, report: Report, query: str) -> SavedHead:
    """The saved views of the report for this viewer: the options they may see, the starter templates they may use, the
    one the cleaned address `query` matches, and whether they may change it. Each view's address and the match use the
    query as this viewer may see it."""
    report_url = reverse("reports:report", args=[report.key])
    shown = [(v, _viewer_query(user, report, v.query)) for v in _visible_views(user, report.key)]
    current = next((v for v, own in shown if own == query), None)
    options = [
        SavedOption(name=_option_name(v), url=_view_url(report_url, own), selected=v is current) for v, own in shown
    ]
    # the starter templates («Загвар»): read-only, offered only when every column their rules use is one this viewer
    # may see; a saved view that matches the address wins the selection over a template
    template_options = []
    for t in report.templates:
        if not _template_allowed(user, report, t):
            continue
        own = _viewer_query(user, report, resolved_query(t))
        if own:
            template_options.append(
                SavedOption(name=t.name, url=_view_url(report_url, own), selected=current is None and own == query)
            )
    return SavedHead(
        plain_url=_view_url(report_url, ""),
        options=options,
        templates=template_options,
        current_view=current,
        template_current=any(o.selected for o in template_options),
        can_edit_view=current is not None and _may_change(user, current),
    )


def default_view_redirect(request_get: QueryDict, is_htmx: bool, method: str, user: User, report: Report) -> str:
    """The address of the report's default saved view when the request is a bare GET (no query, no htmx request) of a
    report with saved views and this viewer sees a default whose query is not empty; else "". The target has a query,
    so following it never loops. The caller answers the redirect (the Django view issues an HTTP redirect; the API
    answers `redirect`)."""
    if method != "GET" or request_get or is_htmx or not report.saved_views:
        return ""
    default = _visible_views(user, report.key).filter(is_default=True).first()
    cleaned = _viewer_query(user, report, default.query) if default is not None else ""
    return _view_url(reverse("reports:report", args=[report.key]), cleaned) if cleaned else ""


def _selection_urls(user: User, report: Report) -> dict[str, str]:
    """The selection bar's action URLs. An action the user may not use has an empty URL, and the bar leaves it out:
    Excel and CSV need the export permission, the checklist needs the right to start one."""

    def url(name: str, allowed: bool) -> str:
        return reverse(f"reports:sel_{name}", args=[report.key]) if allowed else ""

    can_export = user.has_perm(EXPORT_PERM)
    return {
        "excel": url("excel", can_export),
        "csv": url("csv", can_export),
        "print": url("print", True),
        "copy": url("copy", True),
        "checklist": url("checklist", checklist_access.can_start(user)),
    }


def layout_options(
    path: str, user: User, report: Report, f: Filters, layout: str, adds: list[str], plain: bool
) -> list[LayoutOption]:
    """The switcher's segments: one per layout the report offers to this user. Another layout starts from its own
    defaults; the filters, sort, rules and format stay. `layout` is the layout on screen."""
    names = offered_layouts(report, user)

    def url(name: str) -> str:
        cleared = replace(
            f,
            layout="" if name == "table" else name,
            lby="",
            lby2="",
            lval="",
            lchart="",
            lmonth="",
            **NEW_LAYOUT_BLANKS,
        )
        return address(path, cleared, adds, plain=plain)

    return [LayoutOption(n, LAYOUT_LABELS[n], url(n), n == layout) for n in names]


def page_tools(user: User, report: Report, table: Table) -> PageTools:
    """The tool ribbon's flags and addresses: cheap (no saved-view query), so the batch answers can use them too."""
    f = table.filters
    selectable = report.person is not None and table.spec.layout == "table"
    return PageTools(
        columns=report.picks_columns,
        rules=report.shows_count,
        format=report.shows_count and table.spec.layout not in ("chart", "pivot"),
        print_url=address(reverse("reports:print", args=[report.key]), f),
        excel_url=address(reverse("reports:excel", args=[report.key]), f) if user.has_perm(EXPORT_PERM) else "",
        selectable=selectable,
        selection_urls=_selection_urls(user, report) if selectable else dict.fromkeys(SELECTION_KEYS, ""),
        staff_actions=report.key == "staff-list" and access.can_manage(user),
    )


def page_head(
    request_get: QueryDict,
    is_htmx: bool,
    path: str,
    user: User,
    report: Report,
    table: Table,
    plain: bool,
    method: str = "GET",
) -> PageHead:
    """The head of the report page for this address and viewer. `table` is the built table (its `filters` are the
    cleaned filters); `plain` is True for a report with saved views (an empty address reads view=plain). `method` is the
    request's method, so the redirect follows a bare GET only (the API passes GET). Costs saved-view queries: the Django
    page calls it only for a full page, not for a batch answer."""
    f = table.filters
    adds = added_names(request_get, offered_adds(report, user, offered_filters(report, user)))
    saved = None
    if report.saved_views:
        # the match uses the address as this viewer may use it, cleaned the same way a stored view is (defaults such as
        # the default columns are not part of it, so an empty view matches the plain address)
        query = to_query(_cleaned_for(user, report, parse_filters(request_get)))
        saved = saved_head(user, report, query)
    return PageHead(
        redirect=default_view_redirect(request_get, is_htmx, method, user, report),
        saved=saved,
        tools=page_tools(user, report, table),
        title=report.title,
        layout_options=layout_options(path, user, report, f, table.spec.layout, adds, plain),
        selection_max=selection_mod.MAX_PEOPLE,
    )

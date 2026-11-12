"""Help entries for the saved report views: the report setups (filters, columns, sort) that users saved by name.

Unlike the other areas these are not fixed in code. A view is made, renamed and deleted by users, so its entries are
built for each question, for the user who asks: one entry per view that user may open (`entries_for`). They are not in
`ENTRIES` or `ENTRY_BY_KEY`; `allowed_entries` adds them. The key is `report.view.<pk>`.

A view is offered under the same rules as the report page: the user must be allowed to open its report, and sees every
shared view, their own private views, and (with reports.manage_saved_views) the private views whose author is gone.
"""

from datetime import date

from accounts.models import User
from django.db.models import Q
from reports import registry
from reports.models import SavedView
from reports.types import Report

from assistant.entry import HelpEntry

KEY_PREFIX = "report.view."
MAX_VIEWS = 100  # the most recently changed views; a long list would only crowd the other entries out of the prompt
PLAIN_VIEW = "view=plain"  # the report address of a view saved with no query (reports.views.PLAIN_VIEW)


def entries_for(user: User, day: date) -> list[HelpEntry]:
    """The saved-view entries `user` may be shown. Empty for a user who may not open reports."""
    if not user.has_perm("reports.view_reports"):
        return []
    visible = Q(visibility="shared") | Q(author=user)
    if user.has_perm("reports.manage_saved_views"):
        visible |= Q(author__isnull=True, visibility="private")
    out: list[HelpEntry] = []
    for view in SavedView.objects.filter(visible).order_by("-updated_at", "-pk")[:MAX_VIEWS]:
        report = registry.REPORTS.get(view.report)
        if report is not None and registry.can_open(user, report):
            out.append(_entry(view, report))
    return out


def _entry(view: SavedView, report: Report) -> HelpEntry:
    def need(user: User, day: date) -> bool:
        return registry.can_open(user, report)

    report_title = report.title
    private = view.visibility == "private"
    return HelpEntry(
        key=f"{KEY_PREFIX}{view.pk}",
        title=f"«{view.name}» тайлан (хадгалсан харагдац, {report_title})",
        steps=(
            f"«Тайлан» цэснээс «{report_title}» тайланг нээнэ.",
            f"Тайлангийн дээд талын харагдацын жагсаалтаас «{view.name}»-г сонгоно. "
            "Хадгалсан шүүлтүүр, багана, эрэмбэ тэр чигээрээ гарна.",
        ),
        url_name="reports:report",
        modal=False,
        need=need,
        labels=("Тайлан", report_title, view.name),
        # People call a saved view a report or a template, with or without its name: all of these must find it, and
        # not the general report list (which also says «тайлан»).
        words=(view.name, f"{view.name} тайлан", f"{view.name} харагдац", f"{view.name} загвар"),
        examples=(f"{view.name} тайлан", f"{view.name} тайланг хаанаас нээх вэ"),
        note=(
            f"«{view.name}» нь «{report_title}» тайлангийн хадгалсан харагдац (загвар) юм."
            + (" Энэ нь зөвхөн таны хувийн харагдац." if private else "")
        ),
        url_args=(view.report,),
        url_query=view.query or PLAIN_VIEW,
    )

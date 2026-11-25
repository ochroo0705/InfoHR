"""The sections of the «Тайлан» catalogue page: the cards each user sees, in the group order of the catalogue.

Request-free: the Django catalogue view and GET /api/v1/reports/catalogue both call `sections_for`, so the rules
(a built report the user may not open is not listed, an unbuilt one is listed greyed, a group with no visible card
is left out) live in one place. The card's search text is built here too, as the template's data-search reads it.
"""

from dataclasses import dataclass

from accounts.models import User
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse

from reports import registry
from reports.catalogue import CATALOGUE, GROUPS, Entry


@dataclass(frozen=True)
class Row:
    entry: Entry
    link: bool  # the report is built and the user may open it; otherwise greyed «удахгүй»
    empty: bool  # the built report's main table has no rows yet («бүртгэл алга»)


@dataclass(frozen=True)
class Section:
    title: str
    rows: list[Row]


def _row(user: User | AnonymousUser, entry: Entry) -> Row | None:
    report = registry.get(entry.key)
    if report is None:
        return Row(entry=entry, link=False, empty=False)
    if not registry.can_open(user, report):
        return None  # a built report the user may not open is not listed
    empty = report.source is not None and not report.source._default_manager.exists()
    return Row(entry=entry, link=True, empty=empty)


def sections_for(user: User | AnonymousUser) -> list[Section]:
    sections: list[Section] = []
    for code, title in GROUPS:
        rows: list[Row] = []
        for entry in CATALOGUE:
            if entry.group != code:
                continue
            row = _row(user, entry)
            if row is not None:
                rows.append(row)
        if rows:
            sections.append(Section(title=title, rows=rows))
    return sections


def search_text(entry: Entry) -> str:
    """The card's data-search text: title, old form and description, then each alias, space-joined as the template
    writes them (an empty old form leaves a double space, as the template does)."""
    text = f"{entry.title} {entry.old_form} {entry.description}"
    return text + "".join(f" {alias}" for alias in entry.aliases)


def card_path(row: Row) -> str:
    """The address of a card that links to its report, "" for a greyed card."""
    return reverse("reports:report", args=[row.entry.key]) if row.link else ""

"""The cross-employee log (spec §5.1): one query layer for every log screen.

Visibility is the employee drawer's rule (`employees.access.visible_activity`), written once as SQL here for all
employees at a time. `test_employee_query.test_parity_with_drawer` keeps the two in step.

URL names read by `parse_filter`: q, emp, employee, by, kind (repeatable), area, field, from, to (YYYY-MM-DD),
system=1 (only entries made by the system), oldest=1 (oldest first). Every value that does not parse is dropped.
"""

import dataclasses
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.db import connections
from django.db.models import ExpressionWrapper, F, Q, QuerySet, TextField
from django.http import QueryDict
from employees import access
from employees.models import ActivityEntry, ActivityKind
from employees.scope import restriction
from macs.dialect import search_match

from logs.foldtext import fold
from logs.params import clean_text, parse_date, parse_id, words

AREAS = ("salary", "personal", "orders", "notes")
KINDS_LIMIT = 10  # kind filters kept from the URL
PAGE_MAX_OFFSET = 2**31 - 1  # offsets are clamped to this (a 32-bit row number; a huge one must not reach SQL)
PAGE_MAX_SIZE = 500


def with_field(entries: QuerySet[Any], label: str) -> QuerySet[Any]:
    """The entries whose changes include a field with exactly this label.

    PostgreSQL: a JSON containment test. Firebird: the text `"field": "<label>"` as Django writes it (json.dumps),
    so a label cannot match inside another label or inside a value. That comparison is case-sensitive, like the JSON
    test."""
    if connections[entries.db].vendor == "firebird":
        fragment = json.dumps({"field": label})[1:-1]
        stored_text = ExpressionWrapper(F("changes"), output_field=TextField())  # the stored JSON text, read as text
        return entries.alias(change_json=stored_text).filter(change_json__contains=fragment)
    return entries.filter(changes__contains=[{"field": label}])


TEXT_LIMIT = 500  # characters kept from a free-text field before the word split
FIELD_LIMIT = 200  # a field label is short; longer text is dropped


@dataclass
class EmployeeLogFilter:
    q: str = ""  # every word must match the message or the changed values
    emp: str = ""  # every word must match family name, given name or code
    employee: int | None = None
    by: str = ""  # every word must match the actor's username or first/last name
    kinds: list[str] = dataclasses.field(default_factory=list)
    area: str = ""  # "" | salary | personal | orders | notes
    field: str = ""  # exact field label, as written in the changes
    date_from: date | None = None
    date_to: date | None = None
    system_only: bool = False
    oldest_first: bool = False


def parse_filter(params: QueryDict) -> EmployeeLogFilter:
    raw_kinds = params.getlist("kind")[:KINDS_LIMIT]
    kinds = [kind for kind in dict.fromkeys(raw_kinds) if kind in ActivityKind.values]
    area = params.get("area", "")
    field_label = clean_text(params.get("field", ""), FIELD_LIMIT + 1)
    if len(field_label) > FIELD_LIMIT:
        field_label = ""
    return EmployeeLogFilter(
        q=clean_text(params.get("q", ""), TEXT_LIMIT),
        emp=clean_text(params.get("emp", ""), TEXT_LIMIT),
        employee=parse_id(params.get("employee", "")),
        by=clean_text(params.get("by", ""), TEXT_LIMIT),
        kinds=kinds,
        area=area if area in AREAS else "",
        field=field_label,
        date_from=parse_date(params.get("from", "")),
        date_to=parse_date(params.get("to", "")),
        system_only=params.get("system") == "1",
        oldest_first=params.get("oldest") == "1",
    )


def visible_entries(user: User) -> QuerySet[ActivityEntry]:
    """Every entry of every employee this user may see, with the drawer's salary, personal and notes rules."""
    if not user.is_active:
        return ActivityEntry.objects.none()
    # sees every employee only when not limited by the data scope (a limited HR user also holds view_employees)
    if user.has_perm("macs.view_employees") and restriction(user) is None:
        entries = ActivityEntry.objects.all()
    else:
        entries = ActivityEntry.objects.filter(employee__in=access.visible_employees(user))
    if not access.can_view_salary(user):
        entries = entries.filter(sensitive=False)
    if not user.has_perm("macs.view_personal"):  # the personal tab is open for one's own record too
        entries = entries.filter(Q(personal=False) | Q(employee__ext__user_id=user.pk))
    if not user.has_perm("macs.view_employees"):  # own records only: no internal notes
        entries = entries.exclude(kind=ActivityKind.NOTE)
    return entries


def filtered(user: User, f: EmployeeLogFilter) -> QuerySet[ActivityEntry]:
    """The visible entries narrowed by every filter, all in SQL, newest first unless `oldest_first`."""
    entries = visible_entries(user)
    if f.employee is not None:
        entries = entries.filter(employee_id=f.employee)
    for word in words(f.emp):
        entries = entries.filter(
            search_match(word, "employee__family_name", "employee__given_name", "employee__code", icase=True)
        )
    for word in words(f.q):  # the message is matched as typed; the changed values through their folded copy
        entries = entries.filter(Q(message__icontains=word) | Q(change_text__contains=fold(word)))
    for word in words(f.by):
        entries = entries.filter(search_match(word, "by__username", "by__first_name", "by__last_name", icase=True))
    if f.kinds:
        entries = entries.filter(kind__in=f.kinds)
    if f.area == "salary":
        entries = entries.filter(sensitive=True)
    elif f.area == "personal":
        entries = entries.filter(personal=True)
    elif f.area == "orders":
        entries = entries.filter(order__isnull=False)
    elif f.area == "notes":
        entries = entries.filter(kind=ActivityKind.NOTE)
    if f.field:
        entries = with_field(entries, f.field)
    if f.date_from is not None:
        entries = entries.filter(at__date__gte=f.date_from)
    if f.date_to is not None:
        entries = entries.filter(at__date__lte=f.date_to)
    if f.system_only:
        entries = entries.filter(by__isnull=True)
    order = ("at", "id") if f.oldest_first else ("-at", "-id")
    return entries.select_related("employee", "by").order_by(*order)


def page(user: User, f: EmployeeLogFilter, offset: int, size: int) -> tuple[list[ActivityEntry], bool]:
    """One batch for `batching.paged`: `size` rows from `offset`, and whether more rows follow."""
    start = min(max(offset, 0), PAGE_MAX_OFFSET)
    count = min(max(size, 1), PAGE_MAX_SIZE)
    rows = list(filtered(user, f)[start : start + count + 1])  # one extra row tells whether another batch exists
    return rows[:count], len(rows) > count

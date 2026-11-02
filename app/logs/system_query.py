"""The system log (audit trail) query layer for the system-log page (/logs/system/, Admin only).

Every filter runs in SQL. The rows keep the actor's username in `actor_name`, so an entry still says who did it
after that user is deleted. The `q` search matches the message and the VALUES of the changes (never JSON key names),
using the same `ChangeValues` expression as the employee log.

URL names read by `parse_system_filter`: q, category (repeatable), action, by, target, ip, from, to (YYYY-MM-DD),
oldest=1 (oldest first). Every value that does not parse is dropped.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import date

from accounts.audit import ACTIONS, Category
from accounts.models import SystemLogEntry
from django.db.models import F, Q, QuerySet, TextField
from django.http import QueryDict

from logs.employee_query import PAGE_MAX_OFFSET, PAGE_MAX_SIZE, ChangeValues
from logs.params import clean_text, parse_date, words

CATEGORIES_LIMIT = 10  # category filters kept from the URL (there are four categories)
TEXT_LIMIT = 500  # characters kept from a free-text field before the word split
IP_LIMIT = 45  # the longest textual IPv6 address
_IP_PREFIX = re.compile(r"[0-9a-fA-F.:]+")  # what an IP prefix may contain; anything else is dropped


@dataclass
class SystemLogFilter:
    q: str = ""  # every word must match the message or the changed values
    categories: list[str] = field(default_factory=list)
    action: str = ""  # an action code from accounts.audit.ACTIONS
    by: str = ""  # every word must match the actor's name as stored, or the actor's username or first/last name
    target: str = ""  # every word must match the target's label or type
    ip: str = ""  # an IP prefix (an exact address is a prefix too)
    date_from: date | None = None
    date_to: date | None = None
    oldest_first: bool = False


def _clean_ip(value: object) -> str:
    """An IP prefix made of hex digits, dots and colons only; anything else (NUL bytes, letters that are no hex
    digit, a long value) is dropped, so the address never reaches the database in a form it cannot compare."""
    text = clean_text(value, IP_LIMIT + 1)
    if len(text) > IP_LIMIT or not _IP_PREFIX.fullmatch(text):
        return ""
    return text


def parse_system_filter(params: QueryDict) -> SystemLogFilter:
    raw_categories = params.getlist("category")[:CATEGORIES_LIMIT]
    categories = [value for value in dict.fromkeys(raw_categories) if value in Category.values]
    action = params.get("action", "")
    return SystemLogFilter(
        q=clean_text(params.get("q", ""), TEXT_LIMIT),
        categories=categories,
        action=action if action in ACTIONS else "",
        by=clean_text(params.get("by", ""), TEXT_LIMIT),
        target=clean_text(params.get("target", ""), TEXT_LIMIT),
        ip=_clean_ip(params.get("ip", "")),
        date_from=parse_date(params.get("from", "")),
        date_to=parse_date(params.get("to", "")),
        oldest_first=params.get("oldest") == "1",
    )


def filtered(f: SystemLogFilter) -> QuerySet[SystemLogEntry]:
    """The system log narrowed by every filter, all in SQL, newest first unless `oldest_first`."""
    entries = SystemLogEntry.objects.all()
    if f.categories:
        entries = entries.filter(category__in=f.categories)
    if f.action:
        entries = entries.filter(action=f.action)
    search = words(f.q)
    if search:
        entries = entries.annotate(change_values=ChangeValues(F("changes"), output_field=TextField()))
    for word in search:
        entries = entries.filter(Q(message__icontains=word) | Q(change_values__icontains=word))
    for word in words(f.by):
        entries = entries.filter(
            Q(actor_name__icontains=word)
            | Q(actor__username__icontains=word)
            | Q(actor__first_name__icontains=word)
            | Q(actor__last_name__icontains=word)
        )
    for word in words(f.target):
        entries = entries.filter(Q(target_label__icontains=word) | Q(target_type__icontains=word))
    if f.ip:
        try:
            entries = entries.filter(ip=str(ipaddress.ip_address(f.ip)))  # a full address: exact match only
        except ValueError:
            entries = entries.filter(ip__startswith=f.ip)  # a prefix: Django compares the host part as text
    if f.date_from is not None:
        entries = entries.filter(at__date__gte=f.date_from)  # the local day (TIME_ZONE = Asia/Ulaanbaatar)
    if f.date_to is not None:
        entries = entries.filter(at__date__lte=f.date_to)
    order = ("at", "id") if f.oldest_first else ("-at", "-id")
    return entries.select_related("actor").order_by(*order)


def system_page(f: SystemLogFilter, offset: int, size: int) -> tuple[list[SystemLogEntry], bool]:
    """One batch for `batching.paged`: `size` rows from `offset`, and whether more rows follow."""
    start = min(max(offset, 0), PAGE_MAX_OFFSET)
    count = min(max(size, 1), PAGE_MAX_SIZE)
    rows = list(filtered(f)[start : start + count + 1])  # one extra row tells whether another batch exists
    return rows[:count], len(rows) > count

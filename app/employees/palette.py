"""Matching rules for the Ctrl+K command palette: which screens and which people a typed query finds.

Every word the user types must match (AND), case-insensitively, and ө is read as о and ү as у (`_fold`), so a name
typed without those letters still matches. Only people the employee list shows are searched, and only the rights
the user already has decide what they may see. Quick actions (create forms, print, password change) are matched by
`actions()`, a separate group. Within each group, matches whose title or name starts with the first typed word
come first.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from accounts.models import User
from django.db.models import Case, CharField, F, Func, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse
from django.utils import timezone
from logs.foldtext import fold
from macs.dialect import is_firebird, search_match, search_prefix
from macs.models import Department, Position

from employees import access
from employees.listing import Row, employee_rows
from employees.models import Employee, EventType, HrOrder, JobRecord
from employees.services.orders import _key as order_key

_fold = fold  # the palette's rule, also read by the assistant (defined in logs.foldtext)

PEOPLE_LIMIT = 8  # at most this many people in one palette answer
PEOPLE_MORE_LIMIT = 50  # at most this many people after «show all» (the user types more to narrow it)
ORDER_LIMIT = 5  # at most this many orders (Тушаал) in one palette answer, the newest first
NUMBER_SIGN = "№"  # a typed order number may start with this sign (`№12`, `№ 12`)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # a typed date, YYYY-MM-DD (checked by date.fromisoformat)
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")  # a typed month, YYYY-MM
REPORT_LIMIT = 8  # at most this many individual reports in one palette answer (only after a word is typed)
LIST_LIMIT = 8  # at most this many lists (Жагсаалтууд) in one palette answer (only after a word is typed)
QUERY_LIMIT = 100  # characters of the typed query that are read at all
_CODE_LENGTH = Employee._meta.get_field("code").max_length or 0  # the longest employee code (the code column's length)
_NUMBER_KEY_LENGTH = HrOrder._meta.get_field("number_key").max_length or 0  # the order number key's column length
RECENT_LIMIT = 5  # at most this many remembered items (Сүүлд нээсэн) in the empty box
RECENT_PARAM_LIMIT = 400  # characters of the browser's recent parameter that are read at all
FROM_LIMIT = 200  # characters of the page path the browser sends (the page the palette opened on) that are read
_REF_SHAPE = re.compile(r"p:[0-9]{1,12}|s:/[!-~]{0,200}")  # what a remembered reference may look like


@dataclass(frozen=True)
class Screen:
    title: str
    url: str
    # The row's icon: "page" or "calendar". Presentation only, so equality ignores it (tests compare titles and URLs).
    kind: str = field(default="page", compare=False)


@dataclass(frozen=True)
class Action:
    title: str
    url: str
    modal: bool  # opens as a pop-up over the current page (htmx), not as a page


@dataclass(frozen=True)
class PersonHit:
    employee: Employee
    left: bool  # the person has left the company
    position: str  # the position and department the list shows for the person ("" when none)
    department: str

    @property
    def initials(self) -> str:
        """Two capitals for the initials circle: the first letter of the family name, then of the given name.
        "" when both are empty (the model allows no name)."""
        return ((self.employee.family_name or "")[:1] + (self.employee.given_name or "")[:1]).upper()


@dataclass(frozen=True)
class OrderHit:
    pk: int
    title: str  # «№ <number> · <employee full name> · <order type>»
    day: str  # the order's date as YYYY-MM-DD ("" when it has none)
    url: str  # the order's pop-up on the employee's record (htmx, like the register's rows)


@dataclass(frozen=True)
class Recent:
    ref: str  # what the browser stores: `p:<pk>` for a person, `s:<path>` for a page
    title: str  # the person's full name, or the screen's title
    url: str
    person: PersonHit | None = None  # set for a person, so the row can show the same lines as the people group
    kind: str = "page"  # the icon of a page row (see Screen.kind)


# Who may see an entry: a permission name, "" (only being signed in), or a test of the user for a rule that is more
# than one permission (the same rule the screen itself or the top bar uses, accounts/nav.py).
type Need = str | Callable[[User], bool]


def _per_user[T](user: User, key: str, work: Callable[[], T]) -> T:
    """`work()` once per user object: one palette answer asks for the fixed screens several times."""
    cache: dict[str, Any] = user.__dict__.setdefault("_palette_cache", {})
    if key not in cache:
        cache[key] = work()
    return cache[key]  # type: ignore[no-any-return]


def _has_own_record(user: User) -> bool:
    """The login is linked to an employee (My page exists for them)."""
    return _per_user(user, "own", lambda: access.own_employee(user) is not None)


def _sees_requests(user: User) -> bool:
    """The top bar's «Хүсэлт» rule (leave_tags.requests_nav): request screens are in use, and the user may view leave
    or has a request waiting for their decision."""
    from leave import access as leave_access  # local import: the leave screens import employees (import cycle)
    from leave.services.approvers import may_decide, requests_active, waiting_for_cached

    if not requests_active(user):
        return False
    day = timezone.localdate()
    return leave_access.can_view(user) or (may_decide(user, day) and bool(waiting_for_cached(user, day)))


def _sees_recruitment(user: User) -> bool:
    """The top bar's «Ажилд авах» rule: the user manages recruitment or is a vacancy's hiring manager."""
    from recruitment.services.visibility import sees_recruitment  # local import: recruitment imports employees

    return _per_user(user, "recruitment", lambda: sees_recruitment(user))


def _manages_recruitment(user: User) -> bool:
    """The vacancy form's rule (recruitment/views.vacancy_add): the user manages recruitment."""
    from recruitment.services.visibility import can_manage  # local import: recruitment imports employees

    return can_manage(user)


def _may_request_leave(user: User) -> bool:
    """The rule of the leave request form (leave/views_requests._requester): own record, the right, approval on."""
    from leave.services.approvers import approval_enabled  # local import: import cycle, as above

    return user.has_perm("leave.request_own_leave") and _has_own_record(user) and approval_enabled(user)


def _is_staff(user: User) -> bool:
    return bool(user.is_staff)


def _allowed(user: User, need: Need) -> bool:
    if callable(need):
        return need(user)
    return not need or user.has_perm(need)


# (title, URL name, who may see it)
_CATALOGUE: tuple[tuple[str, str, Need], ...] = (
    ("Өнөөдөр", "employees:today", "macs.view_employees"),  # as the top bar; HR's home page, so first for them
    ("Миний хуудас", "me", _has_own_record),  # first for staff without the employee right: their home page
    ("Миний даалгавар", "checklists:mine", ""),  # works without an employee record too (checklists/views.mine)
    ("Тушаалын бүртгэл", "employees:orders", "macs.view_employees"),
    ("Чөлөө, амралт", "leave:list", "leave.view_leave"),
    ("Хүсэлт", "leave:requests", _sees_requests),
    ("Багийн хуанли", "leave:calendar", "leave.view_leave"),
    ("Амралтын үлдэгдэл", "leave:balances", "leave.view_leave"),
    ("Ажилд авах", "recruitment:vacancies", _sees_recruitment),
    ("Тайлан", "reports:catalogue", "reports.view_reports"),
    ("Ажилтны бүртгэл", "logs:employee", "macs.view_employees"),
    ("Системийн бүртгэл", "logs:system", "accounts.view_audit"),
    ("Жагсаалтууд", "lists:index", "lists.manage_lists"),
    ("Орон тооны төлөвлөгөө", "employees:slots", "employees.manage_position_slots"),
)

# The icon of a fixed screen where it is not the plain page icon (keyed by URL name).
_SCREEN_KINDS: dict[str, str] = {"leave:calendar": "calendar"}

# Deep pages: found by a typed word only, so the empty box keeps the short menu of fixed screens.
_DEEP: tuple[tuple[str, str, Need], ...] = (
    ("Баярын өдрүүд", "leave:holidays", "leave.manage_leave_settings"),
    ("Амралтын төрөл, тохиргоо", "leave:settings", "leave.manage_leave_settings"),
    ("Утгын холбоо", "lists:meaning", "lists.manage_lists"),
    ("Админ хэсэг", "admin:index", _is_staff),
)

# Quick actions (create forms, or a page to print or to change the password): their own group in the palette.
# Every need in the tuple must hold (see `Need`); an empty tuple means only being signed in.
# The leave form asks for both (leave/access.py can_record); the quick action and a person's action need both.
_LEAVE_PERMS = ("leave.record_leave", "leave.view_leave")

# (title, URL name, permissions needed, opens as a pop-up)
_ACTIONS: tuple[tuple[str, str, tuple[Need, ...], bool], ...] = (
    ("Чөлөө бүртгэх", "leave:add", _LEAVE_PERMS, True),
    ("Чөлөө хүсэх", "leave:request_new", (_may_request_leave,), True),  # staff self-service (D-057)
    ("Ажилтан нэмэх", "employees:add", ("macs.manage_employees",), False),
    ("Ажилтан импортлох", "employees:import", ("macs.manage_employees",), False),  # access.can_manage
    ("Тушаалын бүртгэл хэвлэх", "employees:orders_print", ("macs.view_employees",), False),  # as the register screen
    ("Ажлын байр нээх", "recruitment:vacancy_add", (_manages_recruitment,), True),
    ("Орон тоо нэмэх", "employees:slot_add", ("employees.manage_position_slots",), True),
    ("Нууц үг солих", "password_change", (), False),
)


# Capital Cyrillic letters (Mongolian: А–Я, Ё, Ө, Ү) and the small ө, ү, mapped to what `_fold` makes of them. Used by
# `_sql_fold`: PostgreSQL's lower() folds Cyrillic only when the database's locale knows it, translate() always does.
_FOLD_FROM = "АБВГДЕЁЖЗИЙКЛМНОӨПРСТУҮФХЦЧШЩЪЫЬЭЮЯөү"
_FOLD_TO = "".join(_fold(ch) for ch in _FOLD_FROM)


def _sql_fold(expression: Any) -> Func:
    """`_fold` in SQL: lower() for Latin letters, then translate() for Cyrillic capitals, ө and ү. NULL reads as "",
    so a missing name or job matches no word and `exclude` treats it as plain text too.

    Firebird has no translate(), so there each letter pair is one nested REPLACE(), the same mapping in the same
    order. PostgreSQL keeps the translate() expression unchanged."""
    folded = Lower(Coalesce(expression, Value("")))
    if not is_firebird():
        return Func(
            folded,
            Value(_FOLD_FROM),
            Value(_FOLD_TO),
            function="translate",
            output_field=CharField(),
        )
    out: Any = folded
    for src, dst in zip(_FOLD_FROM, _FOLD_TO, strict=True):
        if src != dst:
            out = Func(out, Value(src), Value(dst), function="REPLACE", output_field=CharField())
    return out


def _ranked[T](words: list[str], found: list[tuple[str, T]]) -> list[T]:
    """The matches with those whose own title starts with the first typed word first; the rest keep their order."""
    if not words:
        return [item for _, item in found]
    ordered = sorted(found, key=lambda pair: not _fold(pair[0]).startswith(words[0]))  # stable: ties keep order
    return [item for _, item in ordered]


def screens(user: User, q: str) -> list[Screen]:
    """The screens the user may open whose title contains every typed word. An empty query lists only the fixed ones.

    With a word typed the order is: fixed screens, deep pages, reports, saved report views, lists; inside each group
    the best matches first.
    """
    if not user.is_active:
        return []
    words = [_fold(w) for w in q.split()]
    found = _matching(user, words, _CATALOGUE)
    if words:
        found = _month_screens(user, q) + found  # a typed date is the most specific answer, so it comes first
        found += _matching(user, words, _DEEP)
        found += _report_screens(user, words)
        found += _saved_view_screens(user, words)
        found += _list_screens(user, words)
    return found


def actions(user: User, q: str) -> list[Action]:
    """The quick actions the user may use whose title contains every typed word. An empty query lists all of them."""
    if not user.is_active:
        return []
    words = [_fold(w) for w in q.split()]
    found: list[tuple[str, Action]] = []
    for title, url_name, perms, modal in _ACTIONS:
        if not all(_allowed(user, need) for need in perms):
            continue
        if all(w in _fold(title) for w in words):
            found.append((title, Action(title, reverse(url_name), modal)))
    return _ranked(words, found)


def _typed_months(q: str) -> list[str]:
    """The months the typed words name: a date YYYY-MM-DD or a month YYYY-MM, as YYYY-MM, each once, in the order
    typed. A word that is not a real date or month, or whose year is outside the calendar's range, names nothing."""
    from leave.views import MAX_YEAR, MIN_YEAR  # local import: the leave screens import employees (import cycle)

    months: list[str] = []
    for word in q[:QUERY_LIMIT].split():
        if _DATE.fullmatch(word):
            try:
                day = date.fromisoformat(word)
            except ValueError:
                continue
            year, month = day.year, day.month
        elif _MONTH.fullmatch(word):
            year, month = int(word[:4]), int(word[5:])
        else:
            continue
        if not (MIN_YEAR <= year <= MAX_YEAR and 1 <= month <= 12):
            continue
        key = f"{year:04d}-{month:02d}"
        if key not in months:
            months.append(key)
    return months


def _month_screens(user: User, q: str) -> list[Screen]:
    """«Багийн хуанли · YYYY-MM» for each month the typed words name, for users who may view leave."""
    if not user.has_perm("leave.view_leave"):
        return []
    base = reverse("leave:calendar")
    return [Screen(f"Багийн хуанли · {month}", f"{base}?month={month}", "calendar") for month in _typed_months(q)]


def _order_keys(q: str) -> list[str]:
    """The number keys of the typed words, a leading «№» dropped. A word that is only the sign names nothing."""
    keys: list[str] = []
    for word in q[:QUERY_LIMIT].split():
        key = order_key(word.removeprefix(NUMBER_SIGN))  # the same key the order was saved with (orders.py)
        if key and key not in keys:
            keys.append(key)
    return keys


def orders(user: User, q: str) -> list[OrderHit]:
    """Orders whose number is one of the typed words (a leading «№» dropped), the newest first, at most ORDER_LIMIT.

    The number must be the whole word (exact match on the saved number key), so `12` finds order 12 and not 120. An
    order number is only unique within a year, so the same number can come back for several years: the newest come
    first. Only for users with the register's right (macs.view_employees), and only orders of people the user may see
    (`access.visible_employees`, the same rule as the register screen). One query, the employee read with it.
    """
    if not user.is_active or not user.has_perm("macs.view_employees"):
        return []
    # A key longer than the number column cannot be a saved number, so it is left out (Firebird refuses such a value).
    keys = [k for k in _order_keys(q) if len(k) <= _NUMBER_KEY_LENGTH]
    if not keys:
        return []
    found = (
        HrOrder.objects.filter(number_key__in=keys, employee__in=access.visible_employees(user))
        .select_related("employee")
        .order_by(F("date").desc(nulls_last=True), "-pk")[:ORDER_LIMIT]
    )
    return [
        OrderHit(
            order.pk,
            f"№ {order.number} · {order.employee.full_name} · {order.get_order_type_display()}",
            order.date.isoformat() if order.date else "",
            reverse("employees:order_detail", args=[order.employee_id, order.pk]),
        )
        for order in found
    ]


def _matching(user: User, words: list[str], entries: tuple[tuple[str, str, Need], ...]) -> list[Screen]:
    """The entries of a (title, URL name, need) table the user may open whose title contains every typed word.
    The title is checked first, so a rule that reads the database runs only for a title that matches."""
    found: list[tuple[str, Screen]] = []
    for title, url_name, need in entries:
        if all(w in _fold(title) for w in words) and _allowed(user, need):
            found.append((title, Screen(title, reverse(url_name), _SCREEN_KINDS.get(url_name, "page"))))
    return _ranked(words, found)


def _list_screens(user: User, words: list[str]) -> list[Screen]:
    """Lists the user may edit whose own label contains every typed word (the «Жагсаалт · » prefix is not searched)."""
    if not user.has_perm("lists.manage_lists"):
        return []
    from lists.registry import LISTS  # local import: employees must not import lists at module level (import cycle)

    found: list[tuple[str, Screen]] = [
        (spec.label, Screen(f"Жагсаалт · {spec.label}", reverse("lists:list", args=[spec.slug])))
        for spec in LISTS.values()
        if all(w in _fold(spec.label) for w in words)
    ]
    return _ranked(words, found)[:LIST_LIMIT]


def _report_screens(user: User, words: list[str]) -> list[Screen]:
    """Reports the user may open whose own title (or former name) contains every typed word (the «Тайлан · » prefix is
    not searched)."""
    from reports import registry  # local import: employees must not import reports at module level (import cycle)
    from reports.catalogue import CATALOGUE

    former = {entry.key: " ".join(entry.aliases) for entry in CATALOGUE}  # old names are found too
    found: list[tuple[str, Screen]] = [
        (report.title, Screen(f"Тайлан · {report.title}", reverse("reports:report", args=[report.key])))
        for report in registry.REPORTS.values()
        if all(w in _fold(f"{report.title} {former.get(report.key, '')}") for w in words)
        and registry.can_open(user, report)
    ]
    return _ranked(words, found)[:REPORT_LIMIT]


def _saved_view_screens(user: User, words: list[str]) -> list[Screen]:
    """Saved report views (a named setup of filters and columns) of the reports the user may open, as
    «Тайлан · <report> · <name>», opening the report with the saved query. Matched on the report's title and the
    view's name together; at most REPORT_LIMIT. One query."""
    from reports import registry  # local import: import cycle, as in `_report_screens`
    from reports.models import SavedView
    from reports.views import PLAIN_VIEW  # an empty query opens this view, not the report's default view

    reports = {key: r for key, r in registry.REPORTS.items() if r.saved_views and registry.can_open(user, r)}
    if not reports:
        return []
    found: list[tuple[str, Screen]] = []
    for view in SavedView.objects.filter(report__in=reports).order_by("report", "name", "pk"):
        report = reports[view.report]
        if not all(w in _fold(f"{report.title} {view.name}") for w in words):
            continue
        base = reverse("reports:report", args=[report.key])
        url = f"{base}?{view.query}" if view.query else f"{base}?{PLAIN_VIEW}"  # as reports.views._view_url
        found.append((view.name, Screen(f"Тайлан · {report.title} · {view.name}", url)))
    return _ranked(words, found)[:REPORT_LIMIT]


def people(user: User, q: str, today: date) -> list[PersonHit]:
    """The first PEOPLE_LIMIT people `find_people` finds."""
    return find_people(user, q, today)[0]


def find_people(user: User, q: str, today: date, limit: int = PEOPLE_LIMIT) -> tuple[list[PersonHit], int]:
    """Employees the user may see whose family name, given name, code, position or department contains every typed
    word (folded, see `_fold`), at most `limit` of them, and how many match in all. Position and department are the
    ones the list shows for the person (the same row).

    The best matches come first: a typed word that is the code exactly, then a family or given name that starts
    with the first typed word, then every word in the name or code, then a match that needs the position or
    department; each rank keeps the order family name, given name, pk.
    A blank query finds nothing. Wildcard characters are matched as plain text (no SQL pattern is built).
    """
    if not user.is_active:
        return [], 0
    words = [_fold(w) for w in q[:QUERY_LIMIT].split()]
    if not words:
        return [], 0
    # Matches by name or code are exact in SQL, so the database counts and ranks them and rows are built only for
    # the ones shown. A match by position or department alone needs the row the list shows (its job), so those few
    # candidates (`_candidates` minus the name matches) are checked here. Both orders: rank, then family name, given
    # name, pk (pk last: ties come out the same every time).
    base = _candidates(access.visible_employees(user), words).filter(ext__isnull=False)  # people HR has touched
    by_name = Q()
    for word in words:
        by_name &= search_match(word, "f_family", "f_given", "f_code")
    # A code equal to a word has the word's length, so a word longer than the code column cannot be one: it is left out
    # of the code test (on Firebird a value longer than the column is refused, not compared).
    codes = [w for w in words if len(w) <= _CODE_LENGTH]
    named = base.filter(by_name).annotate(
        rank=Case(
            When(f_code__in=codes, then=Value(0)),
            When(search_prefix(words[0], "f_family", "f_given"), then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    )
    # The total is a second, cheap count query: a window count (one scan for both) is not portable, Firebird has none.
    named_total = named.count()
    shown = list(named.order_by("rank", "family_name", "given_name", "pk").values_list("pk", flat=True)[:limit])
    rows = employee_rows(
        base.filter(Q(pk__in=shown) | ~by_name).order_by("family_name", "given_name", "pk"),
        today,
    )
    hits = _person_hits(rows)
    on_show = set(shown)
    by_job: list[PersonHit] = []
    for row in rows:
        if row.employee.pk in on_show:
            continue
        hit = hits[row.employee.pk]
        pos, dep = _fold(hit.position), _fold(hit.department)
        fam, giv, cod = (
            _fold(row.employee.family_name or ""),
            _fold(row.employee.given_name or ""),
            _fold(row.employee.code or ""),
        )
        if all(w in fam or w in giv or w in cod or w in pos or w in dep for w in words):
            by_job.append(hit)
    found = [hits[pk] for pk in shown] + by_job
    return found[:limit], named_total + len(by_job)


def _candidates(qs: QuerySet[Employee], words: list[str]) -> QuerySet[Employee]:
    """The employees of `qs` that may match: every folded word is in the name or code, or in the name of the position
    or department of one of their job records or of their MACS row (the job of a person with no HR history).

    A superset of the people `find_people` keeps: the row the list shows uses one of those jobs, and `_sql_fold`
    folds as `_fold` does. `contains` escapes % and _, so wildcards stay plain text. Positions and departments are
    short tables, so each word looks them up once and people are then filtered by id, not by a name per person.
    """
    qs = qs.alias(
        f_family=_sql_fold(F("family_name")),
        f_given=_sql_fold(F("given_name")),
        f_code=_sql_fold(F("code")),
    )
    for word in words:
        positions = (
            Position.objects.alias(f_name=_sql_fold(F("name"))).filter(search_match(word, "f_name")).values("pk")
        )
        departments = (
            Department.objects.alias(f_name=_sql_fold(F("name"))).filter(search_match(word, "f_name")).values("pk")
        )
        jobs = JobRecord.objects.filter(Q(position__in=positions) | Q(department__in=departments))
        qs = qs.filter(
            search_match(word, "f_family", "f_given", "f_code")
            | Q(position__in=positions)
            | Q(department__in=departments)
            | Q(pk__in=jobs.values("employee_id"))
        )
    return qs


def _person_hits(rows: list[Row]) -> dict[int, PersonHit]:
    """One PersonHit per row, keyed by employee pk. Position and department names are read in one query each."""
    jobs = [row.job for row in rows if row.job is not None]
    positions = Position.objects.in_bulk({job.position_id for job in jobs if job.position_id})
    departments = Department.objects.in_bulk({job.department_id for job in jobs if job.department_id})
    hits: dict[int, PersonHit] = {}
    for row in rows:
        job = row.job
        position = (positions[job.position_id].name or "") if job and job.position_id in positions else ""
        department = (departments[job.department_id].name or "") if job and job.department_id in departments else ""
        left = row.state == "left"
        hits[row.employee.pk] = PersonHit(row.employee, left, position, department)
    return hits


def highlight(text: str, words: list[str]) -> list[tuple[str, bool]]:
    """The text cut into consecutive (piece, matched) parts; the letters a typed word matches are True.

    Matching uses `_fold` (ө reads as о, ү as у, case does not matter), so a word typed without those letters still
    marks the name. The positions are the original text's: every character is folded on its own, so each unit of the
    search string is exactly one character. A character whose fold changes length (ß) is never matched, and it cannot
    shift the letters after it. Overlapping and adjacent matches merge into one piece.
    No words or no text marks nothing.
    """
    if not text:
        return []
    units = [_fold(ch) for ch in text]
    haystack = "".join(unit if len(unit) == 1 else ch for unit, ch in zip(units, text, strict=True))
    blocked = [len(unit) != 1 for unit in units]
    marked = [False] * len(text)
    for word in {_fold(w) for w in words if w}:
        start = haystack.find(word)
        while start != -1:
            end = start + len(word)
            if not any(blocked[start:end]):
                for i in range(start, end):
                    marked[i] = True
            start = haystack.find(word, start + 1)  # a later start may overlap this match: found too
    pieces: list[tuple[str, bool]] = []
    for ch, flag in zip(text, marked, strict=True):
        if pieces and pieces[-1][1] == flag:
            pieces[-1] = (pieces[-1][0] + ch, flag)
        else:
            pieces.append((ch, flag))
    return pieces


def fixed_urls(user: User) -> set[str]:
    """The URLs of the fixed screens (the short menu of an empty box): only these pages can be remembered."""
    return {screen.url for screen in screens(user, "")}


def parse_refs(raw: str) -> list[str]:
    """The references the browser sent for the recent group: `p:<pk>` or `s:/path`, comma-separated. Only the shape is
    checked here, malformed and repeated ones are dropped, the order is kept and at most RECENT_LIMIT are read.
    `recent` decides what the user may see."""
    refs: list[str] = []
    for token in raw[:RECENT_PARAM_LIMIT].split(","):
        token = token.strip()
        if not _REF_SHAPE.fullmatch(token) or token in refs:
            continue
        refs.append(token)
        if len(refs) == RECENT_LIMIT:
            break
    return refs


def recent(user: User, refs: list[str], today: date) -> list[Recent]:
    """The remembered items the user may still open, in the order given. A person needs an HR row and must be visible
    to the user (the same filter as `people`); a page must be a fixed screen the user may open. Anything else is
    dropped silently. Rows are read in one query for all people, like `people`."""
    if not user.is_active or not refs:
        return []
    pages = {screen.url: screen for screen in screens(user, "")}
    pks = {int(ref[2:]) for ref in refs if ref.startswith("p:")}
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False, pk__in=pks), today) if pks else []
    hits = _person_hits(rows)
    out: list[Recent] = []
    for ref in refs:
        if ref.startswith("p:"):
            hit = hits.get(int(ref[2:]))
            if hit is not None:
                url = reverse("employees:detail", args=[hit.employee.pk])
                out.append(Recent(ref, hit.employee.full_name, url, hit))
        elif ref[2:] in pages:
            screen = pages[ref[2:]]
            out.append(Recent(ref, screen.title, screen.url, kind=screen.kind))
    return out


def current(user: User, pk: int, today: date) -> PersonHit | None:
    """The person whose record page the palette was opened on, when the user may see them and HR has a row for them
    (the same filter as `people`). None otherwise. One query, like `recent`."""
    if not user.is_active:
        return None
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False, pk=pk), today)
    return _person_hits(rows).get(pk)


def person_actions(user: User, hit: PersonHit) -> list[Action]:
    """What the user may do with one person: offered only when the typed query matched exactly that person (the view
    decides). Nothing for a person who has left. Each action needs the rights of the screen it opens."""
    if not user.is_active or hit.left:
        return []
    found: list[Action] = []
    if all(user.has_perm(perm) for perm in _LEAVE_PERMS):
        found.append(Action("Чөлөө бүртгэх", f"{reverse('leave:add')}?employee={hit.employee.pk}", True))
    if access.can_record_event(user, EventType.CONTRACT):
        url = reverse("employees:event", args=[hit.employee.pk, EventType.CONTRACT.value])
        found.append(Action("Гэрээ сунгах / өөрчлөх", url, True))
    return found

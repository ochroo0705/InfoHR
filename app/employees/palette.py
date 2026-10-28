"""Matching rules for the Ctrl+K command palette: which screens and which people a typed query finds.

Every word the user types must match (AND), case-insensitively, and ө is read as о and ү as у (`_fold`), so a name
typed without those letters still matches. Only people the employee list shows are searched, and only the rights
the user already has decide what they may see. Quick actions (create forms, print, password change) are matched by
`actions()`, a separate group. Within each group, matches whose title or name starts with the first typed word
come first.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from accounts.models import User
from django.db.models import F
from django.urls import reverse
from macs.models import Department, Position

from employees import access
from employees.listing import Row, employee_rows
from employees.models import Employee, EventType, HrOrder
from employees.services.orders import _key as order_key

PEOPLE_LIMIT = 8  # at most this many people in one palette answer
ORDER_LIMIT = 5  # at most this many orders (Тушаал) in one palette answer, the newest first
NUMBER_SIGN = "№"  # a typed order number may start with this sign (`№12`, `№ 12`)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # a typed date, YYYY-MM-DD (checked by date.fromisoformat)
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")  # a typed month, YYYY-MM
REPORT_LIMIT = 8  # at most this many individual reports in one palette answer (only after a word is typed)
LIST_LIMIT = 8  # at most this many lists (Жагсаалтууд) in one palette answer (only after a word is typed)
QUERY_LIMIT = 100  # characters of the typed query that are read at all
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


# (title, URL name, permission needed; "" means none beyond being logged in)
_CATALOGUE: tuple[tuple[str, str, str], ...] = (
    ("Өнөөдөр", "employees:today", ""),
    ("Ажилтнууд", "employees:list", ""),
    ("Тушаалын бүртгэл", "employees:orders", "macs.view_employees"),
    ("Чөлөө, амралт", "leave:list", "leave.view_leave"),
    ("Багийн хуанли", "leave:calendar", "leave.view_leave"),
    ("Амралтын үлдэгдэл", "leave:balances", "leave.view_leave"),
    ("Тайлан", "reports:catalogue", "reports.view_reports"),
    ("Жагсаалтууд", "lists:index", "lists.manage_lists"),
)

# The icon of a fixed screen where it is not the plain page icon (keyed by URL name).
_SCREEN_KINDS: dict[str, str] = {"leave:calendar": "calendar"}

# Deep pages: found by a typed word only, so the empty box keeps the short menu of fixed screens.
_DEEP: tuple[tuple[str, str, str], ...] = (
    ("Баярын өдрүүд", "leave:holidays", "leave.manage_leave_settings"),
    ("Амралтын төрөл, тохиргоо", "leave:settings", "leave.manage_leave_settings"),
)

# Quick actions (create forms, or a page to print or to change the password): their own group in the palette.
# Every permission in the tuple is needed; an empty tuple means only being signed in.
# The leave form asks for both (leave/access.py can_record); the quick action and a person's action need both.
_LEAVE_PERMS = ("leave.record_leave", "leave.view_leave")

# (title, URL name, permissions needed, opens as a pop-up)
_ACTIONS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("Чөлөө бүртгэх", "leave:add", _LEAVE_PERMS, True),
    ("Ажилтан нэмэх", "employees:add", ("macs.manage_employees",), False),
    ("Тушаалын бүртгэл хэвлэх", "employees:orders_print", ("macs.view_employees",), False),  # as the register screen
    ("Нууц үг солих", "password_change", (), False),
)


def _fold(text: str) -> str:
    """Case-folded text with Mongolian ө read as о and ү as у, so the letters match with or without them."""
    return text.casefold().replace("ө", "о").replace("ү", "у")


def _ranked[T](words: list[str], found: list[tuple[str, T]]) -> list[T]:
    """The matches with those whose own title starts with the first typed word first; the rest keep their order."""
    if not words:
        return [item for _, item in found]
    ordered = sorted(found, key=lambda pair: not _fold(pair[0]).startswith(words[0]))  # stable: ties keep order
    return [item for _, item in ordered]


def screens(user: User, q: str) -> list[Screen]:
    """The screens the user may open whose title contains every typed word. An empty query lists only the fixed ones.

    With a word typed the order is: fixed screens, deep pages, reports, lists; inside each group the best matches first.
    """
    if not user.is_active:
        return []
    words = [_fold(w) for w in q.split()]
    found = _matching(user, words, _CATALOGUE)
    if words:
        found = _month_screens(user, q) + found  # a typed date is the most specific answer, so it comes first
        found += _matching(user, words, _DEEP)
        found += _report_screens(user, words)
        found += _list_screens(user, words)
    return found


def actions(user: User, q: str) -> list[Action]:
    """The quick actions the user may use whose title contains every typed word. An empty query lists all of them."""
    if not user.is_active:
        return []
    words = [_fold(w) for w in q.split()]
    found: list[tuple[str, Action]] = []
    for title, url_name, perms, modal in _ACTIONS:
        if not all(user.has_perm(perm) for perm in perms):
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
    keys = _order_keys(q)
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


def _matching(user: User, words: list[str], entries: tuple[tuple[str, str, str], ...]) -> list[Screen]:
    """The entries of a (title, URL name, permission) table the user may open whose title contains every typed word."""
    found: list[tuple[str, Screen]] = []
    for title, url_name, perm in entries:
        if perm and not user.has_perm(perm):
            continue
        if all(w in _fold(title) for w in words):
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
    """Reports the user may open whose own title contains every typed word (the «Тайлан · » prefix is not searched)."""
    from reports import registry  # local import: employees must not import reports at module level (import cycle)

    found: list[tuple[str, Screen]] = [
        (report.title, Screen(f"Тайлан · {report.title}", reverse("reports:report", args=[report.key])))
        for report in registry.REPORTS.values()
        if all(w in _fold(report.title) for w in words) and registry.can_open(user, report)
    ]
    return _ranked(words, found)[:REPORT_LIMIT]


def _person_rank(words: list[str], family: str, given: str, code: str) -> int:
    """0: a typed word is the code exactly; 1: family or given name starts with the first typed word;
    2: every word is in the name or code; 3: some word matches only the position or department."""
    if code and code in words:
        return 0
    if family.startswith(words[0]) or given.startswith(words[0]):
        return 1
    if all(w in family or w in given or w in code for w in words):
        return 2
    return 3


def people(user: User, q: str, today: date) -> list[PersonHit]:
    """Employees the user may see whose family name, given name, code, position or department contains every typed
    word (folded, see `_fold`). Position and department are the ones the list shows for the person (the same row).

    The best matches come first (see `_person_rank`); the rest keep the order family name, given name, pk.
    A blank query finds nothing. Wildcard characters are matched as plain text (no SQL pattern is built).
    """
    if not user.is_active:
        return []
    words = [_fold(w) for w in q[:QUERY_LIMIT].split()]
    if not words:
        return []
    # Folding cannot be done in SQL, so the people HR has touched (as the list shows them) are read as the list reads
    # them, and filtered here. Position and department names are read in one query each, not per person.
    rows = employee_rows(
        access.visible_employees(user)
        .filter(ext__isnull=False)  # only people HR has touched, as the list does
        .order_by("family_name", "given_name", "pk"),  # pk last: ties come out the same every time
        today,
    )
    hits = _person_hits(rows)
    ranked: list[tuple[int, PersonHit]] = []
    for row in rows:
        hit = hits[row.employee.pk]
        fam, giv, cod = (
            _fold(row.employee.family_name or ""),
            _fold(row.employee.given_name or ""),
            _fold(row.employee.code or ""),
        )
        pos, dep = _fold(hit.position), _fold(hit.department)
        if all(w in fam or w in giv or w in cod or w in pos or w in dep for w in words):
            ranked.append((_person_rank(words, fam, giv, cod), hit))
    ranked.sort(key=lambda pair: pair[0])  # stable: equal ranks keep the query order
    return [hit for _, hit in ranked[:PEOPLE_LIMIT]]


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

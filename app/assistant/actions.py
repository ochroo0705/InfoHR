"""The two answers the assistant gives from a plan's `field` and `leave_form` tools.

The model names a field key or a leave type phrase and a few values; code finds the person, checks the asker may see the
field, reads the value and builds the address. The model's text never goes into an address, and the value is read from
the database, never from the model (spec, Safety). Nothing here writes data.
"""

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from accounts.models import User
from django.urls import reverse
from employees import access
from employees.listing import employee_rows
from employees.models import Employee
from employees.palette import PersonHit, _fold, _person_hits
from leave.access import can_record
from leave.forms import active_types
from macs.models import LeaveTypeRow

from assistant.fields import AskableField, field_by_key, field_value, same_word, words
from assistant.people import match_people

MIN_WORD = 3  # a word shorter than this is never a name or a leave type word
MAX_YEARS = 10  # a date this many years away from today is a typing slip, not a leave date
QUESTION_STEM = "хэн"  # «хэн», «хэний», «хэнд» ask who; they name nobody
OWN_WORDS = frozenset(_fold(word) for word in ("миний", "минь", "өөрийн"))  # the question words that mean «my own»


@dataclass(frozen=True)
class FieldAnswer:
    """status: "value" or "empty" (one person, `text` is the value, "" when none is recorded), "pick" (several people,
    no url), "who" (no person named and none of the asker's own), "none" (no answer)."""

    status: str
    people: tuple[PersonHit, ...] = ()
    field_label: str = ""
    text: str = ""
    url: str = ""
    field_key: str = ""  # the registry key the answer is about (a pick's rows build their own addresses from it)


@dataclass(frozen=True)
class LeaveFormAnswer:
    """status: "form" (the leave form opens, with what the sentence filled), "pick" (several people, no url), "none".
    `shared` is the validated type, dates and origin as (name, value) pairs, without any person: a pick's rows add their
    own `employee` to it (see leave_address). Nothing from the question text is in it."""

    status: str
    people: tuple[PersonHit, ...] = ()
    url: str = ""
    filled: tuple[str, ...] = ()
    open_parts: tuple[str, ...] = ()
    shared: tuple[tuple[str, str], ...] = ()


def _asks_own(text: str, own: bool) -> bool:
    """The plan's `own` counts only when the question itself says «my» (a word of OWN_WORDS). The model's flag alone
    never picks the asker's record, so «Болдын утас» with own=True still asks about Болд."""
    return own and not words(text).isdisjoint(OWN_WORDS)


def _people(user: User, text: str, day: date, own: bool) -> tuple[PersonHit, ...]:
    """The asker's own employee when `own`, else the people the question names (already inside the asker's scope)."""
    if own:
        employee = access.own_employee(user)
        if employee is None:
            return ()
        rows = employee_rows(Employee.objects.filter(pk=employee.pk), day)
        return tuple(_person_hits(rows).values())
    return tuple(match_people(user, text, day))


def _names_someone(text: str, field: AskableField) -> bool:
    """True when the question has a word that is neither the field's own words nor a question word. Used only to tell
    «whose field?» (nothing named) from a name that matched nobody; it never looks at the staff list."""
    terms = words(field.label)
    for synonym in field.synonyms:
        terms |= words(synonym)
    for word in words(text):
        if len(word) < MIN_WORD or word.startswith(QUESTION_STEM):
            continue
        if any(same_word(word, term) for term in terms):
            continue
        return True
    return False


def _field_url(pk: int, field: AskableField) -> str:
    return reverse("employees:detail", args=[pk]) + f"#{field.tab}-{field.key}"


def field_address(pk: int, field_key: str) -> str:
    """The employee page at one field's row, or "" for a key outside the registry (the pick rows use it)."""
    field = field_by_key(field_key)
    return "" if field is None else _field_url(pk, field)


def leave_address(pk: int, shared: tuple[tuple[str, str], ...]) -> str:
    """The leave form with one employee added to the sentence's validated type, dates and origin (`shared`, from the
    answer). A pick's row uses it; the same parts go in the single-person address."""
    return reverse("leave:add") + "?" + urlencode([("employee", str(pk)), *shared])


def field_answer(user: User, text: str, day: date, field_key: str, own: bool) -> FieldAnswer:
    """The answer to one field of the person the question names (or of the asker's own record when the question says
    «my»)."""
    field = field_by_key(field_key)
    if field is None:
        return FieldAnswer("none")
    own = _asks_own(text, own)
    people = _people(user, text, day, own)
    if not people:
        if not own and not _names_someone(text, field):
            return FieldAnswer("who")
        return FieldAnswer("none")
    if len(people) > 1:
        # A pick links every person's field, so the asker must be able to read it for each of them; if not for one,
        # the answer is the same no-answer as a single person's field the asker may not read (nobody is dropped).
        if any(field_value(user, hit.employee, field_key, day) is None for hit in people):
            return FieldAnswer("none")
        return FieldAnswer("pick", people=people, field_key=field.key)
    employee = people[0].employee
    value = field_value(user, employee, field_key, day)
    if value is None:
        return FieldAnswer("none")
    status = "value" if value.text else "empty"
    return FieldAnswer(
        status,
        people=people,
        field_label=value.label,
        text=value.text,
        url=_field_url(employee.pk, field),
        field_key=field.key,
    )


def _leave_type(phrase: str) -> LeaveTypeRow | None:
    """The one active leave type the phrase names: all its words equal the type's name, or each of its words is the
    start of, or equal to, a word of the type's name. Two or more matching types give None (left for the person)."""
    if not isinstance(phrase, str):  # a missing value from the plan is an empty phrase
        return None
    asked = {word for word in words(phrase) if len(word) >= MIN_WORD}
    if not asked:
        return None
    types = list(active_types())
    exact = [row for row in types if words(row.name) == words(phrase)]
    if len(exact) == 1:
        return exact[0]
    covering = [row for row in types if all(any(same_word(word, name) for name in words(row.name)) for word in asked)]
    return covering[0] if len(covering) == 1 else None


def _date(text: str, today: date) -> date | None:
    """An ISO date within MAX_YEARS of today, or None (missing, malformed, or a year far away)."""
    try:
        found = date.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return found if abs(found.year - today.year) <= MAX_YEARS else None


def _shared_parts(leave_type: str, start: str, end: str, day: date) -> tuple[dict[str, str], list[str], list[str]]:
    """The validated type, dates and origin of a leave sentence (the parts every person's form shares), with the lines
    the card shows for them and the parts the person still has to fill."""
    params: dict[str, str] = {}
    filled: list[str] = []
    open_parts: list[str] = []
    found_type = _leave_type(leave_type)
    if found_type is None:
        open_parts.append("Төрлийг сонгоно уу")
    else:
        params["type"] = str(found_type.pk)
        filled.append(f"Төрөл: {found_type.name}")

    start_day = _date(start, day)
    end_day = _date(end, day) if start_day is not None else None  # an end without a start is dropped
    if start_day is not None and end_day is not None and end_day < start_day:
        end_day = None  # an end before the start is dropped; the start is kept
    if start_day is None:
        open_parts.append("Эхлэх огноог оруулна уу")
    else:
        params["start"] = start_day.isoformat()
        filled.append(f"Эхлэх: {start_day.isoformat()}")
    if end_day is None:
        open_parts.append("Дуусах огноог оруулна уу")
    else:
        params["end"] = end_day.isoformat()
        filled.append(f"Дуусах: {end_day.isoformat()}")

    params["from"] = "assistant"  # cosmetic: the form shows the «filled from your sentence» line; it grants nothing
    return params, filled, open_parts


def leave_form_answer(
    user: User, text: str, day: date, own: bool, leave_type: str, start: str, end: str
) -> LeaveFormAnswer:
    """The leave form, opened with what the sentence names and what its dates say. Valid parts are filled; the rest
    are left to the person and named in `open_parts`. Nothing is saved here: the form checks every value itself."""
    if not can_record(user):
        return LeaveFormAnswer("none")
    own = _asks_own(text, own)
    people = _people(user, text, day, own)
    if own and not people:
        return LeaveFormAnswer("none")
    shared, filled, open_parts = _shared_parts(leave_type, start, end, day)
    if len(people) > 1:
        return LeaveFormAnswer("pick", people=people, shared=tuple(shared.items()))

    params: dict[str, str] = {}
    if people:
        params["employee"] = str(people[0].employee.pk)
        filled.insert(0, f"Ажилтан: {people[0].employee.full_name}")
    params.update(shared)
    url = reverse("leave:add") + "?" + urlencode(params)
    return LeaveFormAnswer("form", people=people, url=url, filled=tuple(filled), open_parts=tuple(open_parts))

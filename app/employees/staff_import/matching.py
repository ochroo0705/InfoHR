"""Match the column headings of a staff spreadsheet to employee fields, and remember the choice for next time."""

from django.db import transaction

from employees.models import StaffImportSettings

from .fields import BY_KEY, FIELDS, normalize_heading

REQUIRED_KEYS = ("family_name", "given_name", "start", "department", "position")
REGISTER_OR_PASSPORT_LABEL = "Регистр эсвэл паспортын дугаар"


def _field_for_heading(heading: str, remembered: dict[str, str]) -> str | None:
    """The field key a heading points to: the remembered choice first, then an exact alias match."""
    norm = normalize_heading(heading)
    if not norm:
        return None
    key = remembered.get(norm)
    if key in BY_KEY:
        return key
    for field in FIELDS:
        if norm in {normalize_heading(alias) for alias in field.aliases}:
            return field.key
    return None


def auto_match(headings: list[str], *, remembered: dict[str, str], allow_salary: bool) -> dict[str, str]:
    """Return {column index as str: field key}. A field goes to the first column that matches it.
    Salary-gated fields are left out unless `allow_salary` is true."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for index, heading in enumerate(headings):
        key = _field_for_heading(heading, remembered)
        if key is None or key in used:
            continue
        if BY_KEY[key].needs_salary and not allow_salary:
            continue
        mapping[str(index)] = key
        used.add(key)
    return mapping


def ignored_salary_headings(headings: list[str], *, remembered: dict[str, str]) -> list[str]:
    """The headings that would match a salary-gated field, so the screen can say they were ignored."""
    return [
        heading
        for heading in headings
        if (key := _field_for_heading(heading, remembered)) is not None and BY_KEY[key].needs_salary
    ]


@transaction.atomic  # the settings save is audited: a failed log line must roll the saved mapping back
def remember(
    settings: StaffImportSettings,
    headings: list[str],
    mapping: dict[str, str],
    defaults: dict[str, str],
    date_format: str,
) -> None:
    """Store the column choice (by normalised heading), the fixed values and the date format on the settings row.

    Entries with a column index that is not 0..len(headings)-1, an unknown field key or a blank heading are skipped.
    If two columns share a normalised heading, the first column wins. Blank default values are not stored.

    The settings row is shared by every user, so this merges: an entry for a heading that is already remembered is
    replaced, every other remembered entry (for example one an Admin saved for a salary column) is kept.
    """
    valid = [
        (int(index), key)
        for index, key in mapping.items()
        if isinstance(index, str) and index.isdecimal() and int(index) < len(headings) and key in BY_KEY
    ]
    stored: dict[str, str] = {}
    for position, key in sorted(valid):
        norm = normalize_heading(headings[position])
        if norm:
            stored.setdefault(norm, key)
    settings.mapping = {**settings.mapping, **stored}
    new_defaults = {k: v for k, v in defaults.items() if isinstance(v, str) and v.strip()}
    settings.defaults = {**settings.defaults, **new_defaults}
    settings.date_format = date_format
    settings.save()


def _supplied(key: str, mapping: dict[str, str], defaults: dict[str, str]) -> bool:
    if key in mapping.values():
        return True
    value = defaults.get(key)
    return isinstance(value, str) and bool(value.strip())


def missing_required(mapping: dict[str, str], defaults: dict[str, str]) -> list[str]:
    """Labels of the required fields that have neither a column nor a fixed value.

    register_no and passport_no count only when a column is mapped: a fixed value would give every row the same
    identity number.
    """
    missing = [BY_KEY[key].label for key in REQUIRED_KEYS if not _supplied(key, mapping, defaults)]
    if not ({"register_no", "passport_no"} & set(mapping.values())):
        missing.append(REGISTER_OR_PASSPORT_LABEL)
    return missing

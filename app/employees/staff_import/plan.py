"""Preview of a staff Excel import: parses every row, resolves the lookups, finds duplicates and lists what would be
created. It reads the database but never writes to it.

Value contract for `ParsedRow.values` (Task 8 consumes the rows whose status is "new"):
- Plain fields keep the types from rows.py (text, date, Decimal, "M"/"F" gender, ...).
- Lookups are resolved to primary keys, and the text keys they came from are gone:
  - `branch_id`, `citizenship_id`, `bank_id`, `insured_category_id`: the matched list entry.
  - `department_id`, `position_id`: an existing active entry.
  - `department`, `position`: the cleaned text of a name that does not exist yet. The runner creates it, once per
    name (rows that share a name share the first spelling among the rows that end up new), and then uses the new id.
    Such a row has no `*_id` key for that field.
- `work_conditions`: int 1 (Хэвийн), 2 (Хүнд) or 3 (Бусад).
- Salary-gated fields (`base_salary`, `bank_id`, `account_no`, `social_insurance_no`, `health_insurance_no`,
  `taxpayer_no`, `insured_category_id`) are absent when `allow_salary` is false. Their columns are not parsed at all.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from accounts.models import User
from macs.models import Bank, Branch, Country, Department, InsuredCategory, Position

from employees.access import branch_choices, branch_required, default_branch
from employees.models import DepartmentExt, Employee, PositionExt, StaffImportDraft
from employees.staff_import.fields import BY_KEY
from employees.staff_import.reader import read_rows
from employees.staff_import.rows import ParsedRow, parse_row
from employees.validators import normalize_register_no

WORK_CONDITIONS: dict[str, int] = {"хэвийн": 1, "хүнд": 2, "бусад": 3, "1": 1, "2": 2, "3": 3}
WORK_CONDITIONS_HINT = "Хэвийн, Хүнд, Бусад эсвэл 1, 2, 3"
SPACES = re.compile(r"\s+")
DUPLICATE_IN_SYSTEM = "Системд бүртгэлтэй"
OUT_OF_SCOPE = "Салбар таны эрхийн хүрээнд ороогүй байна."
BRANCH_REQUIRED = "Салбар сонгогдоогүй байна."


@dataclass
class Preview:
    rows: list[ParsedRow]
    new: int
    duplicates: int
    errors: int
    new_departments: list[str]
    new_positions: list[str]
    ignored_columns: list[str]


def _key(text: str) -> str:
    """Lower case with whitespace collapsed. Used to compare names; the text itself is not changed."""
    return " ".join(text.lower().split())


def _clean(text: str) -> str:
    """The name as it would be stored: whitespace collapsed, case kept."""
    return " ".join(text.split())


def _is_salary(key: str) -> bool:
    return key in BY_KEY and BY_KEY[key].needs_salary


@dataclass(frozen=True)
class _Catalogue:
    """A list whose entries are found by name first and by code second (Country, InsuredCategory)."""

    names: dict[str, int]
    codes: dict[str, int]

    def find(self, text: str) -> int | None:
        key = _key(text)
        found = self.names.get(key)
        return found if found is not None else self.codes.get(key)


def _catalogue(names: Iterable[tuple[int, str | None]], codes: Iterable[tuple[int, str | None]] = ()) -> _Catalogue:
    name_index: dict[str, int] = {}
    code_index: dict[str, int] = {}
    for pk, name in names:
        if name and name.strip():
            name_index.setdefault(_key(name), pk)
    for pk, code in codes:
        if code and code.strip():
            code_index.setdefault(_key(code), pk)
    return _Catalogue(name_index, code_index)


def _by_name(pairs: Iterable[tuple[int, str | None]]) -> dict[str, list[int]]:
    """Every id per name. A name may exist twice, once active and once not, so all ids are kept."""
    index: dict[str, list[int]] = {}
    for pk, name in pairs:
        if name and name.strip():
            index.setdefault(_key(name), []).append(pk)
    return index


@dataclass(frozen=True)
class _Lookups:
    branches: _Catalogue
    branches_all: _Catalogue
    countries: _Catalogue
    banks: _Catalogue
    insured: _Catalogue
    departments: dict[str, list[int]]
    inactive_departments: frozenset[int]
    positions: dict[str, list[int]]
    inactive_positions: frozenset[int]

    @classmethod
    def load(cls, scope: "_BranchScope | None" = None) -> "_Lookups":
        every = _catalogue(Branch.objects.values_list("id", "name"))
        listed = every
        if scope is not None:  # a branch-limited hirer's names come from their own list first
            listed = _catalogue(Branch.objects.filter(pk__in=scope.allowed).values_list("id", "name"))
        return cls(
            branches=listed,
            branches_all=every,
            countries=_catalogue(Country.objects.values_list("id", "name"), Country.objects.values_list("id", "code")),
            banks=_catalogue(Bank.objects.values_list("id", "name")),
            insured=_catalogue(
                InsuredCategory.objects.values_list("id", "name"),
                InsuredCategory.objects.values_list("id", "code"),
            ),
            departments=_by_name(Department.objects.values_list("id", "name")),
            inactive_departments=frozenset(
                DepartmentExt.objects.filter(active=False).values_list("department_id", flat=True)
            ),
            positions=_by_name(Position.objects.values_list("id", "name")),
            inactive_positions=frozenset(
                PositionExt.objects.filter(active=False).values_list("position_id", flat=True)
            ),
        )


def _resolve_catalogue(row: ParsedRow, text_key: str, id_key: str, catalogue: _Catalogue) -> None:
    text = row.values.pop(text_key, None)
    if text is None:
        return
    pk = catalogue.find(text)
    if pk is None:
        row.errors.append(f"{BY_KEY[text_key].label} олдсонгүй: {text}")
    else:
        row.values[id_key] = pk


def _resolve_work_conditions(row: ParsedRow) -> None:
    text = row.values.pop("work_conditions", None)
    if text is None:
        return
    code = WORK_CONDITIONS.get(_key(str(text)))
    if code is None:
        row.errors.append(f"{BY_KEY['work_conditions'].label} буруу байна ({WORK_CONDITIONS_HINT})")
    else:
        row.values["work_conditions"] = code


def _resolve_named(
    row: ParsedRow,
    key: str,
    ids: dict[str, list[int]],
    inactive: frozenset[int],
    limit: int,
    pending: list[tuple[ParsedRow, str, str, str]],
) -> None:
    """A department or a position. An active match gives `<key>_id`; an inactive match is an error; no match is
    queued in `pending` as a name to create (the caller keeps it only for rows that will be imported)."""
    text = row.values.pop(key, None)
    if text is None:
        return
    label = BY_KEY[key].label
    name = _clean(text)
    if len(name) > limit:
        row.errors.append(f"{label} хэт урт байна (дээд тал {limit} тэмдэгт)")
        return
    matches = ids.get(_key(name), [])
    active = [pk for pk in matches if pk not in inactive]
    if active:
        row.values[f"{key}_id"] = active[0]
    elif matches:
        row.errors.append(f"{label} идэвхгүй байна: {name}")
    else:
        pending.append((row, key, _key(name), name))


@dataclass(frozen=True)
class _BranchScope:
    """What a branch-limited hirer may import: the branches they may pick, and the one a blank branch cell gets."""

    allowed: frozenset[int]
    default: Branch | None


def _branch_scope(user: User | None) -> _BranchScope | None:
    """None when the user is not limited by branch (no user given, or no listed branches): every row is in scope."""
    if user is None or not branch_required(user):
        return None
    return _BranchScope(frozenset(branch_choices(user).values_list("pk", flat=True)), default_branch(user))


def _limit_branch(row: ParsedRow, had_cell: bool, scope: _BranchScope) -> None:
    """A blank branch takes the hirer's default branch, as the hire form pre-selects it. A branch outside the hirer's
    list refuses the row. An unknown branch name is already an error from the lookup, so it is not repeated here."""
    if not had_cell:
        if scope.default is None:
            row.errors.append(BRANCH_REQUIRED)
        else:
            row.values["branch_id"] = scope.default.pk
    elif "branch_id" in row.values and row.values["branch_id"] not in scope.allowed:
        row.errors.append(OUT_OF_SCOPE)


def _resolve_branch(row: ParsedRow, lookups: _Lookups) -> None:
    """A name in the hirer's list gives `branch_id`. A name that exists only outside that list gives the outside id,
    which `_limit_branch` refuses with OUT_OF_SCOPE. A name unknown everywhere is the usual unknown-value error."""
    text = row.values.pop("branch", None)
    if text is None:
        return
    pk = lookups.branches.find(text)
    if pk is None:
        pk = lookups.branches_all.find(text)
    if pk is None:
        row.errors.append(f"{BY_KEY['branch'].label} олдсонгүй: {text}")
    else:
        row.values["branch_id"] = pk


def _resolve_lookups(row: ParsedRow, lookups: _Lookups, pending: list[tuple[ParsedRow, str, str, str]]) -> None:
    _resolve_branch(row, lookups)
    _resolve_catalogue(row, "citizenship", "citizenship_id", lookups.countries)
    _resolve_catalogue(row, "bank", "bank_id", lookups.banks)
    _resolve_catalogue(row, "insured_category", "insured_category_id", lookups.insured)
    _resolve_work_conditions(row)
    _resolve_named(
        row,
        "department",
        lookups.departments,
        lookups.inactive_departments,
        _max_length(Department),
        pending,
    )
    _resolve_named(row, "position", lookups.positions, lookups.inactive_positions, _max_length(Position), pending)


def _max_length(model: type[Department] | type[Position]) -> int:
    return int(model._meta.get_field("name").max_length or 0)


@dataclass
class _Existing:
    """Register numbers and passport numbers already in the system, normalised the way the hire form does."""

    registers: set[str] = field(default_factory=set)
    passports: set[str] = field(default_factory=set)

    @classmethod
    def load(cls) -> "_Existing":
        existing = cls()
        for register, passport in Employee.objects.values_list("register_no", "passport_no"):
            if register:
                existing.registers.add(normalize_register_no(register))
            if passport:
                existing.passports.add(SPACES.sub("", passport).upper())
        return existing


def _mark_duplicate(row: ParsedRow, existing: _Existing, seen: dict[tuple[str, str], int]) -> None:
    """Sets the status of a row that has no errors: a register number is compared with register numbers and a
    passport with passports. The first row of a key in the file is the one that counts."""
    if "register_no" in row.values:
        kind, key, taken = "register", normalize_register_no(row.values["register_no"]), existing.registers
    else:
        kind, key, taken = "passport", SPACES.sub("", str(row.values["passport_no"])).upper(), existing.passports
    if key in taken:
        row.status, row.note = "duplicate", DUPLICATE_IN_SYSTEM
    elif (kind, key) in seen:
        row.status, row.note = "duplicate", f"Файлд давхардсан (мөр {seen[(kind, key)]})"
    else:
        seen[(kind, key)] = row.number


def _ignored_headings(headings: list[str], mapping: dict[str, str]) -> list[str]:
    """The headings of the mapped salary-gated columns, in column order."""
    columns = sorted((int(index), key) for index, key in mapping.items() if index.isdecimal())
    return [headings[position] for position, key in columns if _is_salary(key) and position < len(headings)]


def build_preview(draft: StaffImportDraft, *, allow_salary: bool, user: User | None = None) -> Preview:
    """Parse the draft's file and say what an import would do. Nothing is written. With a branch-limited `user`, a row
    outside the user's branches is an error and a blank branch takes the user's default; `user=None` is unscoped."""
    headings, numbered_rows = read_rows(bytes(draft.data), draft.sheet, draft.header_rows)
    mapping: dict[str, str] = {
        index: key for index, key in draft.mapping.items() if allow_salary or not _is_salary(key)
    }
    defaults: dict[str, str] = {
        key: value for key, value in draft.defaults.items() if allow_salary or not _is_salary(key)
    }
    ignored_columns = [] if allow_salary else _ignored_headings(headings, draft.mapping)

    scope = _branch_scope(user)
    lookups = _Lookups.load(scope)
    existing = _Existing.load()
    rows = [parse_row(number, cells, mapping, defaults, draft.date_format) for number, cells in numbered_rows]
    pending: list[tuple[ParsedRow, str, str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        had_cell = "branch" in row.values  # a blank branch cell leaves no key behind (rows.py)
        _resolve_lookups(row, lookups, pending)
        if scope is not None:
            _limit_branch(row, had_cell, scope)
        if row.errors:
            row.status = "error"
        else:
            _mark_duplicate(row, existing, seen)

    # A name to create is recorded only for a row that will be imported; the first spelling among those rows is kept.
    new_names: dict[str, dict[str, str]] = {"department": {}, "position": {}}
    for row, key, norm, name in pending:
        if row.status != "new":
            continue
        row.values[key] = new_names[key].setdefault(norm, name)

    return Preview(
        rows=rows,
        new=sum(row.status == "new" for row in rows),
        duplicates=sum(row.status == "duplicate" for row in rows),
        errors=sum(row.status == "error" for row in rows),
        new_departments=list(new_names["department"].values()),
        new_positions=list(new_names["position"].values()),
        ignored_columns=ignored_columns,
    )

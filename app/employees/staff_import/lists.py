"""The optional list sheets of a staff workbook: family, education, previous jobs, languages and so on.

Each list sheet is a second sheet of the same file, named like its list on the personal tab. Its first column holds the
register (or passport) number of a person from the main sheet; every other column is one field of the row form the
personal tab uses for that list. A row is checked and written by that same form and by `personal_writes.add`, so an
imported row obeys exactly the rules of a row typed in by hand.

A list row belongs only to a person created by this import. A person who is already in the system (a duplicate), or
whose main row is refused, gets no list rows: running the same file twice never adds a row twice.

Nothing here writes to the database; `run.py` writes. Code lists are matched by name and never added to.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from django import forms
from macs.models import (
    AcademicDegree,
    Branch,
    City,
    ContactType,
    Country,
    Department,
    District,
    EducationLevel,
    FamilyRelation,
    ForeignLanguage,
    Position,
    ProfessionType,
    QualificationType,
    SpecEduType,
    TalentKind,
)

from employees.forms import FORMS
from employees.services.personal_writes import PAY_TYPES, TITLES, TR_TYPES
from employees.staff_import.fields import normalize_heading
from employees.staff_import.reader import NO_DATA, ImportFileError, read_rows, sheet_names
from employees.staff_import.rows import DATE_FORMATS, ParsedRow
from employees.validators import normalize_register_no

LINK_LABEL = "Регистр / паспорт"
LINK_ALIASES = ("регистр", "регистр/паспорт", "регистрийн дугаар", "паспорт", "register no", "register")
NO_PERSON = "Үндсэн хуудсанд ийм дугаартай ажилтан алга"
PERSON_EXISTS = "Ажилтан системд аль хэдийн бүртгэлтэй тул алгасав"
PERSON_REFUSED = "Ажилтны мөр алдаатай тул алгасав"
PERSON_NOT_SAVED = "Ажилтан хадгалагдаагүй тул алгасав"
NO_LINK = "Регистр эсвэл паспортын дугаар дутуу байна"

# lookup name -> model whose `name` is matched. "district" and the two fixed-choice lookups are handled by hand.
MODELS: dict[str, Any] = {
    "family_relation": FamilyRelation,
    "branch": Branch,
    "department": Department,
    "position": Position,
    "country": Country,
    "education": EducationLevel,
    "profession_type": ProfessionType,
    "qualification_type": QualificationType,
    "degree": AcademicDegree,
    "spec_edu_type": SpecEduType,
    "language": ForeignLanguage,
    "talent": TalentKind,
    "city": City,
    "contact_type": ContactType,
}
CHOICES: dict[str, dict[int, str]] = {"tr_type": TR_TYPES, "pay_type": PAY_TYPES}


@dataclass(frozen=True)
class ListSheet:
    """One list sheet: the personal-tab list `kind`, and its columns as (form field, lookup or None).
    The heading of a column is the label of that form field."""

    kind: str
    columns: tuple[tuple[str, str | None], ...]

    @property
    def title(self) -> str:
        return TITLES[self.kind]

    def label(self, name: str) -> str:
        return str(FORMS[self.kind].base_fields[name].label)

    def headings(self) -> list[str]:
        return [LINK_LABEL, *(self.label(name) for name, _ in self.columns)]


SHEETS: tuple[ListSheet, ...] = (
    ListSheet(
        "family",
        (
            ("relation", "family_relation"),
            ("given_name", None),
            ("surname", None),
            ("birth_date", None),
            ("job", None),
            ("phone", None),
        ),
    ),
    ListSheet(
        "relative",
        (
            ("given_name", None),
            ("father_name", None),
            ("description", None),
            ("phone", None),
            ("branch", "branch"),
            ("department", "department"),
            ("position", "position"),
        ),
    ),
    ListSheet(
        "education",
        (
            ("org_name", None),
            ("country", "country"),
            ("start_year", None),
            ("end_year", None),
            ("edu_level", "education"),
            ("profession_type", "profession_type"),
            ("qualification_type", "qualification_type"),
            ("grade", "degree"),
            ("credit_score", None),
            ("diplom_number", None),
        ),
    ),
    ListSheet(
        "before_work",
        (
            ("worked_place", None),
            ("start_text", None),
            ("end_text", None),
            ("profession", None),
            ("shaltgaan", None),
            ("start_year", None),
            ("end_year", None),
        ),
    ),
    ListSheet(
        "certificate",
        (
            ("cert_type", "spec_edu_type"),
            ("org_edu", None),
            ("profession", None),
            ("spec_profession", None),
            ("certify_number", None),
            ("certify_date", None),
            ("end_date", None),
            ("certify_year", None),
        ),
    ),
    ListSheet(
        "training",
        (
            ("tr_type", "tr_type"),
            ("description", None),
            ("start_date", None),
            ("start_year", None),
            ("days", None),
            ("amount", None),
            ("pay_type", "pay_type"),
            ("training_center", None),
        ),
    ),
    ListSheet(
        "language",
        (
            ("language", "language"),
            ("understand_lvl", None),
            ("speaking_lvl", None),
            ("reading_lvl", None),
            ("writing_lvl", None),
            ("description", None),
        ),
    ),
    ListSheet("talent", (("talent", "talent"), ("trained_year", None), ("description", None))),
    ListSheet("award", (("give_org", None), ("award_name", None), ("award_date", None), ("description", None))),
    ListSheet("address", (("city", "city"), ("district", "district"), ("street", None))),
    ListSheet(
        "contact",
        (("contact_type", "contact_type"), ("name", None), ("relative", None), ("value", None)),
    ),
)
BY_KIND: dict[str, ListSheet] = {sheet.kind: sheet for sheet in SHEETS}


@dataclass
class ListRow:
    number: int
    cells: list[object]
    person: str  # the register or passport number as written on the sheet
    person_row: int | None = None  # the Excel row of the main sheet that this person comes from
    values: dict[str, Any] = field(default_factory=dict)
    ext: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    status: str = "ok"  # "ok" (will be written), "error" (refused), "skipped" (person not imported by this run)


@dataclass
class SheetPreview:
    sheet: ListSheet
    headings: list[str]
    rows: list[ListRow]

    @property
    def ok(self) -> int:
        return sum(row.status == "ok" for row in self.rows)

    @property
    def refused(self) -> int:
        return sum(row.status != "ok" for row in self.rows)


def link_key(row: ParsedRow) -> list[str]:
    """The keys under which a main-sheet row can be found: its register number and its passport number."""
    keys: list[str] = []
    if "register_no" in row.values:
        keys.append(normalize_register_no(str(row.values["register_no"])))
    if "passport_no" in row.values:
        keys.append("".join(str(row.values["passport_no"]).split()).upper())
    return keys


def _text(raw: object) -> str:
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw).strip()


@dataclass
class _Names:
    """Name -> id lookups, loaded once per preview. Names compare lower case with single spaces."""

    by_model: dict[str, dict[str, int]]
    districts: dict[tuple[int, str], int]

    @staticmethod
    def _key(text: str) -> str:
        return " ".join(text.lower().split())

    @classmethod
    def load(cls) -> "_Names":
        by_model: dict[str, dict[str, int]] = {}
        for lookup, model in MODELS.items():
            names: dict[str, int] = {}
            for pk, name in model.objects.values_list("pk", "name"):
                if name and name.strip():
                    names.setdefault(cls._key(name), pk)
            by_model[lookup] = names
        districts: dict[tuple[int, str], int] = {}
        for pk, city_id, name in District.objects.values_list("pk", "city_id", "name"):
            if name and name.strip():
                districts.setdefault((city_id, cls._key(name)), pk)
        return cls(by_model, districts)

    def find(self, lookup: str, text: str) -> int | None:
        key = self._key(text)
        if lookup in CHOICES:
            for code, label in CHOICES[lookup].items():
                if key in (self._key(label), str(code)):
                    return code
            return None
        return self.by_model[lookup].get(key)


def _cell_text(raw: object, date_field: bool, date_format: str) -> str:
    """The text the form gets for a cell. A date cell, or a date in the file's date format, becomes yyyy-mm-dd."""
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    text = _text(raw)
    if date_field:
        try:
            return datetime.strptime(text, DATE_FORMATS[date_format][1]).date().isoformat()
        except (ValueError, KeyError):
            pass
    return text


def _form_data(
    sheet: ListSheet, cells: dict[str, object], names: _Names, date_format: str, errors: list[str]
) -> dict[str, str]:
    """Turns the cells of one row into the data its row form is given: a looked-up name becomes an id."""
    base = FORMS[sheet.kind].base_fields
    data: dict[str, str] = {}
    city_id: int | None = None
    for name, lookup in sheet.columns:
        if name not in cells:
            continue
        raw = cells[name]
        if lookup is None:
            data[name] = _cell_text(raw, isinstance(base[name], forms.DateField), date_format)
            continue
        text = _text(raw)
        if lookup == "district":
            pk = names.districts.get((city_id, _Names._key(text))) if city_id is not None else None
        else:
            pk = names.find(lookup, text)
        if pk is None:
            errors.append(f"{sheet.label(name)} олдсонгүй: {text}")
            continue
        data[name] = str(pk)
        if name == "city":
            city_id = pk
    return data


def _parse_row(
    sheet: ListSheet, number: int, cells: list[object], positions: dict[int, str], names: _Names, date_format: str
) -> ListRow:
    link = _text(cells[0]) if cells and cells[0] is not None else ""
    row = ListRow(number=number, cells=cells, person=link)
    by_field: dict[str, object] = {}
    for position, name in positions.items():
        if position < len(cells) and cells[position] is not None and _text(cells[position]):
            by_field[name] = cells[position]
    data = _form_data(sheet, by_field, names, date_format, row.errors)
    form = FORMS[sheet.kind](data, adding=True)
    if not form.is_valid():
        for name, messages in form.errors.items():
            label = sheet.label(name) if name in {column for column, _ in sheet.columns} else name
            row.errors.extend(f"{label}: {message}" for message in messages)
    if not row.errors:
        row.values, row.ext = form.values()
    row.status = "error" if row.errors else "ok"
    return row


def _positions(sheet: ListSheet, headings: list[str]) -> tuple[int | None, dict[int, str]]:
    """The column of the person link, and {column index: form field} for every heading that names a field."""
    wanted = {normalize_heading(sheet.label(name)): name for name, _ in sheet.columns}
    link: int | None = None
    positions: dict[int, str] = {}
    for index, heading in enumerate(headings):
        norm = normalize_heading(heading)
        if link is None and (norm == normalize_heading(LINK_LABEL) or norm in LINK_ALIASES):
            link = index
        elif norm in wanted and wanted[norm] not in positions.values():
            positions[index] = wanted[norm]
    return link, positions


def _attach(row: ListRow, people: dict[str, ParsedRow]) -> None:
    """Finds the main-sheet person of a row. A row refused for a bad value stays refused whatever the person is."""
    if not row.person:
        row.errors.append(NO_LINK)
        row.status = "error"
        return
    key = normalize_register_no(row.person)
    person = people.get(key) or people.get("".join(row.person.split()).upper())
    if person is None:
        row.errors.append(NO_PERSON)
        row.status = "error"
        return
    row.person_row = person.number
    if row.status != "ok":
        return
    if person.status == "duplicate":
        row.status, row.errors = "skipped", [PERSON_EXISTS]
    elif person.status != "new":
        row.status, row.errors = "skipped", [PERSON_REFUSED]


def _read(data: bytes, sheet: ListSheet, name: str) -> tuple[list[str], list[tuple[int, list[object]]]]:
    try:
        return read_rows(data, name, 1)
    except ImportFileError as exc:
        if str(exc) == NO_DATA:  # a sheet with a heading and no rows
            return [], []
        raise


def build_list_previews(
    data: bytes, main_sheet: str, date_format: str, rows: Iterable[ParsedRow]
) -> dict[str, SheetPreview]:
    """The checked rows of every list sheet the file has, by list kind. A sheet that is not there gives no entry."""
    present = [name for name in sheet_names(data) if name != main_sheet]
    wanted = [sheet for sheet in SHEETS if sheet.title in present]
    if not wanted:
        return {}
    people: dict[str, ParsedRow] = {}
    for row in rows:
        for key in link_key(row):
            people.setdefault(key, row)
    names = _Names.load()
    chosen_format = date_format if date_format in DATE_FORMATS else "iso"
    previews: dict[str, SheetPreview] = {}
    for sheet in wanted:
        headings, numbered = _read(data, sheet, sheet.title)
        if not numbered:  # headings only (or the template's example row only): nothing to add, nothing to check
            previews[sheet.kind] = SheetPreview(sheet, sheet.headings(), [])
            continue
        link, positions = _positions(sheet, headings)
        if link is None:
            raise ImportFileError(f"«{sheet.title}» хуудасны эхний баганын гарчиг «{LINK_LABEL}» байх ёстой.")
        # The link column is read as column 0 below, so a sheet that has it elsewhere is moved to the front.
        listed: list[ListRow] = []
        for number, cells in numbered:
            ordered = [cells[link] if link < len(cells) else None, *cells]
            shifted = {position + 1: name for position, name in positions.items()}
            parsed = _parse_row(sheet, number, ordered, shifted, names, chosen_format)
            _attach(parsed, people)
            parsed.cells = cells
            listed.append(parsed)
        previews[sheet.kind] = SheetPreview(sheet, headings, listed)
    return previews

"""Write layer for the personal lists on production tables: the only code that writes them (D-017).

Lists: family, relative, education (+ ext), certificate, training, language, talent (raw SQL, no model), gift (+ ext),
material_help,
address, emergency contact.
Every public function is atomic. A refused change raises PersonalConflict with the user-facing text.
Production ids come from the database sequences, so nothing here sets a primary key.
"""

from collections.abc import Callable
from typing import Any, cast

from accounts.models import User
from django.db import DataError, IntegrityError, connection, transaction
from django.db.models import Model
from macs.dialect import lock_suffix
from macs.models import (
    AddressRow,
    ArmyRankRow,
    AwardRow,
    BeforeWorkRow,
    BodyRow,
    CertificateRow,
    ComplaintRow,
    ContactRow,
    DisciplineRow,
    DriverRow,
    FamilyRow,
    ForeignLanguage,
    LanguageRow,
    MaterialHelpRow,
    MilitaryRow,
    PresentRow,
    QualificationRow,
    RelativeRow,
    SkillWorkRow,
    TalentKind,
    TrainingRow,
)
from macs.triggers import PERSONAL_WRITE_TABLES, database_has_triggers, require

from employees.models import (
    PERSONAL_ADDED,
    PERSONAL_DELETED,
    PERSONAL_UPDATED,
    ActivityEntry,
    ActivityKind,
    Employee,
    GiftExt,
)
from employees.money import group
from employees.services import macs_writes
from employees.services.display import shown

KINDS = (
    "family",
    "relative",
    "education",
    "before_work",
    "certificate",
    "training",
    "language",
    "talent",
    "skill",
    "gift",
    "material_help",
    "address",
    "contact",
    "award",
    "discipline",
    "complaint",
    "body",
    "driver",
    "military",
    "army_rank",
)
TITLES = {
    "family": "Гэр бүл",
    "relative": "Хамаатан садан",
    "education": "Боловсрол",
    "before_work": "Ажлын туршлага",
    "certificate": "Мэргэшил, сертификат",
    "training": "Сургалт",
    "language": "Гадаад хэл",
    "talent": "Авьяас",
    "skill": "Ур чадварын даалгавар",
    "gift": "Олгосон бэлэг",
    "material_help": "Буцалтгүй тусламж",
    "address": "Хаяг",
    "contact": "Яаралтай үед холбогдох",
    "award": "Шагнал урамшил",
    "discipline": "Сахилгын шийтгэл",
    "complaint": "Үйлчлүүлэгчийн гомдол",
    "body": "Эрүүл мэндийн үзлэг",
    "driver": "Жолоо",
    "military": "Цэргийн алба",
    "army_rank": "Цэргийн цол",
}

STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу"
GIFT_DUPLICATE = "Энэ бэлэг аль хэдийн бүртгэгдсэн байна"
TALENT_DUPLICATE = "Энэ авьяас аль хэдийн бүртгэгдсэн байна"
CONSTRAINT = "Өгөгдөл хадгалах боломжгүй: шаардлагатай талбар дутуу эсвэл буруу байна"
# Training codes (hr_training.tr_type and pay_type); codes are stored, labels are shown.
TR_TYPES = {1: "Дотоод", 2: "Гадаад"}
PAY_TYPES = {1: "Зээл", 2: "Өөрөө", 3: "Байгууллага", 4: "Гадны багш", 5: "Байгууллага"}
# Complaint codes (hr_complaints.ctype and complaint_name): fixed lists typed into the old screen, no table.
COMPLAINT_TYPES = {1: "Харилцаа", 2: "Ур чадвар"}
COMPLAINT_KINDS = {1: "Аман", 2: "Санал асуулга"}

Snapshot = dict[str, object]


class PersonalConflict(Exception):
    """A refused write; the message is the user-facing text."""


_MODELS: dict[str, Any] = {
    "family": FamilyRow,
    "relative": RelativeRow,
    "before_work": BeforeWorkRow,
    "education": QualificationRow,
    "certificate": CertificateRow,
    "training": TrainingRow,
    "language": LanguageRow,
    "skill": SkillWorkRow,
    "gift": PresentRow,
    "material_help": MaterialHelpRow,
    "award": AwardRow,
    "discipline": DisciplineRow,
    "complaint": ComplaintRow,
    "body": BodyRow,
    "driver": DriverRow,
    "military": MilitaryRow,
    "army_rank": ArmyRankRow,
    "address": AddressRow,
    "contact": ContactRow,
}
# kind -> (ext model, its key field name). Ext rows hold HR-only fields; their key is the production id.
_EXT: dict[str, tuple[Any, str]] = {"gift": (GiftExt, "present")}
_TALENT_COLUMNS = ("talent_ident", "trained_year", "description")
_DUPLICATE_CONSTRAINTS = {"unq1_given_present": GIFT_DUPLICATE, "emp_talents_idx1": TALENT_DUPLICATE}

_TALENT_SELECT = (
    "SELECT talent_ident, trained_year, description FROM emp_talents WHERE emp_ident = %s AND talent_ident = %s"
)
_TALENT_INSERT = "INSERT INTO emp_talents (emp_ident, talent_ident, trained_year, description) VALUES (%s, %s, %s, %s)"
_TALENT_UPDATE = (
    "UPDATE emp_talents SET talent_ident = %s, trained_year = %s, description = %s"
    " WHERE emp_ident = %s AND talent_ident = %s"
)
_TALENT_DELETE = "DELETE FROM emp_talents WHERE emp_ident = %s AND talent_ident = %s"
_ADDRESS_DELETE = "DELETE FROM address WHERE address_id = %s AND employee_ident = %s"


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown personal list: {kind}")


def snapshot(kind: str, row: Any) -> Snapshot:
    """The production columns of one row as read, keyed by model attname (talents: a 3-tuple)."""
    if kind == "talent":
        return dict(zip(_TALENT_COLUMNS, row, strict=True))
    model = _MODELS[kind]
    return {f.attname: getattr(row, f.attname) for f in model._meta.concrete_fields if not f.primary_key}


def load(kind: str, employee: Employee, key: Any) -> Snapshot | None:
    """The current row a form should show, or None when it no longer exists for this employee."""
    _check_kind(kind)
    if kind == "talent":
        row = _talent_row(employee, key, lock=False)
        return None if row is None else snapshot(kind, row)
    row = _MODELS[kind].objects.filter(pk=key, employee=employee).first()
    return None if row is None else snapshot(kind, row)


def _talent_row(employee: Employee, talent_ident: Any, *, lock: bool) -> tuple[Any, ...] | None:
    sql = _TALENT_SELECT + (lock_suffix() if lock else "")
    with connection.cursor() as cur:
        cur.execute(sql, [employee.pk, talent_ident])
        found: tuple[Any, ...] | None = cur.fetchone()
    return found


def _conflict(exc: Exception) -> PersonalConflict:
    text = str(exc)
    for constraint, message in _DUPLICATE_CONSTRAINTS.items():
        if constraint in text:
            return PersonalConflict(message)
    return PersonalConflict(CONSTRAINT)


def _guarded(action: Callable[[], Any]) -> Any:
    """Run one write in a savepoint; a database constraint or data error becomes a form error."""
    try:
        with transaction.atomic():
            return action()
    except (IntegrityError, DataError) as exc:
        raise _conflict(exc) from exc


def _save_ext(kind: str, row: Any, ext: dict[str, object]) -> None:
    if kind not in _EXT:
        return
    model, field = _EXT[kind]
    filled = any(value not in (None, "") for value in ext.values())
    if not filled and not model.objects.filter(pk=row.pk).exists():
        return
    model.objects.update_or_create(defaults=ext, **{field: row})


def _delete_ext(kind: str, key: Any) -> None:
    if kind in _EXT:
        model, _ = _EXT[kind]
        model.objects.filter(pk=key).delete()


def _list_name(model: type[ForeignLanguage] | type[TalentKind], pk: Any) -> str:
    """The list entry's name for the log; the id as text when it is not a known entry."""
    if not pk:
        return ""
    name = model.objects.filter(pk=pk).values_list("name", flat=True).first()
    return str(name or pk)


def _summary(kind: str, data: dict[str, object]) -> str:
    if kind in ("family", "relative"):
        return str(data.get("given_name") or "")
    if kind == "education":
        return str(data.get("org_name") or "")
    if kind == "before_work":
        return str(data.get("worked_place") or "")
    if kind == "talent":
        return _list_name(TalentKind, data.get("talent_ident"))
    if kind == "skill":
        return str(data.get("description") or "")
    if kind == "certificate":
        return str(data.get("org_edu") or "")
    if kind == "training":
        return str(data.get("description") or "")
    if kind == "language":
        return _list_name(ForeignLanguage, data.get("language_id"))
    if kind == "gift":
        return str(data.get("pdate") or "")
    if kind == "material_help":
        return str(data.get("help_date") or "")
    if kind == "award":
        return str(data.get("award_name") or "")
    if kind == "discipline":
        return str(data.get("discipline_date") or "")
    if kind == "complaint":
        return str(data.get("cdate") or "")
    if kind == "body":
        return str(data.get("inserted_ognoo") or "")
    if kind == "driver":
        return str(data.get("number_driver") or "")
    if kind == "military":
        return str(data.get("army_rank") or "")
    if kind == "army_rank":
        return str(data.get("rank") or "")
    if kind == "address":
        return str(data.get("street") or "")
    return str(data.get("name") or "")


_VERB_KINDS = {PERSONAL_ADDED: ActivityKind.ADDED, PERSONAL_DELETED: ActivityKind.DELETED}
# Money columns of the personal lists: shown as 2,500,000₮.
_MONEY_KEYS = frozenset({"amount", "price"})
# The talent list has no model, so its three columns are labelled as on the form (TalentRowForm).
_TALENT_LABELS = {"talent_ident": "Авьяас", "trained_year": "Сургасан он", "description": "Тайлбар"}


def _field_for(kind: str, key: str) -> Any | None:
    """The model field behind one snapshot key: the row model, then the HR-only ext model."""
    models = ([_MODELS[kind]] if kind in _MODELS else []) + ([_EXT[kind][0]] if kind in _EXT else [])
    for model in models:
        for field in model._meta.concrete_fields:
            if field.attname == key:
                return field
    return None


def _label(kind: str, key: str) -> str:
    field = _field_for(kind, key)
    if field is not None:
        return str(field.verbose_name)
    return _TALENT_LABELS.get(key, key)


def _related_model(kind: str, key: str) -> type[Model] | None:
    """The code list a key points at (a foreign key, or the talent list), None for a plain column."""
    if kind == "talent" and key == "talent_ident":
        return TalentKind
    field = _field_for(kind, key)
    if field is not None and field.is_relation:
        return cast(type[Model], field.related_model)
    return None


def _list_names(wanted: dict[type[Model], set[Any]]) -> dict[tuple[type[Model], Any], str]:
    """The names of the code-list entries, one IN query per list (not one per value)."""
    names: dict[tuple[type[Model], Any], str] = {}
    for model, pks in wanted.items():
        for pk, row in cast(Any, model).objects.in_bulk(list(pks)).items():
            names[(model, pk)] = str(row)
    return names


def _value_text(kind: str, key: str, value: object, names: dict[tuple[type[Model], Any], str]) -> str:
    """A snapshot value as the log shows it: list names, formatted dates and money, '' when blank."""
    if value is None or value == "":
        return ""
    model = _related_model(kind, key)
    if model is not None:
        return names.get((model, value), str(value))
    field = _field_for(kind, key)
    text = shown(field, value) if field is not None else str(value)
    if key in _MONEY_KEYS:
        text = f"{group(value)}₮"  # type: ignore[arg-type]
    return text


def _changes(kind: str, old: dict[str, object] | None, new: dict[str, object] | None) -> list[dict[str, str]]:
    """One {field, old, new} per column whose value differs. Add: old is empty; delete: new is empty.

    The row's owner (employee_id) never changes, so it is not a change. Code-list names for all changed values
    are read with one query per list.
    """
    before, after = old or {}, new or {}
    pending: list[tuple[str, object, object]] = []
    for key in dict.fromkeys([*before, *after]):
        if key == "employee_id":
            continue
        was, now = before.get(key), after.get(key)
        if (was is None or was == "") and (now is None or now == ""):
            continue
        if was == now:
            continue
        pending.append((key, was, now))
    wanted: dict[type[Model], set[Any]] = {}
    for key, was, now in pending:
        model = _related_model(kind, key)
        if model is not None:
            wanted.setdefault(model, set()).update(v for v in (was, now) if v not in (None, ""))
    names = _list_names(wanted) if wanted else {}
    return [
        {
            "field": _label(kind, key),
            "old": _value_text(kind, key, was, names),
            "new": _value_text(kind, key, now, names),
        }
        for key, was, now in pending
    ]


def _log(
    kind: str,
    employee: Employee,
    by: User,
    verb: str,
    data: dict[str, object],
    changes: list[dict[str, str]],
) -> None:
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=_VERB_KINDS.get(verb, ActivityKind.CHANGED),
        personal=True,
        message=f"{TITLES[kind]}: {verb} — {_summary(kind, data)}",
        changes=changes,
    )


_TRIGGER_KINDS = ("contact", "address")
_TRIGGER_TABLES = PERSONAL_WRITE_TABLES
# CONTACTING_AI0 (insert) and CONTACTING_AU0 (update, type 2 only) write employee.email for type 4 and
# employee.homephone for type 2 in the database. HR refreshes those two columns and never writes them itself.
_CONTACT_TYPES_WITH_EMPLOYEE_EFFECT = (2, 4)
# Firebird: the same two triggers copy the value into the employee column. A longer value makes the trigger's UPDATE
# fail with a truncation error that the write layer does not map, so the length is checked here, before any write.
_CONTACT_TARGET_LIMITS = {
    2: ("private_phone", "Утасны дугаар хэт урт байна (дээд тал нь {n} тэмдэгт)."),
    4: ("email", "И-мэйл хаяг хэт урт байна (дээд тал нь {n} тэмдэгт)."),
}


def _check_contact_length(contact_type_id: object, value: object) -> None:
    """Firebird only: refuse a type-2 or type-4 contact value longer than the employee column it is copied into."""
    if not database_has_triggers() or contact_type_id not in _CONTACT_TARGET_LIMITS:
        return
    field_name, message = _CONTACT_TARGET_LIMITS[cast(int, contact_type_id)]
    limit = Employee._meta.get_field(field_name).max_length
    if len(str(value or "")) > limit:
        raise PersonalConflict(message.format(n=limit))


def _refresh_contact_effect(employee: Employee, contact_type_id: object) -> None:
    """Firebird only: re-read the employee columns a contact trigger may have changed into the instance the caller
    holds, so the page shows the stored value and a later save of that instance does not carry a stale one."""
    if database_has_triggers() and contact_type_id in _CONTACT_TYPES_WITH_EMPLOYEE_EFFECT:
        employee.refresh_from_db(fields=["email", "private_phone"])


@transaction.atomic
def add(kind: str, employee: Employee, values: dict[str, object], ext: dict[str, object], by: User) -> object:
    """Insert one row. Returns the new key: the production id, or the talent_ident."""
    _check_kind(kind)
    if kind in _TRIGGER_KINDS:
        require(*_TRIGGER_TABLES)
    if kind == "contact":
        _check_contact_length(values.get("contact_type_id"), values.get("value"))

    def write() -> object:
        if kind == "talent":
            params: list[Any] = [
                employee.pk,
                values["talent_ident"],
                values.get("trained_year"),
                values.get("description"),
            ]
            with connection.cursor() as cur:
                cur.execute(_TALENT_INSERT, params)
            return values["talent_ident"]
        row = _MODELS[kind].objects.create(employee=employee, **values)
        _save_ext(kind, row, ext)
        if kind == "address" and not database_has_triggers():
            # ADDRESS_BI copied the street to the ERP row on insert (Firebird); PostgreSQL has no trigger.
            macs_writes.copy_address_to_customer(employee, row.street)
        if kind == "contact":
            _refresh_contact_effect(employee, row.contact_type_id)
        return row.pk

    key = _guarded(write)
    _log(kind, employee, by, PERSONAL_ADDED, values, _changes(kind, None, {**values, **ext}))
    return key


@transaction.atomic
def update(
    kind: str,
    employee: Employee,
    key: Any,
    loaded: Snapshot,
    values: dict[str, object],
    ext: dict[str, object],
    by: User,
) -> None:
    """Change one row, if it still matches `loaded`. `values` uses model attnames (talents: the 3 columns)."""
    _check_kind(kind)
    if kind in _TRIGGER_KINDS:
        require(*_TRIGGER_TABLES)
    if kind == "contact":
        _check_contact_length(
            values.get("contact_type_id", loaded.get("contact_type_id")), values.get("value", loaded.get("value"))
        )

    def write() -> dict[str, object]:
        if kind == "talent":
            current = _talent_row(employee, key, lock=True)
            if current is None or snapshot(kind, current) != loaded:
                raise PersonalConflict(STALE)
            new = {**loaded, **values}
            params: list[Any] = [new["talent_ident"], new.get("trained_year"), new.get("description"), employee.pk, key]
            with connection.cursor() as cur:
                cur.execute(_TALENT_UPDATE, params)
            return new
        row = _MODELS[kind].objects.select_for_update().filter(pk=key, employee=employee).first()
        if row is None or snapshot(kind, row) != loaded:
            raise PersonalConflict(STALE)
        # Filtered by employee too: the address key is (address_id, employee_ident), so row.save() on the pk
        # alone would also rewrite another employee's row that shares the address_id.
        _MODELS[kind].objects.filter(pk=key, employee=employee).update(**values)
        _save_ext(kind, row, ext)
        new = {**loaded, **values}
        if kind == "address":  # no update trigger exists in MACS, so HR copies the street on every save
            macs_writes.copy_address_to_customer(employee, new.get("street"))  # type: ignore[arg-type]
        if kind == "contact":
            _refresh_contact_effect(employee, new["contact_type_id"])
        return new

    data = _guarded(write)
    changes = _changes(kind, loaded, data)
    # An unchanged save writes no entry. Ext values (gift note) are not compared: their old value is not loaded,
    # so a save of an ext kind is always logged, as before.
    if changes or kind in _EXT:
        _log(kind, employee, by, PERSONAL_UPDATED, data, changes)


@transaction.atomic
def delete(kind: str, employee: Employee, key: Any, loaded: Snapshot, by: User) -> None:
    """Delete one row, if it still matches `loaded`. The ext row goes with it."""
    _check_kind(kind)

    def write() -> None:
        if kind == "talent":
            current = _talent_row(employee, key, lock=True)
            if current is None or snapshot(kind, current) != loaded:
                raise PersonalConflict(STALE)
            with connection.cursor() as cur:
                cur.execute(_TALENT_DELETE, [employee.pk, key])
            return
        row = _MODELS[kind].objects.select_for_update().filter(pk=key, employee=employee).first()
        if row is None or snapshot(kind, row) != loaded:
            raise PersonalConflict(STALE)
        if kind == "address":  # a queryset delete goes by pk alone and would hit the other employee's row too
            with connection.cursor() as cur:
                cur.execute(_ADDRESS_DELETE, [key, employee.pk])
        else:
            _MODELS[kind].objects.filter(pk=key, employee=employee).delete()
        _delete_ext(kind, key)

    _guarded(write)
    _log(kind, employee, by, PERSONAL_DELETED, loaded, _changes(kind, loaded, None))

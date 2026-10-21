"""Write layer for the personal lists on production tables: the only code that writes them (D-017).

Lists: family, education (+ ext), certificate, training, language, talent (raw SQL, no model), gift (+ ext),
address, emergency contact.
Every public function is atomic. A refused change raises PersonalConflict with the user-facing text.
Production ids come from the database sequences, so nothing here sets a primary key.
"""

from collections.abc import Callable
from typing import Any

from accounts.models import User
from django.db import DataError, IntegrityError, connection, transaction
from macs.models import (
    AddressRow,
    CertificateRow,
    ContactRow,
    FamilyRow,
    ForeignLanguage,
    LanguageRow,
    PresentRow,
    QualificationRow,
    TrainingRow,
)

from employees.models import ActivityEntry, ActivityKind, Employee, GiftExt
from employees.services import macs_writes

KINDS = ("family", "education", "certificate", "training", "language", "talent", "gift", "address", "contact")
TITLES = {
    "family": "Гэр бүл",
    "education": "Боловсрол",
    "certificate": "Мэргэшил, сертификат",
    "training": "Сургалт",
    "language": "Гадаад хэл",
    "talent": "Авьяас",
    "gift": "Олгосон бэлэг",
    "address": "Хаяг",
    "contact": "Яаралтай үед холбогдох",
}

STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу"
GIFT_DUPLICATE = "Энэ бэлэг аль хэдийн бүртгэгдсэн байна"
TALENT_DUPLICATE = "Энэ авьяас аль хэдийн бүртгэгдсэн байна"
CONSTRAINT = "Өгөгдөл хадгалах боломжгүй: шаардлагатай талбар дутуу эсвэл буруу байна"
# Training codes (hr_training.tr_type and pay_type); codes are stored, labels are shown.
TR_TYPES = {1: "Дотоод", 2: "Гадаад"}
PAY_TYPES = {1: "Зээл", 2: "Өөрөө", 3: "Байгууллага", 4: "Гадны багш", 5: "Байгууллага"}

Snapshot = dict[str, object]


class PersonalConflict(Exception):
    """A refused write; the message is the user-facing text."""


_MODELS: dict[str, Any] = {
    "family": FamilyRow,
    "education": QualificationRow,
    "certificate": CertificateRow,
    "training": TrainingRow,
    "language": LanguageRow,
    "gift": PresentRow,
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
    sql = _TALENT_SELECT + (" FOR UPDATE" if lock else "")
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


def _language_name(language_id: Any) -> str:
    """The language's name for the log; the id as text when it is not a known language."""
    if not language_id:
        return ""
    name = ForeignLanguage.objects.filter(pk=language_id).values_list("name", flat=True).first()
    return str(name or language_id)


def _summary(kind: str, data: dict[str, object]) -> str:
    if kind == "family":
        return str(data.get("given_name") or "")
    if kind == "education":
        return str(data.get("org_name") or "")
    if kind == "talent":
        return str(data.get("talent_ident") or "")
    if kind == "certificate":
        return str(data.get("org_edu") or "")
    if kind == "training":
        return str(data.get("description") or "")
    if kind == "language":
        return _language_name(data.get("language_id"))
    if kind == "gift":
        return str(data.get("pdate") or "")
    if kind == "address":
        return str(data.get("street") or "")
    return str(data.get("name") or "")


def _log(kind: str, employee: Employee, by: User, verb: str, data: dict[str, object]) -> None:
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.CHANGED,
        personal=True,
        message=f"{TITLES[kind]}: {verb} — {_summary(kind, data)}",
    )


@transaction.atomic
def add(kind: str, employee: Employee, values: dict[str, object], ext: dict[str, object], by: User) -> object:
    """Insert one row. Returns the new key: the production id, or the talent_ident."""
    _check_kind(kind)

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
        if kind == "address":
            macs_writes.copy_address_to_customer(employee, row.street)
        return row.pk

    key = _guarded(write)
    _log(kind, employee, by, "нэмсэн", values)
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
        if kind == "address":
            macs_writes.copy_address_to_customer(employee, new.get("street"))  # type: ignore[arg-type]
        return new

    data = _guarded(write)
    _log(kind, employee, by, "засварласан", data)


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
    _log(kind, employee, by, "устгасан", loaded)

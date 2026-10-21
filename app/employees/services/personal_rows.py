"""Read layer for the personal lists on production tables (D-017).

Merges each production row with its Info HR extension row (education and gift only) into one
display shape. Read-only: writes go through employees.services.personal_writes.
A dangling list id (a code that no longer exists) shows as a dash and is logged.
"""

import logging
from dataclasses import dataclass
from typing import Any

from django.db import connection
from macs.models import (
    AcademicDegree,
    AddressRow,
    CertificateRow,
    City,
    ContactRow,
    ContactType,
    Country,
    District,
    EducationLevel,
    FamilyRelation,
    FamilyRow,
    ForeignLanguage,
    LanguageRow,
    PresentRow,
    PresentType,
    ProfessionType,
    QualificationRow,
    QualificationType,
    SpecEduType,
    TalentKind,
    TrainingRow,
)

from employees.models import Employee, GiftExt
from employees.services import personal_writes as pw

logger = logging.getLogger(__name__)

EM_DASH = "—"
_ALL = object()  # "no key filter" sentinel


@dataclass
class PersonalRow:
    kind: str
    key: object  # production id, or talent_ident for talents
    values: dict[str, object]  # display values; list ids replaced by names
    ext: dict[str, object]  # HR-only fields; all None when there is no ext row
    snapshot: pw.Snapshot  # same shape as personal_writes.snapshot(), used for stale checks
    from_old_system: bool  # education/gift only: True when no ext row exists


@dataclass(frozen=True)
class _Spec:
    model: Any  # production model; None for talents (raw SQL)
    order: tuple[str, ...]
    lookups: tuple[tuple[str, str, Any], ...]  # (display name, id attname, list model)
    fields: tuple[str, ...]  # plain values copied from the snapshot
    ext_model: Any = None
    ext_fields: tuple[str, ...] = ()


_SPECS: dict[str, _Spec] = {
    "family": _Spec(
        model=FamilyRow,
        order=("birth_date", "id"),
        lookups=(("relation", "relation_id", FamilyRelation),),
        fields=("given_name", "surname", "birth_date", "job", "phone"),
    ),
    "education": _Spec(
        model=QualificationRow,
        order=("start_year", "id"),
        lookups=(
            ("qualification_type", "qualification_type_id", QualificationType),
            ("profession_type", "profession_type_id", ProfessionType),
            ("edu_level", "edu_level_id", EducationLevel),
            ("grade", "grade_id", AcademicDegree),
        ),
        fields=("org_name", "start_year", "end_year", "credit_score", "diplom_number", "country"),
    ),
    "certificate": _Spec(
        model=CertificateRow,
        order=("-certify_year", "id"),
        lookups=(("cert_type", "cert_type_id", SpecEduType),),
        fields=(
            "org_edu",
            "certify_number",
            "certify_date",
            "profession",
            "spec_profession",
            "end_date",
            "certify_year",
        ),
    ),
    "training": _Spec(
        model=TrainingRow,
        order=("-start_year", "id"),
        lookups=(),
        fields=(
            "tr_type",
            "description",
            "start_date",
            "days",
            "amount",
            "pay_type",
            "training_center",
            "start_year",
        ),
    ),
    "language": _Spec(
        model=LanguageRow,
        order=("id",),
        lookups=(("language", "language_id", ForeignLanguage),),
        fields=("understand_lvl", "speaking_lvl", "reading_lvl", "writing_lvl", "description"),
    ),
    "talent": _Spec(
        model=None,
        order=(),
        lookups=(("talent", "talent_ident", TalentKind),),
        fields=("trained_year", "description"),
    ),
    "gift": _Spec(
        model=PresentRow,
        order=("-pdate", "id"),
        lookups=(("present_type", "present_type_id", PresentType),),
        fields=("pdate", "given_year", "childqty", "price", "child_age", "given"),
        ext_model=GiftExt,
        ext_fields=("note",),
    ),
    "address": _Spec(
        model=AddressRow,
        order=("id",),
        lookups=(("city", "city_id", City), ("district", "district_id", District)),
        fields=("street",),
    ),
    "contact": _Spec(
        model=ContactRow,
        order=("id",),
        lookups=(("contact_type", "contact_type_id", ContactType),),
        fields=("name", "relative", "value"),
    ),
}

# Physical (ctid) order is used for talents, as the brief asks; there is no PK to order by.
_TALENT_LIST_SQL = "SELECT talent_ident, trained_year, description FROM emp_talents WHERE emp_ident = %s"


def rows(kind: str, employee: Employee) -> list[PersonalRow]:
    """All rows of one personal list for this employee, in display order."""
    return _build(kind, _raw(kind, employee, _ALL))


def row(kind: str, employee: Employee, key: Any) -> PersonalRow | None:
    """One row by key (production id, or talent_ident), or None if it does not belong to this employee."""
    found = _build(kind, _raw(kind, employee, key))
    return found[0] if found else None


def _raw(kind: str, employee: Employee, key: object) -> list[Any]:
    """Raw rows: model instances, or 3-tuples for talents."""
    pw._check_kind(kind)
    spec = _SPECS[kind]
    if spec.model is None:
        sql = _TALENT_LIST_SQL
        params: list[Any] = [employee.pk]
        if key is not _ALL:
            sql += " AND talent_ident = %s"
            params.append(key)
        with connection.cursor() as cur:
            cur.execute(sql + " ORDER BY ctid", params)
            return list(cur.fetchall())
    qs = spec.model.objects.filter(employee=employee)
    if key is not _ALL:
        qs = qs.filter(pk=key)
    return list(qs.order_by(*spec.order))


def _build(kind: str, raw: list[Any]) -> list[PersonalRow]:
    spec = _SPECS[kind]
    snaps = [pw.snapshot(kind, r) for r in raw]
    names = {attname: _list_names(model, [s[attname] for s in snaps]) for _, attname, model in spec.lookups}
    country_names = _country_names([s["country"] for s in snaps]) if kind == "education" else {}
    ext_map = _ext_map(spec, raw)

    out: list[PersonalRow] = []
    for r, snap in zip(raw, snaps, strict=True):
        key = snap["talent_ident"] if spec.model is None else r.pk
        values: dict[str, object] = {}
        for display, attname, model in spec.lookups:
            values[display] = _resolve(kind, model, names[attname], snap[attname])
        for field in spec.fields:
            values[field] = snap[field]
        if kind == "education":
            country = snap["country"] if isinstance(snap["country"], str) else None
            values["country_name"] = _country_name(country, country_names)
        elif kind == "training":
            values["tr_type_label"] = _code_label(snap["tr_type"], pw.TR_TYPES)
            values["pay_type_label"] = _code_label(snap["pay_type"], pw.PAY_TYPES)

        ext_obj = ext_map.get(key) if spec.ext_model is not None else None
        ext = {f: getattr(ext_obj, f) for f in spec.ext_fields} if ext_obj else dict.fromkeys(spec.ext_fields)
        from_old = spec.ext_model is not None and ext_obj is None
        out.append(PersonalRow(kind, key, values, ext, snap, from_old))
    return out


def _ext_map(spec: _Spec, raw: list[Any]) -> dict[Any, Any]:
    """HR ext rows for these production rows, keyed by production id. Orphan ext rows are never read."""
    if spec.ext_model is None or not raw:
        return {}
    found: dict[Any, Any] = spec.ext_model.objects.in_bulk([r.pk for r in raw])
    return found


def _list_names(model: Any, ids: list[Any]) -> dict[Any, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {pk: str(obj.name or "") for pk, obj in model.objects.in_bulk(wanted).items()}


def _country_names(raws: list[Any]) -> dict[int, str]:
    """Country names for every raw country value that is a digit string of an existing id, in one query."""
    wanted = {int(r) for r in raws if isinstance(r, str) and r.strip().isdigit()}
    if not wanted:
        return {}
    return {pk: str(obj.name) for pk, obj in Country.objects.in_bulk(wanted).items() if obj.name}


def _country_name(raw: str | None, names: dict[int, str]) -> str:
    """The country name for a qualification row: the list name when the text is a known id, else the text."""
    text = (raw or "").strip()
    if not text:
        return EM_DASH
    if text.isdigit() and int(text) in names:
        return names[int(text)]
    return text


def _code_label(code: Any, labels: dict[int, str]) -> str:
    if code is None:
        return EM_DASH
    return labels.get(code, str(code))


def _resolve(kind: str, model: Any, names: dict[Any, str], ident: Any) -> str:
    if ident is None:
        return EM_DASH
    if ident in names:
        return names[ident]
    logger.warning("personal list %s: %s id %s not found; showing a dash", kind, model.__name__, ident)
    return EM_DASH

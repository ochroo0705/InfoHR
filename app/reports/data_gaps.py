"""The data gaps report («Дутуу мэдээлэл»): the employees with a blank field among the checked staff-list columns, and
which fields. One row per person. The checked columns are the staff list's own, so «blank» means what the list shows
blank, and a column the viewer may not see is never checked or named."""

from dataclasses import dataclass, replace

from accounts.models import User
from macs.models import Employee

from reports import staff_list
from reports.filters import Filters
from reports.types import Column, Report

# The staff-list columns checked, in the order they are named. A key the viewer may not see is skipped.
CHECKED: tuple[str, ...] = (
    "register_no",
    "birth_date",
    "gender",
    "department",
    "position",
    "first_hire_date",
    "contract_no",
    "work_phone",
    "private_phone",
    "email",
    "address",
    "contacts",
    "education_level",
    "social_insurance_no",
    "bank",
    "account_no",
)

_STAFF_COLUMNS: dict[str, Column] = {c.key: c for c in staff_list.COLUMNS}
_unknown = [key for key in CHECKED if key not in _STAFF_COLUMNS]
if _unknown:  # a renamed staff-list column must not silently drop a check
    raise RuntimeError(f"data_gaps.CHECKED names columns the staff list does not have: {_unknown}")


@dataclass(frozen=True)
class GapRow:
    staff: staff_list.StaffRow
    missing: tuple[str, ...]  # the labels of the checked columns that are blank, in CHECKED order
    checked: int  # how many columns were checked for this viewer


def checked_columns(user: User) -> list[Column]:
    """The checked staff-list columns this user may see, in CHECKED order."""
    visible = []
    for key in CHECKED:
        col = _STAFF_COLUMNS[key]
        if not col.needs or user.has_perm(col.needs):
            visible.append(col)
    return visible


def _blank(value: object) -> bool:
    """What the staff list shows as nothing: None, or text that is empty or only spaces."""
    return value is None or (isinstance(value, str) and not value.strip())


def rows(user: User, f: Filters) -> list[GapRow]:
    """The people with at least one blank checked column, most missing first, then by name."""
    cols = checked_columns(user)
    if not cols:
        return []
    # the staff rows load the lazily read fields (address, contacts…) only when their columns are named here
    staff = staff_list.rows(user, replace(f, columns=tuple(c.key for c in cols)))
    # department and position of legacy jobs, one query each for all rows
    staff_list.load_job_names([s.row.job for s in staff if s.row.job is not None])
    found: list[GapRow] = []
    for s in staff:
        missing = tuple(c.label for c in cols if _blank(c.value(s)))
        if missing:
            found.append(GapRow(staff=s, missing=missing, checked=len(cols)))
    found.sort(
        key=lambda r: (-len(r.missing), r.staff.row.employee.family_name or "", r.staff.row.employee.given_name or "")
    )
    return found


def _from_staff(col: Column) -> Column:
    """A staff-list column read from the staff row inside a gap row: the same value and link."""
    href = col.href
    return replace(
        col,
        value=lambda r: col.value(r.staff),
        href=(lambda r: href(r.staff)) if href is not None else None,
    )


def _filled_pct(r: GapRow) -> int:
    return round((r.checked - len(r.missing)) * 100 / r.checked)


COLUMNS: tuple[Column, ...] = (
    _from_staff(_STAFF_COLUMNS["code"]),
    _from_staff(_STAFF_COLUMNS["name"]),
    _from_staff(_STAFF_COLUMNS["department"]),
    _from_staff(_STAFF_COLUMNS["position"]),
    Column(key="missing_count", label="Дутуу талбар", value=lambda r: len(r.missing), numeric=True, kind="number"),
    Column(key="filled_pct", label="Бүрдэл, %", value=_filled_pct, numeric=True, kind="number"),
    Column(key="missing", label="Дутуу мэдээлэл", value=lambda r: "; ".join(r.missing)),
)


def _note(f: Filters) -> str:
    return (
        "Шалгасан талбарын аль нэг нь хоосон ажилтнууд. Бүрэн бөглөсөн ажилтан энд гарахгүй. "
        "Таны харах эрхгүй талбарыг шалгаагүй."
    )


REPORT = Report(
    key="data-gaps",
    title="Дутуу мэдээлэл",
    filters=("state", "as_of", "branch", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=rows,
    needs=("macs.view_employees",),
    source=Employee,
    group_options=("department", "position"),
    person=lambda r: r.staff.row.employee.pk,
    photo=lambda r: r.staff.row.employee,
    note=_note,
)

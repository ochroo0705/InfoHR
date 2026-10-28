"""E1 «Үйлдвэрийн ослын тайлан» and E2 «Хурц хордлогын тайлан»: the lines of the old procedures CALC_FACTORYACC and
CALC_FACTORYTOX (docs/migration/legacy-logic/procedures), one row per line with its number, label and count.
The accident rows (FactoryAccidentRow, kind `accident` or `toxic`) are kept by the old program; Info HR has no screen
for them. Both reports share one builder and differ only in their list of lines.

Branch rules as in the old procedures: line 6 filters by the employee's branch, every other accident line by the
accident's own branch. The staff counts (lines 1 and 2) are the working people of the branch."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from accounts.models import User
from employees import access
from employees.services.order_register import age_on
from macs.models import FactoryAccidentRow, InfoRow

from reports import survey_common
from reports.filters import Filters, period_of
from reports.survey_common import NEEDS_PERSONAL
from reports.types import Column, Report

FEMALE = "F"  # Employee.gender value of women
ORG_TYPES: tuple[str, ...] = ("01", "02", "03", "04")  # state, private, budget, foreign (the old `info.orgtype_code`)


@dataclass(frozen=True)
class StatLine:
    id: int  # the line's place, 1 up (the old procedure's ID)
    number: int | None  # the printed line number; None for a heading
    label: str
    value: int | None  # None for a heading


@dataclass(frozen=True)
class Context:
    rows: list[
        FactoryAccidentRow
    ]  # the kind's accident rows of the period, visible people only; the employee is loaded
    branch: int | None  # the branch filter
    working: int  # working people of the branch
    women: int  # working women of the branch
    org_type: str | None  # the organisation type code (`info.orgtype_code`)

    @property
    def scoped(self) -> list[FactoryAccidentRow]:
        """The rows of the accident's own branch: what every line but line 6 counts."""
        return [r for r in self.rows if self.branch is None or r.branch_id == self.branch]


Counter = Callable[[Context], int | None]
Line = tuple[int | None, str, Counter | None]  # (number, label, counter); a heading has no counter


def _employee(r: FactoryAccidentRow) -> Any:
    """The accident's employee (loaded by select_related)."""
    return r.employee


def _count(matches: Callable[[FactoryAccidentRow], bool] = lambda r: True) -> Counter:
    return lambda c: sum(1 for r in c.scoped if matches(r))


def _where(field: str, code: int) -> Counter:
    """Accident rows whose `facc_type`, `facc_reason` or `facc_result` is `code`."""
    return _count(lambda r: getattr(r, field) == code)


def _women_by_employee(c: Context) -> int:
    """The old line 6: the accident's employee is a woman and the EMPLOYEE is in the branch."""
    return sum(
        1 for r in c.rows if _employee(r).gender == FEMALE and (c.branch is None or _employee(r).branch_id == c.branch)
    )


def _age_band(low: int | None, high: int | None) -> Counter:
    """Accidents whose person was `low` or older and under `high` on the accident date; no birth date: not counted."""

    def matches(r: FactoryAccidentRow) -> bool:
        age = age_on(_employee(r).birth_date, r.accident_date)
        # a birth date after the accident gives no age (as survey_common._age): the person is in no band
        return age is not None and age >= 0 and (low is None or age >= low) and (high is None or age < high)

    return _count(matches)


def worked_years(r: FactoryAccidentRow) -> int | None:
    """Full years from the first hire to the accident (at least 0) plus the earlier service (CALC_WORKEDYEAR)."""
    years = age_on(_employee(r).first_hire_date, r.accident_date)
    if years is None:
        return None
    return max(years, 0) + (_employee(r).prior_service_years or 0)


def _worked_band(low: int | None, high: int | None) -> Counter:
    def matches(r: FactoryAccidentRow) -> bool:
        years = worked_years(r)
        return years is not None and (low is None or years >= low) and (high is None or years < high)

    return _count(matches)


def _ownership(code: str) -> Counter:
    """The total of the line «people in accidents» when the organisation has this type, else blank."""
    return lambda c: len(c.scoped) if c.org_type == code else None


def _tail(first: int) -> list[Line]:
    """The age, worked-year and ownership blocks, which both procedures share; they differ only in the numbers."""
    return [
        (None, "Нас", None),
        (first, "18 нас хүртэл", _age_band(None, 18)),
        (first + 1, "18-35 нас хүртэл", _age_band(18, 35)),
        (first + 2, "35-аас дээш", _age_band(35, None)),
        (None, "Ажилласан хугацаа", None),
        (first + 3, "5 жил хүртэл", _worked_band(None, 5)),
        (first + 4, "5-15 жил хүртэл", _worked_band(5, 15)),
        (first + 5, "15-аас дээш жил", _worked_band(15, None)),
        (None, "Аж ахуйн нэгж, байгууллагын өмчийн хэлбэр", None),
        (first + 6, "Төрийн болон төрийн өмч давамгайлсан", _ownership("01")),
        (first + 7, "Хувийн", _ownership("02")),
        (first + 8, "Төсвийн", _ownership("03")),
        (first + 9, "Гадаадын болон хамтарсан хөрөнгө оруулалттай", _ownership("04")),
    ]


def _head(total: str, group: str, people: str, women: str) -> list[Line]:
    """Lines 1-10, which have the same conditions in both procedures and differ in some labels."""
    return [
        (1, "Ажилтны дундаж тоо", lambda c: c.working),
        (2, "Үүнээс эмэгтэй", lambda c: c.women),
        (3, total, _count()),
        (4, group, _where("group_accident", 1)),
        (5, people, _count()),
        (6, women, _women_by_employee),
        (7, "Нас барсан хүний тоо", _where("facc_result", 1)),
        (8, "Хөгжлийн бэрхшээлтэй болсон хүний тоо", _where("facc_result", 2)),
        (9, "Хөдөлмөрийн чадвар түр алдсан хүний тоо", _where("facc_result", 3)),
        (10, "Мэргэжлийн ажлаас өөр ажилд шилжсэн хүний тоо", _where("facc_result", 4)),
    ]


# CALC_FACTORYACC. The line «Халтиргаанаас» (reason 8) has no number in the old procedure but is counted.
ACCIDENT_LINES: list[Line] = [
    *_head("Ослын тоо", "Үүнээс: Бүлэг ослын тоо", "Осолд орсон хүний тоо", "Үүнээс: эмэгтэй"),
    (None, "Ослын хэлбэр", None),
    (11, "Хүний амь нас хохирсон", _where("facc_type", 1)),
    (12, "Хүнд", _where("facc_type", 2)),
    (13, "Хөнгөн", _where("facc_type", 3)),
    (None, "Ослын шалтгаан", None),
    (14, "Машин механизм, тоног төхөөрөмжийн гэмтэл, алдаанаас", _where("facc_reason", 1)),
    (15, "Технологийн процесс зөрчсөнөөс", _where("facc_reason", 2)),
    (16, "Тээврийн хэрэгсэлээс", _where("facc_reason", 3)),
    (17, "Өргөх, зөөх төхөөрөмжөөс", _where("facc_reason", 4)),
    (18, "Цахилгаан гүйдэлд цохиулсанаас", _where("facc_reason", 5)),
    (19, "Халалт, түлэгдэлт, хөлдөлтөөс", _where("facc_reason", 6)),
    (20, "Уналт, нуралтаас", _where("facc_reason", 7)),
    (None, "Халтиргаанаас", _where("facc_reason", 8)),
    (21, "Аюулгүй ажиллах арга барилд хангалтгүй сургаснаас", _where("facc_reason", 9)),
    (22, "Ажлын хувцас, хамгаалах хэрэгсэлгүй ажилласнаас", _where("facc_reason", 10)),
    (23, "Онцгой ур чадвар шаардсан ажилд мэргэжлийн хүн ажиллуулаагүйгээс", _where("facc_reason", 11)),
    (24, "Химийн болон биологийн бодис алдагдсанаас", _where("facc_reason", 12)),
    (25, "Стандартын шаардлага хангаагүйгээс", _where("facc_reason", 13)),
    (26, "Бусад", _where("facc_reason", 14)),
    *_tail(27),
]

# CALC_FACTORYTOX
POISONING_LINES: list[Line] = [
    *_head("Хурц хордлого гарсан тоо", "Үүнээс: Бүлэг хордлого", "Хурц хордлогод өртсөн хүний тоо", "Үүнээс эмэгтэй"),
    (None, "Хурц хордлогын хэлбэр", None),
    (11, "Хөнгөн", _where("facc_type", 3)),
    (12, "Дунд", _where("facc_type", 4)),
    (13, "Хүнд", _where("facc_type", 2)),
    (14, "Хүний амь үрэгдсэн", _where("facc_type", 1)),
    (None, "Хурц хордлогын шалтгаан", None),
    (15, "Угаарын хий", _where("facc_reason", 1)),
    (16, "Органик уусгагч", _where("facc_reason", 2)),
    (17, "Пестицид", _where("facc_reason", 3)),
    (18, "Нефтийн бүтээгдэхүүн", _where("facc_reason", 4)),
    (19, "Аммиак", _where("facc_reason", 5)),
    (20, "Хүчил, шүлт", _where("facc_reason", 6)),
    (21, "Хүнд металлын нэгдэл", _where("facc_reason", 7)),
    (22, "Цацраг идэвхит бодис", _where("facc_reason", 8)),
    (23, "Бусад химийн бодис", _where("facc_reason", 9)),
    (24, "Машин тоног төхөөрөмжийн гэмтэл", _where("facc_reason", 10)),
    (25, "Тоног төхөөрөмжийн битүүмжлэл алдагдсан", _where("facc_reason", 11)),
    (26, "Технологийн процесс зөрчсөн", _where("facc_reason", 12)),
    (27, "Аюулгүй ажиллах арга барилд хангалтгүй сурсан", _where("facc_reason", 13)),
    (28, "Ажлын хувцас хамгаалах хэрэгсэлгүй ажилласан", _where("facc_reason", 14)),
    (29, "Онцгой ур чадвар шаардсан ажилд мэргэжлийн хүн ажиллуулаагүй", _where("facc_reason", 15)),
    (30, "Бусад", _where("facc_reason", 16)),
    *_tail(31),
]


def _context(user: User, f: Filters, kind: str) -> Context:
    start, end = period_of(f)
    rows = list(
        FactoryAccidentRow.objects.select_related("employee")
        .filter(
            kind=kind,
            accident_date__gte=start,
            accident_date__lt=end + timedelta(days=1),
            employee_id__in=access.visible_employees(user).values("pk"),
        )
        .order_by("id")
    )
    working = survey_common.people(user, Filters(state="working", branch=f.branch))
    return Context(
        rows=rows,
        branch=f.branch,
        working=len(working),
        women=sum(1 for p in working if p.row.employee.gender == FEMALE),
        org_type=InfoRow.objects.values_list("orgtype_code", flat=True).first(),
    )


def build_lines(user: User, f: Filters, kind: str, lines: list[Line]) -> list[StatLine]:
    """The report lines for the period and branch; `kind` is `accident` or `toxic`. One query for the accident rows."""
    ctx = _context(user, f, kind)
    return [
        StatLine(id=i, number=number, label=label, value=counter(ctx) if counter is not None else None)
        for i, (number, label, counter) in enumerate(lines, start=1)
    ]


COLUMNS: tuple[Column, ...] = (
    Column(key="label", label="Үзүүлэлт", value=lambda x: x.label),
    Column(key="number", label="Мөр", value=lambda x: x.number, numeric=True),
    Column(key="value", label="Утга", value=lambda x: x.value, numeric=True),
)


def _note(f: Filters) -> str:
    """The grey line: where the rows come from."""
    return "Осол, хордлогын бүртгэлийг хуучин програмаас харуулна; Info HR-д оруулах дэлгэц байхгүй."


def _report(key: str, title: str, kind: str, lines: list[Line]) -> Report:
    return Report(
        key=key,
        title=title,
        filters=("period", "branch"),
        columns=COLUMNS,
        default_columns=tuple(c.key for c in COLUMNS),
        rows=lambda user, f: build_lines(user, f, kind, lines),
        needs=NEEDS_PERSONAL,
        source=FactoryAccidentRow,
        note=_note,
        shows_count=False,
    )


ACCIDENTS = _report("accidents", "Үйлдвэрийн ослын тайлан", "accident", ACCIDENT_LINES)
POISONING = _report("poisoning", "Хурц хордлогын тайлан", "toxic", POISONING_LINES)

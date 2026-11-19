"""The order register's print page: the groups by department and the log label, without a request."""

from dataclasses import dataclass

from employees.models import CompanySettings, Department, OrderType
from employees.services import order_register
from employees.services.order_register_page import FilterOptions, RegisterQuery

NO_DEPARTMENT = "Хэлтэсгүй"


@dataclass
class PrintGroup:
    department: str
    rows: list[order_register.RegisterRow]


def build_groups(rows: list[order_register.RegisterRow]) -> list[PrintGroup]:
    """The rows by date (no date last), grouped by department; «Хэлтэсгүй» goes last."""
    buckets: dict[str, list[order_register.RegisterRow]] = {}
    for row in sorted(rows, key=lambda r: (r.date is None, r.date)):
        buckets.setdefault(row.department or NO_DEPARTMENT, []).append(row)
    return [
        PrintGroup(department=name, rows=group)
        for name, group in sorted(buckets.items(), key=lambda item: (item[0] == NO_DEPARTMENT, item[0]))
    ]


def register_label(query: RegisterQuery, options: FilterOptions) -> str:
    """The register's filters as one readable line for the system log. The search text is not written, only that a
    search was made: it is typed by the user and may hold a person's name."""
    parts: list[str] = []
    if query.year:
        parts.append(f"Он: {query.year}")
    if query.order_type is not None:
        parts.append(f"Тушаалын төрөл: {OrderType(query.order_type).label}")
    if query.department is not None:
        name = Department.objects.filter(pk=query.department).values_list("name", flat=True).first()
        parts.append(f"Хэлтэс: {name or '—'}")
    if query.state:
        parts.append(f"Төлөв: {dict(options.states).get(query.state, '—')}")
    if query.q:
        parts.append("Хайлт ашигласан")
    return "; ".join(parts)


def company_name() -> str:
    return CompanySettings.get().name

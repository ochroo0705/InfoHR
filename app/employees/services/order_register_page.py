"""The order register's filters and filter options, without a request: the Django page and the API share them."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from config.params import id_param

from employees.models import Department, OrderState, OrderType
from employees.services import order_register


@dataclass(frozen=True)
class RegisterQuery:
    year: int | None
    order_type: int | None
    department: int | None
    state: str
    q: str
    sort: str


@dataclass
class FilterOptions:
    years: list[int]
    types: list[tuple[int, str]]
    states: list[tuple[str, str]]
    departments: list[tuple[int, str]]


def parse_query(get: Mapping[str, str]) -> RegisterQuery:
    """The register's filters from the query string. Bad values are ignored, never an error."""
    state = get.get("state", "")
    valid_states = {s.value for s in OrderState} | {order_register.LEGACY}
    state = state if state in valid_states else ""
    year = id_param(get.get("year"))
    if year is not None and not 1 <= year <= 9999:
        year = None
    order_type = id_param(get.get("order_type"))
    if order_type is not None and order_type not in OrderType.values:
        order_type = None
    department = id_param(get.get("department"))
    q = get.get("q", "").strip()[:100]
    sort = order_register.clean_sort(get.get("sort", order_register.DEFAULT_SORT))
    return RegisterQuery(
        year=year,
        order_type=order_type,
        department=department,
        state=state,
        q=q,
        sort=sort,
    )


def filter_options(today: date) -> FilterOptions:
    """The choices of the register's filter boxes. The state box has no «Дугаар оруулаагүй» choice: every new
    order is numbered (D-083), and the old MACS rows are offered as one choice at the end."""
    states = [(k, v) for k, v in OrderState.choices if k != OrderState.PENDING]
    return FilterOptions(
        years=list(range(today.year, today.year - 12, -1)),
        types=list(OrderType.choices),
        states=[*states, (order_register.LEGACY, "MACS")],
        departments=[
            (pk, name or "")  # Department.name is nullable: a NULL name shows as an empty label, never as "None"
            for pk, name in Department.objects.exclude(ext__active=False).values_list("pk", "name")
        ],
    )


def query_string(query: RegisterQuery) -> str:
    """The non-empty filters as a query string (the print link and the API share it)."""
    fields = {
        "q": query.q,
        "sort": query.sort,
        "year": query.year,
        "order_type": query.order_type,
        "department": query.department,
        "state": query.state,
    }
    return urlencode([(name, value) for name, value in fields.items() if value is not None and value != ""])

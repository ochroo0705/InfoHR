"""The balances page's rules: which people a batch holds, their current period and the date their right starts.

The Django view and the API both call this module. Rules only; drawing is the caller's job. The caller passes the date:
nothing here reads the clock.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from employees import access as employee_access
from employees import listing
from employees.models import Employee

from leave.services import entitlement, ledger
from leave.services.ledger import Period


@dataclass(frozen=True)
class BalanceLine:
    employee: Employee
    period: Period | None  # the period that holds `day`, or None
    waiting: date | None  # the date the right starts, only while `day` is before it


def balance_batch(user: User, offset: int, size: int, day: date) -> tuple[list[BalanceLine], bool]:
    """One batch of the balances page (visible, still-working people in name order) and whether more people follow."""
    people = listing.still_working(employee_access.visible_employees(user), day).order_by(
        "family_name", "given_name", "pk"
    )
    # The database picks the batch; grants and leaves are then read once for its people, not once per person.
    chunk = list(people[offset : offset + size + 1])
    staying = chunk[:size]
    periods = ledger.periods_many(staying, day)
    eligible_from = entitlement.eligible_froms(staying)  # the right to take leave starts after the waiting months
    lines = []
    for e in staying:
        found, _ = periods[e.pk]
        eligible = eligible_from[e.pk]
        waiting = eligible if eligible is not None and day < eligible else None
        lines.append(BalanceLine(e, next((p for p in found if p.current), None), waiting))
    return lines, len(chunk) > size

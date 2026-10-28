"""F1 «Зээл олгосон тайлан»: the loans given in a period, from the production `hr_loan` table, with the reason from
`loan_refs`. Each row is paired with its person's listing row for today (personal_lists.with_rows). A loan with no
date cannot sit in a period, so it is left out. Loans are money, so the report needs the salary right as well as the
employee list (as A10); HR is refused, the Accountant opens it.
"""

from datetime import timedelta

from accounts.models import User
from django.utils import timezone
from macs.models import LoanRow

from reports.filters import Filters, period_of
from reports.personal_lists import ListRow, department, detail_url, full_name, or_none, people, with_rows
from reports.types import Column, Report


def _loan_rows(user: User, f: Filters) -> list[ListRow]:
    """F1: the loans dated in the period, of the people the user may see, sorted by date then name."""
    start, end = period_of(f)
    items = LoanRow.objects.select_related("loan_ref").filter(
        employee__in=people(user),
        get_date__gte=start,
        get_date__lt=end + timedelta(days=1),
    )
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.get_date, full_name(r)))


def _reason(r: ListRow) -> str | None:
    """The loan's reason from the reference table; None when the loan names none."""
    return or_none(r.item.loan_ref.description) if r.item.loan_ref_id is not None else None


def _note(f: Filters) -> str:
    """The grey line: the loans are entered in the old program, not in Info HR."""
    return "Зээлийн бүртгэлийг хуучин програмаас харуулна; Info HR-д оруулах дэлгэц байхгүй."


COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Зээл авсан огноо", value=lambda r: r.item.get_date),
    Column(key="code", label="Код", value=lambda r: r.row.employee.code),
    Column(key="name", label="Ажилтан", value=full_name, href=detail_url),
    Column(key="department", label="Хэлтэс", value=department),
    Column(key="end_date", label="Зээл дуусах огноо", value=lambda r: r.item.end_date),
    Column(key="amount", label="Зээлийн дүн", value=lambda r: r.item.amount, numeric=True, money=True),
    Column(
        key="per_month",
        label="Сард төлөх төлөлт",
        value=lambda r: r.item.pay_permonth,
        numeric=True,
        money=True,
    ),
    Column(key="reason", label="Зээлийн шалтгаан", value=_reason),
)


LOANS = Report(
    key="loans",
    title="Зээл олгосон тайлан",
    filters=("period",),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_loan_rows,
    needs=("macs.view_employees", "macs.view_salary"),
    source=LoanRow,
    group_options=("reason",),
    note=_note,
)

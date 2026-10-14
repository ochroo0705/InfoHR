"""The "needs attention" strip above the employee list."""

from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User

from employees import access
from employees.listing import Row
from employees.models import Employee, SalaryInsurance
from employees.services import setup

PROBATION_DAYS = 14
CONTRACT_DAYS = 30


@dataclass
class Attention:
    employee: Employee
    text: str
    kind: str


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def items(user: User, rows: list[Row], today: date) -> list[Attention]:
    can_manage = access.can_manage(user)
    can_salary = access.can_view_salary(user)
    if not (can_manage or can_salary):
        return []
    rows = [r for r in rows if r.state != "left"]
    with_account: set[int] = set()
    if can_salary:
        with_account = set(
            SalaryInsurance.objects.filter(employee__in=[r.employee for r in rows])
            .exclude(account_no="")
            .values_list("employee_id", flat=True)
        )
    out: list[Attention] = []
    for r in rows:
        e = r.employee
        pe = e.probation_end
        if pe is not None and today <= pe <= today + timedelta(days=PROBATION_DAYS):
            out.append(Attention(e, f"Туршилтын хугацаа {_fmt(pe)}-нд дуусна", "probation"))
        ce = r.job.contract_end if r.job else None
        if ce is not None:
            if today <= ce <= today + timedelta(days=CONTRACT_DAYS):
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дуусна", "contract"))
            elif ce < today and r.state == "active":
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дууссан", "contract"))
        if can_manage and e.setup_required and not setup.complete_for(e, user):
            out.append(Attention(e, "Бүрдүүлэлт дутуу", "setup"))
        if access.can_view_personal(user, e) and not (e.emergency_name and e.emergency_phone):
            out.append(Attention(e, "Яаралтай үед холбогдох хүн бүртгээгүй", "emergency"))
        if can_salary and e.pk not in with_account:
            out.append(Attention(e, "Банкны мэдээлэл бүртгээгүй", "bank"))
    out.sort(key=lambda a: (a.employee.full_name, a.employee.pk))
    return out

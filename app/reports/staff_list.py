"""The staff list («Ажилчдын жагсаалт»): everyone who has worked here, with the columns the user may see."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone
from employees import access, listing
from employees.models import ext_of
from employees.services.order_register import age_on
from macs.models import AddressRow, BirthPlace, Department, Employee, Position

from reports.filters import Filters
from reports.types import Column, Report

PERSONAL = "macs.view_personal"  # register number, birth date, phones, address and family facts
SALARY = "macs.view_salary"  # salary, insurance and bank

GROUP_NAME = "Нэр, үнэмлэх"
GROUP_JOB = "Ажил"
GROUP_CONTRACT = "Гэрээ"
GROUP_INSURANCE = "Даатгал, банк"
GROUP_CONTACT = "Холбоо барих"
GROUP_PERSONAL = "Хувийн"
GROUP_SALARY = "Цалин"

DEFAULT_COLUMNS = ("code", "name", "department", "position", "first_hire_date", "work_phone")

# Every foreign key the columns read, so one query loads the rows (`ext` is the HR row).
EMPLOYEE_FKS = (
    "branch",
    "department",
    "position",
    "ext",
    "nationality",
    "citizenship",
    "social_origin",
    "marital_status",
    "housing_condition",
    "car_ownership",
    "clothing_size",
    "shoe_size",
    "elected_position",
    "education_level",
    "academic_degree",
    "bank",
    "insured_category",
)


@dataclass(frozen=True)
class StaffRow:
    row: listing.Row  # the job and state on the day (listing.row_for)
    address: str  # "" unless the address column is shown
    birthplace: str  # "" unless the birthplace column is shown
    salary: Decimal | None  # today's base salary; read only when the salary column is shown
    as_of: date  # the day the row is read for; ages and years count to it


def _detail_url(s: StaffRow) -> str:
    return reverse("employees:detail", args=[s.row.employee.pk])


def _name(obj: Any) -> str | None:
    """The name of a code-list value (a nationality, a bank…); None when the employee has none."""
    return obj.name if obj is not None else None


def _job_department(s: StaffRow) -> str | None:
    job = s.row.job
    return job.department.name if job is not None and job.department_id is not None else None


def _job_position(s: StaffRow) -> str | None:
    job = s.row.job
    return job.position.name if job is not None and job.position_id is not None else None


def _probation_end(s: StaffRow) -> date | None:
    ext = ext_of(s.row.employee)
    return ext.probation_end if ext is not None else None


COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda s: s.row.employee.code, group=GROUP_NAME),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda s: s.row.employee.full_name,
        group=GROUP_NAME,
        href=_detail_url,
    ),
    Column(
        key="clan_name", label="Ургийн овог", value=lambda s: s.row.employee.clan_name, group=GROUP_NAME, needs=PERSONAL
    ),
    Column(
        key="register_no",
        label="Регистрийн дугаар",
        value=lambda s: s.row.employee.register_no,
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="passport_no",
        label="Иргэний үнэмлэх / паспорт",
        value=lambda s: s.row.employee.passport_no,
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="birth_date",
        label="Төрсөн огноо",
        value=lambda s: s.row.employee.birth_date,
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="age",
        label="Нас",
        value=lambda s: age_on(s.row.employee.birth_date, s.as_of),
        group=GROUP_NAME,
        needs=PERSONAL,
        numeric=True,
    ),
    Column(
        key="gender",
        label="Хүйс",
        value=lambda s: s.row.employee.get_gender_display(),
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="nationality",
        label="Үндэс угсаа",
        value=lambda s: _name(s.row.employee.nationality),
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="citizenship",
        label="Иргэншил",
        value=lambda s: _name(s.row.employee.citizenship),
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(key="birthplace", label="Төрсөн газар", value=lambda s: s.birthplace, group=GROUP_NAME, needs=PERSONAL),
    Column(
        key="social_origin",
        label="Нийгмийн гарал",
        value=lambda s: _name(s.row.employee.social_origin),
        group=GROUP_NAME,
        needs=PERSONAL,
    ),
    Column(
        key="state",
        label="Төлөв",
        value=lambda s: listing.STATE_LABELS.get(s.row.state, ""),
        group=GROUP_JOB,
    ),
    Column(key="branch", label="Салбар", value=lambda s: _name(s.row.employee.branch), group=GROUP_JOB),
    Column(key="department", label="Хэлтэс", value=_job_department, group=GROUP_JOB),
    Column(key="position", label="Албан тушаал", value=_job_position, group=GROUP_JOB),
    Column(
        key="first_hire_date",
        label="Ажилд орсон",
        value=lambda s: s.row.employee.first_hire_date,
        group=GROUP_JOB,
    ),
    Column(
        key="years_worked",
        label="Ажилласан жил",
        value=lambda s: age_on(s.row.employee.first_hire_date, s.as_of),
        group=GROUP_JOB,
        numeric=True,
    ),
    Column(
        key="work_conditions",
        label="Ажлын нөхцөл",
        value=lambda s: s.row.employee.get_work_conditions_display(),
        group=GROUP_JOB,
    ),
    Column(
        key="elected_position",
        label="Сонгуульт ажил",
        value=lambda s: _name(s.row.employee.elected_position),
        group=GROUP_JOB,
        needs=PERSONAL,
    ),
    Column(
        key="contract_no",
        label="Гэрээний дугаар",
        value=lambda s: s.row.job.contract_no if s.row.job is not None else None,
        group=GROUP_CONTRACT,
    ),
    Column(
        key="contract_start",
        label="Гэрээ байгуулсан",
        value=lambda s: s.row.job.contract_start if s.row.job is not None else None,
        group=GROUP_CONTRACT,
    ),
    Column(
        key="contract_end",
        label="Гэрээ дуусах",
        value=lambda s: s.row.job.contract_end if s.row.job is not None else None,
        group=GROUP_CONTRACT,
    ),
    Column(key="probation_end", label="Туршилт дуусах", value=_probation_end, group=GROUP_CONTRACT),
    Column(
        key="insured_category",
        label="Даатгуулагчийн төрөл",
        value=lambda s: _name(s.row.employee.insured_category),
        group=GROUP_INSURANCE,
        needs=SALARY,
    ),
    Column(
        key="social_insurance_no",
        label="НДД-ийн дугаар",
        value=lambda s: s.row.employee.social_insurance_no,
        group=GROUP_INSURANCE,
        needs=SALARY,
    ),
    Column(
        key="health_insurance_no",
        label="ЭМДД-ийн дугаар",
        value=lambda s: s.row.employee.health_insurance_no,
        group=GROUP_INSURANCE,
        needs=SALARY,
    ),
    Column(key="bank", label="Банк", value=lambda s: _name(s.row.employee.bank), group=GROUP_INSURANCE, needs=SALARY),
    Column(
        key="account_no",
        label="Дансны дугаар",
        value=lambda s: s.row.employee.account_no,
        group=GROUP_INSURANCE,
        needs=SALARY,
    ),
    Column(key="work_phone", label="Ажлын утас", value=lambda s: s.row.employee.work_phone, group=GROUP_CONTACT),
    Column(
        key="private_phone",
        label="Хувийн утас",
        value=lambda s: s.row.employee.private_phone,
        group=GROUP_CONTACT,
        needs=PERSONAL,
    ),
    Column(key="email", label="И-мэйл", value=lambda s: s.row.employee.email, group=GROUP_CONTACT),
    Column(key="address", label="Гэрийн хаяг", value=lambda s: s.address, group=GROUP_CONTACT, needs=PERSONAL),
    Column(
        key="education_level",
        label="Боловсрол",
        value=lambda s: _name(s.row.employee.education_level),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="academic_degree",
        label="Эрдмийн зэрэг",
        value=lambda s: _name(s.row.employee.academic_degree),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="marital_status",
        label="Гэрлэлтийн байдал",
        value=lambda s: _name(s.row.employee.marital_status),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="housing_condition",
        label="Орон байрны нөхцөл",
        value=lambda s: _name(s.row.employee.housing_condition),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="car_ownership",
        label="Автомашин эзэмшил",
        value=lambda s: _name(s.row.employee.car_ownership),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="clothing_size",
        label="Хувцасны хэмжээ",
        value=lambda s: _name(s.row.employee.clothing_size),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="shoe_size",
        label="Гутлын хэмжээ",
        value=lambda s: _name(s.row.employee.shoe_size),
        group=GROUP_PERSONAL,
        needs=PERSONAL,
    ),
    Column(
        key="salary",
        label="Үндсэн цалин",
        value=lambda s: s.salary,
        group=GROUP_SALARY,
        needs=SALARY,
        numeric=True,
        money=True,
    ),
)


def _place(parts: Iterable[str | None]) -> str:
    """Address parts joined with commas; empty parts are skipped."""
    return ", ".join(part for part in parts if part)


def address_text(address: Any) -> str:
    """An address row as «аймаг/хот, сум/дүүрэг, хаяг»."""
    return _place(
        [
            address.city.name if address.city_id else None,
            address.district.name if address.district_id else None,
            address.street,
        ]
    )


def _birthplace_text(birthplace: Any) -> str:
    """A birth place as «аймаг/хот, сум/дүүрэг, тайлбар»."""
    return _place(
        [
            birthplace.city.name if birthplace.city_id else None,
            birthplace.district.name if birthplace.district_id else None,
            birthplace.description,
        ]
    )


def first_per_employee(qs: QuerySet[Any]) -> dict[int, Any]:
    """The first row of each employee (lowest id), so an employee with two rows shows one."""
    first: dict[int, Any] = {}
    for item in qs.order_by("id"):
        first.setdefault(item.employee_id, item)
    return first


def _kept(r: listing.Row, f: Filters, day: date, today: date) -> bool:
    """Whether a row passes the state, department, position, branch and gender filters."""
    if f.state == "working" and (r.state == "left" or (r.state == "upcoming" and day != today)):
        return False  # a person hired after `day` is not on staff on that day
    if day != today and r.legacy and r.employee.first_hire_date is not None and r.employee.first_hire_date > day:
        return False  # no Info HR job history: the first hire date is the only record of when they started
    if f.state == "left" and r.state != "left":
        return False
    job = r.job
    if f.department is not None and (job is None or job.department_id != f.department):
        return False
    if f.position is not None and (job is None or job.position_id != f.position):
        return False
    if f.branch is not None and r.employee.branch_id != f.branch:
        return False
    return not f.gender or r.employee.gender == f.gender


def load_job_names(jobs: Sequence[Any]) -> None:
    """Sets the department and position objects on each job whose name is not loaded yet. A legacy job
    (listing.legacy_job) holds only the ids, so without this each cell would load its own department and position."""
    dept_ids = {j.department_id for j in jobs if j.department_id is not None and not type(j).department.is_cached(j)}
    pos_ids = {j.position_id for j in jobs if j.position_id is not None and not type(j).position.is_cached(j)}
    depts = Department.objects.in_bulk(dept_ids)
    poss = Position.objects.in_bulk(pos_ids)
    for job in jobs:
        if job.department_id in depts and not type(job).department.is_cached(job):
            job.department = depts[job.department_id]
        if job.position_id in poss and not type(job).position.is_cached(job):
            job.position = poss[job.position_id]


def kept_rows(user: User, f: Filters, select_related: tuple[str, ...] = EMPLOYEE_FKS) -> tuple[list[listing.Row], date]:
    """The job rows of the people the user may see that pass the filters, and the day they are read on (today when
    none). Shared by the staff list and the survey reports, so both count the same people."""
    today = timezone.localdate()
    day = f.as_of or today
    if not user.has_perm(PERSONAL):
        f = replace(f, gender="")  # the gender filter reads a personal field
    shown = set(f.columns or DEFAULT_COLUMNS)
    wants_salary = "salary" in shown and user.has_perm(SALARY)
    staff = access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED).select_related(*select_related)
    if wants_salary:
        staff = staff.prefetch_related("salary_records")
    kept = [r for r in listing.employee_rows(staff, day) if _kept(r, f, day, today)]
    return kept, day


def rows(user: User, f: Filters) -> list[StaffRow]:
    """The staff rows for these filters, read on the chosen day (today when none). Only people the user may see."""
    kept, day = kept_rows(user, f)
    today = timezone.localdate()
    shown = set(f.columns or DEFAULT_COLUMNS)
    wants_address = "address" in shown and user.has_perm(PERSONAL)
    wants_salary = "salary" in shown and user.has_perm(SALARY)
    ids = [r.employee.pk for r in kept]

    addresses: dict[int, Any] = {}
    if wants_address:
        addresses = first_per_employee(
            AddressRow.objects.filter(employee_id__in=ids).select_related("city", "district")
        )
    birthplaces: dict[int, Any] = {}
    if "birthplace" in shown:
        birthplaces = first_per_employee(
            BirthPlace.objects.filter(employee_id__in=ids).select_related("city", "district")
        )

    result: list[StaffRow] = []
    for r in kept:
        emp = r.employee
        address = addresses.get(emp.pk)
        birthplace = birthplaces.get(emp.pk)
        salary = listing.current_salary(emp, today) if wants_salary else None
        result.append(
            StaffRow(
                row=r,
                address=address_text(address) if address is not None else "",
                birthplace=_birthplace_text(birthplace) if birthplace is not None else "",
                salary=salary.base_salary if salary is not None else None,
                as_of=day,
            )
        )
    return result


def _note(f: Filters) -> str:
    """The grey line on another day: state, department and position are that day's, the other columns today's."""
    if f.as_of is None or f.as_of == timezone.localdate():
        return ""
    return (
        f"{f.as_of.isoformat()} өдрийн байдлаар: төлөв, хэлтэс, албан тушаал, гэрээ тухайн өдрийнх "
        "(Info HR-д ажлын түүхгүй ажилтных өнөөдрийнх); нас, ажилласан жил тухайн өдрөөр; бусад багана өнөөдрийнх."
    )


REPORT = Report(
    key="staff-list",
    title="Ажилчдын жагсаалт",
    filters=("state", "as_of", "branch", "department", "position", "gender"),
    filter_needs={"gender": PERSONAL},
    columns=COLUMNS,
    default_columns=DEFAULT_COLUMNS,
    rows=rows,
    needs=("macs.view_employees",),
    source=Employee,
    group_options=("department", "branch", "position"),
    picks_columns=True,
    saved_views=True,
    note=_note,
)

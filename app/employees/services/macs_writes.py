"""The only code that writes production MACS rows (spec §2). It applies what the old
database triggers and the old desktop screen did (docs/migration/firebird-rules-audit.md)."""

from datetime import date, timedelta
from typing import Any, cast

from accounts.models import User
from django.db import IntegrityError, connection, transaction
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr
from lists.models import DEATH, MeaningfulEntry
from lists.usage import usage_count
from macs.models import Command, EmployeeHistory, Movement

from employees.models import (
    Department,
    DepartmentExt,
    Employee,
    EmployeeExt,
    Event,
    EventProdRow,
    EventType,
    HrOrder,
    JobRecord,
    JobStatus,
    OrderState,
    Position,
    PositionExt,
)

# emptype -> (status, contract_emp, wagetest_emp): old triggers TR_EMPLOYEEID / EMPLOYEE_BU0.
EMPTYPE_FLAGS: dict[int, tuple[str, str, int | None]] = {
    1: ("active", "no", None),
    3: ("inactive", "no", None),
    5: ("active", "yes", None),
    6: ("elder", "no", None),
    9: ("active", "no", 2),
}


def next_code() -> str:
    """Next E-number. Compares the digits as numbers, so E10000 follows E9999."""
    top = (
        Employee.objects.filter(code__regex=r"^E\d{4,}$")
        .annotate(number=Cast(Substr("code", 2), IntegerField()))
        .aggregate(top=Max("number"))["top"]
    )
    return f"E{(top or 0) + 1:04d}"


def emptype_for(job: JobRecord | None, ext: EmployeeExt, today: date) -> int:
    """The production employee type for a job period. It is stored on the job (`job.emptype`), never derived
    from dates. Left: 6 when the termination event was a pension exit, else 3. A job without a stored type (rows
    from before the field existed) keeps what production already holds."""
    if job is None:
        return 3
    if job.status == JobStatus.LEFT:
        event = job.event if job.event_id else None
        return 6 if event is not None and event.pension else 3
    if job.emptype is not None:
        return int(job.emptype)
    held = job.employee.emptype
    return held if held in EMPTYPE_FLAGS and held not in (3, 6) else 1


# MACS emptype values HR does not model: firebird-rules-audit.md. Working: 8 hired labour.
# Not working: 2 external reserve, 4 applicant (HR shows them as left; 3 is HR's own "left").
UNMODELLED_EMPTYPES = {8}
UNMODELLED_NOT_WORKING = {2, 4}


def keeps_emptype(employee: Employee, job: JobRecord, ext: EmployeeExt) -> bool:
    """Leave emptype/status/contract_emp/wagetest_emp as MACS holds them while HR cannot express the MACS value:
    8 while working; 2/4 while HR still shows the person as left (a rehire makes them active)."""
    if job.status == JobStatus.LEFT:
        return employee.emptype in UNMODELLED_NOT_WORKING
    return employee.emptype in UNMODELLED_EMPTYPES


def _fullname(employee: Employee) -> str:
    """MACS format: surname padded with spaces to 25 characters (RPAD), then ', ' and the given name."""
    return f"{(employee.family_name or '').ljust(25)}, {employee.given_name}"


def _birth_year(employee: Employee) -> int | None:
    return employee.birth_date.year if employee.birth_date else None


def _fill_hire_dates(employee: Employee) -> None:
    """New employees only: each empty hire date takes the other one's value. Never run on update."""
    if employee.first_hire_date is None and employee.contract_start is not None:
        employee.first_hire_date = employee.contract_start
    if employee.contract_start is None and employee.first_hire_date is not None:
        employee.contract_start = employee.first_hire_date


def hr_employment_start(employee: Employee) -> date | None:
    """Start of the current employment as recorded in HR: the latest live rehire event, else the HR hire job's
    start. None for a MACS-only (legacy) employee that has neither."""
    rehire = employee.events.filter(type=EventType.REHIRE, cancelled_at__isnull=True).order_by("-effective").first()
    if rehire is not None:
        return rehire.effective
    hire = employee.job_records.filter(change_type="hire").order_by("period").first()
    if hire is not None:
        return cast(date, hire.period.lower)
    return None


def current_employment_start(employee: Employee) -> date | None:
    """Start of the current employment. Order: latest live rehire event, HR hire job start, MACS contract_start
    (current contract), then first_hire_date ("Анх ажилд орсон"): the very first hire, which can be years earlier,
    so it is the last resort only."""
    start = hr_employment_start(employee)
    if start is not None:
        return start
    if employee.contract_start is not None:
        return cast(date, employee.contract_start)
    return cast(date | None, employee.first_hire_date)


def probation_months(start: date | None, probation_end: date | None) -> int | None:
    """Whole months of probation (production test_month): from the employee's start to the end of
    probation, rounded to the nearest month, at least 1. None when there is no probation end."""
    if probation_end is None or start is None:
        return None
    return max(1, round((probation_end - start).days / 30.4375))


def _set_emptype(employee: Employee, emptype: int) -> None:
    employee.emptype = emptype
    employee.status, employee.contract_flag, employee.wagetest = EMPTYPE_FLAGS[emptype]


@transaction.atomic
def create_employee(values: dict[str, Any], ext_values: dict[str, Any], *, code: str, by: User) -> Employee:
    employee = Employee(**values)
    employee.code = code
    employee.hr_flag = "yes"
    employee.sector_years = 0
    _set_emptype(employee, 1)
    employee.fullname = _fullname(employee)
    employee.birth_year = _birth_year(employee)
    _fill_hire_dates(employee)
    employee.save(force_insert=True)
    employee.loginpass = str(employee.pk)
    employee.save(update_fields=["loginpass"])
    EmployeeExt.objects.create(employee=employee, created_by=by, updated_by=by, **ext_values)
    create_customer_row(employee)
    return employee


# The ERP customer row of an employee (D-024). Raw SQL: the ERP table has ~60 columns whose NOT NULL ones
# take database defaults. HR inserts and updates it here only; it never deletes it.
CUSTOMER_DESCRIPTION_MAX = 80
CUSTOMER_ADDRESS_MAX = 90


def create_customer_row(employee: Employee) -> int | None:
    """Old trigger TR_EMPCUST: an HR-created active employee gets one ERP customer row (code = empno, Q-1).
    The description (unique in the ERP) is "Given.F"; only when that is taken, " <empno>" is added, then
    " <empno>-2", "-3"... (rows typed in the ERP can hold those too; each try runs in a savepoint, so a row the ERP
    adds meanwhile does not fail the hire). Returns the new cust_id, or None when skipped (not HR/active, or the
    employee already has a row)."""
    if employee.hr_flag != "yes" or employee.status != "active":
        return None
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM customer WHERE employee_ident = %s AND employee = 'yes'", [employee.pk])
        if c.fetchone():
            return None
    initial = (employee.family_name or "").strip()[:1]
    base = f"{(employee.given_name or '').strip()}.{initial}"
    tag = employee.code or str(employee.pk)
    for n in range(1, 100):
        suffix = "" if n == 1 else f" {tag}" if n == 2 else f" {tag}-{n - 1}"
        description = base[: CUSTOMER_DESCRIPTION_MAX - len(suffix)] + suffix
        try:
            with transaction.atomic(), connection.cursor() as c:
                c.execute(
                    "INSERT INTO customer (employee_ident, description, code, passport, register, employee)"
                    " VALUES (%s, %s, %s, %s, %s, 'yes') RETURNING cust_id",
                    [employee.pk, description, employee.code, employee.passport_no, employee.register_no],
                )
                return int(c.fetchone()[0])
        except IntegrityError as exc:
            if "cust_dscx" not in str(exc):
                raise
    raise IntegrityError(f"no free ERP customer description for {base!r}")


def copy_address_to_customer(employee: Employee, street: str | None) -> None:
    """Old trigger ADDRESS_BI: a saved street is copied to the employee's ERP customer row (cut to 90).
    Also run on address updates (D-024). An empty street or a missing row changes nothing."""
    if not street:
        return
    with connection.cursor() as c:
        c.execute(
            "UPDATE customer SET address = %s WHERE employee_ident = %s AND employee = 'yes'",
            [street[:CUSTOMER_ADDRESS_MAX], employee.pk],
        )


@transaction.atomic
def update_employee_columns(employee: Employee, values: dict[str, Any]) -> None:
    for name, value in values.items():
        setattr(employee, name, value)
    # Derived columns are rewritten only when their source changed, so an unrelated edit leaves MACS values alone.
    derived: set[str] = set()
    if values.keys() & {"family_name", "given_name"}:
        employee.fullname = _fullname(employee)
        derived.add("fullname")
    if "birth_date" in values:
        employee.birth_year = _birth_year(employee)
        derived.add("birth_year")
    fields = sorted({*values, *derived})
    if fields:
        employee.save(update_fields=fields)


LEAVE_TYPE_CODES = {"unpaid": 1, "childcare": 2, "maternity": 3}


def _flags(employee: Employee, job: JobRecord, today: date) -> dict[str, Any]:
    """Production leave/leaving flags for the job valid today (spec §6)."""
    flags: dict[str, Any] = {"taken_leave": 0, "leave_type": None, "fired_reason_id": None, "died": "no"}
    live = employee.events.filter(cancelled_at__isnull=True, effective__lte=today)
    if job.status == JobStatus.LONG_LEAVE:
        start = live.filter(type=EventType.LEAVE_START).order_by("-effective", "-id").first()
        flags["taken_leave"] = 1
        flags["leave_type"] = LEAVE_TYPE_CODES.get(start.reason) if start else employee.leave_type
    elif job.status == JobStatus.LEFT:
        term = live.filter(type=EventType.TERMINATION).order_by("-effective", "-id").first()
        if term is None:  # legacy leaver without an event: keep what production already holds
            flags["fired_reason_id"] = employee.fired_reason_id
            flags["died"] = employee.died
        else:
            reason_id = term.fired_reason_id
            flags["fired_reason_id"] = reason_id
            flags["died"] = "yes" if reason_id is not None and reason_id == MeaningfulEntry.get(DEATH) else "no"
    return flags


@transaction.atomic
def sync_current(employee: Employee, today: date) -> bool:
    """Copy the job and salary valid today onto the production row (spec §6).
    Saves and bumps changed_date only when a copied value really changed; returns whether it did."""
    # Local import: history imports this module, so a top-level import would be circular.
    from employees.services.history import job_on, salary_on

    # The same job row drives both the copied fields and emptype (a future-only hire is not "inactive").
    job = job_on(employee, today) or employee.job_records.order_by("-period").first()
    salary = salary_on(employee, today)
    ext = EmployeeExt.objects.get_or_create(employee=employee)[0]
    copied: dict[str, Any] = {}
    if job is not None:
        copied.update(
            department_id=job.department_id,
            position_id=job.position_id,
            contract_no=job.contract_no or None,
            contract_start=job.contract_start,
            contract_end=job.contract_end,
        )
    # Legacy rows (production row + HR ext, no HR job/salary history yet) keep their values: no job means
    # no emptype/status change, no salary means no salary change.
    if job is not None:
        if not keeps_emptype(employee, job, ext):
            emptype = emptype_for(job, ext, today)
            copied["emptype"] = emptype
            copied["status"], copied["contract_flag"], copied["wagetest"] = EMPTYPE_FLAGS[emptype]
        copied.update(_flags(employee, job, today))
    if salary is not None:
        copied["salary"] = salary.base_salary
    changed = [name for name, value in copied.items() if getattr(employee, name) != value]
    if not changed:
        return False
    for name, value in copied.items():
        setattr(employee, name, value)
    employee.changed_date = today
    employee.save(update_fields=[*changed, "changed_date"])
    return True


def record_movement(
    employee: Employee,
    kind: str,
    day: date,
    *,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
) -> int:
    """Write one production movement row and return its id. `old`/`new` carry department_id, position_id,
    emptype; without `new` the employee's live row is the new state (hire)."""
    if new is None:
        new = {
            "department_id": employee.department_id,
            "position_id": employee.position_id,
            "emptype": employee.emptype,
        }
    old = old or {}
    movement = Movement.objects.create(
        employee=employee,
        kind=kind,
        date=day,
        old_department_id_value=old.get("department_id"),
        old_position_id_value=old.get("position_id"),
        old_emptype=old.get("emptype"),
        new_department_id_value=new.get("department_id"),
        new_position_id_value=new.get("position_id"),
        new_emptype=new.get("emptype"),
    )
    return int(movement.pk)


def snapshot_history(
    employee: Employee, as_of: date | None = None, *, fired_reason_id: int | None = None, terminating: bool = False
) -> int:
    """Write an employee_history row and return its id. With `as_of` the job-dependent columns come from the
    HR job/salary valid that day (the live row where there is none: legacy employees)."""
    # Local import: history imports this module, so a top-level import would be circular.
    from employees.services.history import job_on, salary_on

    state: dict[str, Any] = {
        "salary": employee.salary,
        "status": employee.status,
        "contract_flag": employee.contract_flag,
        "wagetest": employee.wagetest,
        "emptype": employee.emptype,
        "department_id_value": employee.department_id,
        "position_id_value": employee.position_id,
        "contract_start": employee.contract_start,
        "contract_end": employee.contract_end,
        "changed_date": employee.changed_date,
    }
    extra: dict[str, Any] = {}
    if as_of is not None:
        state["changed_date"] = as_of
        job = job_on(employee, as_of)
        if job is not None:
            ext = EmployeeExt.objects.get_or_create(employee=employee)[0]
            state.update(
                department_id_value=job.department_id,
                position_id_value=job.position_id,
                contract_start=job.contract_start,
                contract_end=job.contract_end,
            )
            if not keeps_emptype(employee, job, ext):
                emptype = emptype_for(job, ext, as_of)
                state["emptype"] = emptype
                state["status"], state["contract_flag"], state["wagetest"] = EMPTYPE_FLAGS[emptype]
        salary = salary_on(employee, as_of)
        if salary is not None:
            state["salary"] = salary.base_salary
        if terminating or fired_reason_id is not None:
            extra = {"fired_date": as_of, "fired_reason_id_value": fired_reason_id}
    with connection.cursor() as c:
        c.execute("select nextval('gen_employee_history_id')")
        history_id = c.fetchone()[0]
    EmployeeHistory.objects.create(
        id=history_id,
        employee_id_value=employee.pk,
        branch_id_value=employee.branch_id,
        given_name=employee.given_name,
        family_name=employee.family_name,
        fullname=employee.fullname,
        first_hire_date=employee.first_hire_date,
        work_conditions=employee.work_conditions,
        register_no=employee.register_no,
        gender=employee.gender,
        birth_date=employee.birth_date,
        is_default=0,
        **state,
        **extra,
    )
    return int(history_id)


def _state_on(employee: Employee, day: date) -> dict[str, Any] | None:
    # Local import: history imports this module, so a top-level import would be circular.
    from employees.services.history import job_on

    job = job_on(employee, day)
    if job is None:
        return None
    ext = EmployeeExt.objects.get_or_create(employee=employee)[0]
    emptype = employee.emptype if keeps_emptype(employee, job, ext) else emptype_for(job, ext, day)
    return {"department_id": job.department_id, "position_id": job.position_id, "emptype": emptype}


def write_event_rows(event: Event) -> None:
    """Write the production movement (if the event moves someone) and the as-of snapshot, and link them (spec §3)."""
    employee, day = event.employee, event.effective
    new = _state_on(employee, day)
    old = _state_on(employee, day - timedelta(days=1)) or new
    kind: str | None = None
    if event.type == EventType.REHIRE:
        kind = "in"
    elif event.type == EventType.TERMINATION:
        kind = "out"
    elif new is not None and old is not None:
        if new["department_id"] != old["department_id"]:
            kind = "dep"
        elif new["position_id"] != old["position_id"]:
            kind = "occ"
    terminating = event.type == EventType.TERMINATION
    movement_id = record_movement(employee, kind, day, old=old, new=new) if kind and new is not None else None
    history_id = snapshot_history(
        employee,
        day,
        fired_reason_id=event.fired_reason_id if terminating else None,
        terminating=terminating,
    )
    EventProdRow.objects.create(event=event, movement_id=movement_id, history_id=history_id)


def _order_change_date(order: HrOrder) -> date:
    """The effective date of the change an order belongs to (a hire: the hire start)."""
    if order.event is not None:
        return order.event.effective
    hire = order.employee.job_records.filter(change_type="hire").order_by("period").first()
    return cast(date, hire.period.lower) if hire is not None else date.min


@transaction.atomic
def point_employee_to_latest_order(employee: Employee) -> None:
    """employee.command_ident / move_type <- the latest registered or signed order, by the change's effective
    date (ties: higher order id); NULL when none is left. Orders without a number or cancelled are ignored."""
    live = employee.hr_orders.filter(state__in=[OrderState.REGISTERED, OrderState.SIGNED], command_id__isnull=False)
    latest = max(live.select_related("event"), key=lambda o: (_order_change_date(o), o.pk), default=None)
    command_id = latest.command_id if latest is not None else None
    move_type = latest.order_type if latest is not None else None
    Employee.objects.filter(pk=employee.pk).update(command_id_value=command_id, move_type=move_type)
    employee.command_id_value, employee.move_type = command_id, move_type


@transaction.atomic
def write_order(order: HrOrder) -> None:
    """Write a registered/signed order to production: the command row (inserted the first time, then updated),
    the change's employee_history row, and the employee pointer. The command row is never deleted."""
    values: dict[str, Any] = {
        "employee_id": order.employee_id,
        "summary": order.summary or None,
        "date": order.date,
        "issued_by": order.issued_by or None,
        "number": order.number,
        "path": None,  # spec §6: the old MACS program reads this as a path on its own share
        "order_type": order.order_type,
    }
    if order.command_id and Command.objects.filter(pk=order.command_id).exists():
        Command.objects.filter(pk=order.command_id).update(**values)
    else:
        command = Command.objects.create(**values)
        order.command_id = int(command.pk)
        HrOrder.objects.filter(pk=order.pk).update(command_id=order.command_id)
    if order.is_hire:
        history_ids = [order.history_id] if order.history_id else []
    else:
        history_ids = (
            [x.history_id for x in order.event.prod_rows.all() if x.history_id] if order.event is not None else []
        )
    EmployeeHistory.objects.filter(pk__in=history_ids).update(
        command_id_value=order.command_id, move_type=order.order_type
    )
    point_employee_to_latest_order(order.employee)


@transaction.atomic
def delete_event_rows(event: Event) -> None:
    """Remove the production rows an event wrote; ids already gone are ignored."""
    links = list(event.prod_rows.all())
    Movement.objects.filter(pk__in=[x.movement_id for x in links if x.movement_id]).delete()
    EmployeeHistory.objects.filter(pk__in=[x.history_id for x in links if x.history_id]).delete()
    event.prod_rows.all().delete()


@transaction.atomic
def save_department(name: str, *, department: Department | None = None) -> Department:
    if department is None:
        department = Department.objects.create(name=name)
        DepartmentExt.objects.create(department=department)
    else:
        department.name = name
        department.save(update_fields=["name"])
    return department


@transaction.atomic
def save_position(name: str, *, position: Position | None = None) -> Position:
    if position is None:
        position = Position.objects.create(name=name)
        PositionExt.objects.create(position=position)
    else:
        position.name = name
        position.save(update_fields=["name"])
    return position


class ListEntryInUse(ValueError):
    """A list entry is still referenced by production or HR rows; it cannot be removed."""

    def __init__(self, count: int) -> None:
        super().__init__(f"{count} ажилтан/бичлэг ашиглаж байгаа тул устгах боломжгүй.")
        self.count = count


# A list entry with its own HR extension row: the extension goes with the entry, so it is not a user of it.
_EXTENSIONS: dict[type[Any], type[Any]] = {Department: DepartmentExt, Position: PositionExt}


def save_list_entry(model: Any, values: dict[str, Any], *, entry: Any | None = None) -> Any:
    """Create or update one row of a production list table (the generic list editor)."""
    if entry is None:
        return model.objects.create(**values)
    for name, value in values.items():
        setattr(entry, name, value)
    entry.save(update_fields=list(values))
    return entry


@transaction.atomic
def delete_list_entry(entry: Any) -> None:
    """Remove a list entry and its HR extension row. Refused while any row still points at it."""
    model: Any = type(entry)
    extension = _EXTENSIONS.get(model)
    skip = [extension._meta.db_table] if extension is not None else []
    count = usage_count(model, entry.pk, exclude_tables=skip)
    if count:
        raise ListEntryInUse(count)
    if extension is not None:
        extension.objects.filter(pk=entry.pk).delete()  # the extension's primary key is the entry's id
    model.objects.filter(pk=entry.pk).delete()


def delete_department(department: Department) -> None:
    """Remove a department and its HR row. Refused while any row still points at it."""
    delete_list_entry(department)


def delete_position(position: Position) -> None:
    """Remove a position and its HR row. Refused while any row still points at it."""
    delete_list_entry(position)


def save_photo(employee: Employee, jpeg: bytes | None) -> None:
    """Replace the employee's photo; None removes it. Stored as raw JPEG bytes (the MACS and old-program format)."""
    from macs.models import EmployeePhoto

    with transaction.atomic():
        EmployeePhoto.objects.filter(employee=employee).delete()
        if jpeg:
            EmployeePhoto.objects.create(employee=employee, data=jpeg)


def replace_photo_bytes(photo_id: int, data: bytes) -> None:
    """Overwrite the bytes of one existing emp_photo row (used by fix_photo_encoding)."""
    from macs.models import EmployeePhoto

    EmployeePhoto.objects.filter(pk=photo_id).update(data=data)


@transaction.atomic
def save_birth_place(employee: Employee, city: Any, district: Any, description: str) -> None:
    """Set the employee's birth place (production birth_place, one row kept per employee); no city removes it."""
    from macs.models import BirthPlace

    rows = BirthPlace.objects.filter(employee=employee).order_by("id")
    place = rows.first()
    if city is None:
        rows.delete()
        return
    values = {"city": city, "district": district, "description": description[:50] or None}
    if place is None:
        BirthPlace.objects.create(employee=employee, **values)
    else:
        rows.filter(pk=place.pk).update(**values)


@transaction.atomic
def reactivate_department(department: Department) -> None:
    """Show an inactive department in the dropdowns again (its HR extension row, as the admin does)."""
    DepartmentExt.objects.update_or_create(department=department, defaults={"active": True})


@transaction.atomic
def reactivate_position(position: Position) -> None:
    """Show an inactive position in the dropdowns again (its HR extension row, as the admin does)."""
    PositionExt.objects.update_or_create(position=position, defaults={"active": True})

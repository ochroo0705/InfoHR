"""The governed objects in the Firebird database: the scope table GOV_SCOPE and the GOV_ views (the list is the
order of view_statements(); the gates that open them are in catalogue.py).

Table and column names come from the models (db_table, db_column) when install runs, so a renamed column is seen
here, not as a silent break. Firebird dialect 1: unquoted upper-case names, 31 characters at most, no schemas.

No access rule is written in SQL. The host fills GOV_SCOPE with the ids the asker may see (employees/access.py). A
view shows only employees whose id is in GOV_SCOPE, so an empty scope gives zero rows.
"""

import re
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Field, Model
from employees.models import ChangeType, Event, EventType, HrOrder, JobRecord, OrderType, SalaryRecord
from leave.models import LeaveRequest
from macs.models import (
    AcademicDegree,
    AwardRow,
    Branch,
    CertificateRow,
    Department,
    EducationLevel,
    EducRow,
    EduType,
    Employee,
    Entitlement,
    FamilyRelation,
    FamilyRow,
    FiredReason,
    LeaveAssign,
    LeaveTypeRow,
    LoanRefRow,
    LoanRow,
    Position,
    PresentRow,
    PresentType,
    ProfessionType,
    QualificationRow,
    QualificationType,
    SpecEduType,
)

SCOPE_TABLE = "GOV_SCOPE"
_PLAIN = re.compile(r"[a-z][a-z0-9_]*")
# English words for the views, one per OrderType member (a missing member fails at import, not in a query).
_ORDER_TYPE_WORDS: dict[OrderType, str] = {
    OrderType.HIRED: "hired",
    OrderType.DEPARTMENT: "department",
    OrderType.POSITION: "position",
    OrderType.FIRED: "fired",
    OrderType.PENSION: "pension",
    OrderType.TYPE_CHANGED: "type_changed",
}
_LEAVE_STATUS_WORDS: dict[int, str] = {
    LeaveAssign.APPROVED: "approved",
    LeaveAssign.CANCELLED: "cancelled",
    LeaveAssign.REJECTED: "rejected",
}
_SCOPE_CREATE = (
    "CREATE GLOBAL TEMPORARY TABLE GOV_SCOPE (EMP_ID INTEGER NOT NULL PRIMARY KEY, WORKING SMALLINT NOT NULL)"
    " ON COMMIT DELETE ROWS"
)
_SCOPE_WORKING_CHECK = (
    "SELECT COUNT(*) FROM RDB$RELATION_FIELDS WHERE TRIM(RDB$RELATION_NAME) = 'GOV_SCOPE'"
    " AND TRIM(RDB$FIELD_NAME) = 'WORKING'"
)
_GOV_VIEW_LIST = (
    "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$VIEW_SOURCE IS NOT NULL"
    " AND TRIM(RDB$RELATION_NAME) STARTING WITH 'GOV_'"
)


def _table(model: type[Model]) -> str:
    name = str(model._meta.db_table)
    if not _PLAIN.fullmatch(name):
        raise ValueError(f"table name is not a plain identifier: {name!r}")
    return name


def _col(model: type[Model], field_name: str) -> str:
    field = model._meta.get_field(field_name)
    if not isinstance(field, Field):
        raise ValueError(f"{model.__name__}.{field_name} is not a column")
    name = str(field.column)
    if not _PLAIN.fullmatch(name):
        raise ValueError(f"column name is not a plain identifier: {name!r}")
    return name


def _case(column: str, words: Mapping[int, str]) -> str:
    """A CASE expression that maps integer codes to words; a code not in `words` gives NULL."""
    arms = " ".join(f"WHEN {int(code)} THEN '{word}'" for code, word in words.items())
    return f"TRIM(CASE {column} {arms} END)"  # TRIM: Firebird pads CASE text to a fixed width


def view_statements() -> list[str]:
    """The CREATE OR ALTER VIEW statements, built from the models. Run after GOV_SCOPE exists."""
    emp, dep, branch, pos = _table(Employee), _table(Department), _table(Branch), _table(Position)
    fam, rel = _table(FamilyRow), _table(FamilyRelation)
    employees = f"""CREATE OR ALTER VIEW GOV_EMPLOYEES (EMP_ID, FIRST_NAME, LAST_NAME, DEPARTMENT_NAME, BRANCH_NAME,
POSITION_NAME, HIRE_DATE, BIRTH_DATE, GENDER, WORKING) AS
SELECT e.{_col(Employee, "id")}, e.{_col(Employee, "given_name")}, e.{_col(Employee, "family_name")},
d.{_col(Department, "name")}, b.{_col(Branch, "name")}, p.{_col(Position, "name")},
e.{_col(Employee, "first_hire_date")}, e.{_col(Employee, "birth_date")}, e.{_col(Employee, "gender")}, w.WORKING
FROM {emp} e
JOIN GOV_SCOPE w ON w.EMP_ID = e.{_col(Employee, "id")}
LEFT JOIN {dep} d ON d.{_col(Department, "id")} = e.{_col(Employee, "department")}
LEFT JOIN {branch} b ON b.{_col(Branch, "id")} = e.{_col(Employee, "branch")}
LEFT JOIN {pos} p ON p.{_col(Position, "id")} = e.{_col(Employee, "position")}"""  # noqa: S608 (names come from the models, checked by _PLAIN)
    children = f"""CREATE OR ALTER VIEW GOV_CHILDREN (CHILD_ID, EMP_ID, CHILD_NAME, CHILD_SURNAME, BIRTH_DATE,
GENDER) AS
SELECT f.{_col(FamilyRow, "id")}, f.{_col(FamilyRow, "employee")}, f.{_col(FamilyRow, "given_name")},
f.{_col(FamilyRow, "surname")}, f.{_col(FamilyRow, "birth_date")},
CASE r.{_col(FamilyRelation, "fm_type")} WHEN 'son' THEN 'M' WHEN 'daughter' THEN 'F' END
FROM {fam} f
JOIN {rel} r ON r.{_col(FamilyRelation, "id")} = f.{_col(FamilyRow, "relation")}
WHERE r.{_col(FamilyRelation, "fm_type")} IN ('son', 'daughter')
AND EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = f.{_col(FamilyRow, "employee")})"""  # noqa: S608 (as above)
    leave_t, leave_row = _table(LeaveTypeRow), _table(LeaveAssign)
    leave = f"""CREATE OR ALTER VIEW GOV_LEAVE (LEAVE_ID, EMP_ID, LEAVE_TYPE_NAME, START_DATE, END_DATE, DAYS,
STATUS_NAME) AS
SELECT l.{_col(LeaveAssign, "id")}, l.{_col(LeaveAssign, "employee")}, t.{_col(LeaveTypeRow, "name")},
l.{_col(LeaveAssign, "date1")}, l.{_col(LeaveAssign, "date2")}, l.{_col(LeaveAssign, "adays")},
{_case(f"l.{_col(LeaveAssign, 'status')}", _LEAVE_STATUS_WORDS)}
FROM {leave_row} l
LEFT JOIN {leave_t} t ON t.{_col(LeaveTypeRow, "id")} = l.{_col(LeaveAssign, "leave_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = l.{_col(LeaveAssign, "employee")})"""  # noqa: S608 (as above)
    order_t = _table(HrOrder)
    orders = f"""CREATE OR ALTER VIEW GOV_ORDERS (ORDER_ID, EMP_ID, ORDER_TYPE_NAME, STATE_NAME, ORDER_NUMBER,
ORDER_DATE, SUMMARY) AS
SELECT o.{_col(HrOrder, "id")}, o.{_col(HrOrder, "employee")},
{_case(f"o.{_col(HrOrder, 'order_type')}", {int(t): w for t, w in _ORDER_TYPE_WORDS.items()})},
TRIM(o.{_col(HrOrder, "state")}), o.{_col(HrOrder, "number")}, o.{_col(HrOrder, "date")}, o.{_col(HrOrder, "summary")}
FROM {order_t} o
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = o.{_col(HrOrder, "employee")})"""  # noqa: S608 (as above)
    salary_t = _table(SalaryRecord)
    salary = f"""CREATE OR ALTER VIEW GOV_SALARY (SALARY_ID, EMP_ID, START_DATE, END_DATE, BASE_SALARY,
CHANGE_TYPE) AS
SELECT s.{_col(SalaryRecord, "id")}, s.{_col(SalaryRecord, "employee")}, s.{_col(SalaryRecord, "start_date")},
s.{_col(SalaryRecord, "end_date")}, s.{_col(SalaryRecord, "base_salary")}, s.{_col(SalaryRecord, "change_type")}
FROM {salary_t} s
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE sc WHERE sc.EMP_ID = s.{_col(SalaryRecord, "employee")})"""  # noqa: S608 (as above)
    loan_t, loan_ref_t = _table(LoanRow), _table(LoanRefRow)
    loans = f"""CREATE OR ALTER VIEW GOV_LOANS (LOAN_ID, EMP_ID, LOAN_DATE, END_DATE, AMOUNT, MONTHLY_PAYMENT,
REASON) AS
SELECT l.{_col(LoanRow, "id")}, l.{_col(LoanRow, "employee")}, l.{_col(LoanRow, "get_date")},
l.{_col(LoanRow, "end_date")}, l.{_col(LoanRow, "amount")}, l.{_col(LoanRow, "pay_permonth")},
r.{_col(LoanRefRow, "description")}
FROM {loan_t} l
LEFT JOIN {loan_ref_t} r ON r.{_col(LoanRefRow, "id")} = l.{_col(LoanRow, "loan_ref")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE sc WHERE sc.EMP_ID = l.{_col(LoanRow, "employee")})"""  # noqa: S608 (as above)
    educ_t, edu_type_t = _table(EducRow), _table(EduType)
    education = f"""CREATE OR ALTER VIEW GOV_EDUCATION (EDUCATION_ID, EMP_ID, EDUCATION_TYPE_NAME, START_DATE,
START_YEAR) AS
SELECT e.{_col(EducRow, "id")}, e.{_col(EducRow, "employee")}, t.{_col(EduType, "name")},
e.{_col(EducRow, "startdate")}, e.{_col(EducRow, "start_year")}
FROM {educ_t} e
LEFT JOIN {edu_type_t} t ON t.{_col(EduType, "id")} = e.{_col(EducRow, "edu_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = e.{_col(EducRow, "employee")})"""  # noqa: S608 (as above)
    qual_t, qual_type_t, prof_t = _table(QualificationRow), _table(QualificationType), _table(ProfessionType)
    edu_level_t, degree_t = _table(EducationLevel), _table(AcademicDegree)
    qualifications = f"""CREATE OR ALTER VIEW GOV_QUALIFICATIONS (QUALIFICATION_ID, EMP_ID, QUALIFICATION_TYPE_NAME,
PROFESSION_NAME, ORGANISATION, DIPLOMA_NUMBER, START_DATE, END_DATE, START_YEAR, END_YEAR, EDUCATION_LEVEL_NAME,
DEGREE_NAME, COUNTRY) AS
SELECT q.{_col(QualificationRow, "id")}, q.{_col(QualificationRow, "employee")}, qt.{_col(QualificationType, "name")},
pt.{_col(ProfessionType, "name")}, q.{_col(QualificationRow, "org_name")}, q.{_col(QualificationRow, "diplom_number")},
q.{_col(QualificationRow, "start_date")}, q.{_col(QualificationRow, "ending_date")},
q.{_col(QualificationRow, "start_year")}, q.{_col(QualificationRow, "end_year")},
el.{_col(EducationLevel, "name")}, ad.{_col(AcademicDegree, "name")}, q.{_col(QualificationRow, "country")}
FROM {qual_t} q
LEFT JOIN {qual_type_t} qt ON qt.{_col(QualificationType, "id")} = q.{_col(QualificationRow, "qualification_type")}
LEFT JOIN {prof_t} pt ON pt.{_col(ProfessionType, "id")} = q.{_col(QualificationRow, "profession_type")}
LEFT JOIN {edu_level_t} el ON el.{_col(EducationLevel, "id")} = q.{_col(QualificationRow, "edu_level")}
LEFT JOIN {degree_t} ad ON ad.{_col(AcademicDegree, "id")} = q.{_col(QualificationRow, "grade")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = q.{_col(QualificationRow, "employee")})"""  # noqa: S608 (as above)
    cert_t, spec_type_t = _table(CertificateRow), _table(SpecEduType)
    certificates = f"""CREATE OR ALTER VIEW GOV_CERTIFICATES (CERTIFICATE_ID, EMP_ID, CERTIFICATE_TYPE_NAME,
ORGANISATION, CERTIFICATE_NUMBER, CERTIFICATE_DATE, END_DATE, PROFESSION, SPECIAL_PROFESSION, CERTIFICATE_YEAR) AS
SELECT c.{_col(CertificateRow, "id")}, c.{_col(CertificateRow, "employee")}, t.{_col(SpecEduType, "name")},
c.{_col(CertificateRow, "org_edu")}, c.{_col(CertificateRow, "certify_number")},
c.{_col(CertificateRow, "certify_date")}, c.{_col(CertificateRow, "end_date")},
c.{_col(CertificateRow, "profession")}, c.{_col(CertificateRow, "spec_profession")},
c.{_col(CertificateRow, "certify_year")}
FROM {cert_t} c
LEFT JOIN {spec_type_t} t ON t.{_col(SpecEduType, "id")} = c.{_col(CertificateRow, "cert_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = c.{_col(CertificateRow, "employee")})"""  # noqa: S608 (as above)
    award_t = _table(AwardRow)
    awards = f"""CREATE OR ALTER VIEW GOV_AWARDS (AWARD_ID, EMP_ID, AWARD_NAME, GIVEN_BY, AWARD_DATE) AS
SELECT a.{_col(AwardRow, "id")}, a.{_col(AwardRow, "employee")}, a.{_col(AwardRow, "award_name")},
a.{_col(AwardRow, "give_org")}, a.{_col(AwardRow, "award_date")}
FROM {award_t} a
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = a.{_col(AwardRow, "employee")})"""  # noqa: S608 (as above)
    gift_t, gift_type_t = _table(PresentRow), _table(PresentType)
    gifts = f"""CREATE OR ALTER VIEW GOV_GIFTS (GIFT_ID, EMP_ID, GIFT_TYPE_NAME, GIFT_DATE, GIFT_YEAR, PRICE, GIVEN,
CHILD_COUNT, CHILD_AGE) AS
SELECT g.{_col(PresentRow, "id")}, g.{_col(PresentRow, "employee")}, t.{_col(PresentType, "name")},
g.{_col(PresentRow, "pdate")}, g.{_col(PresentRow, "given_year")}, g.{_col(PresentRow, "price")},
g.{_col(PresentRow, "given")}, g.{_col(PresentRow, "childqty")}, g.{_col(PresentRow, "child_age")}
FROM {gift_t} g
LEFT JOIN {gift_type_t} t ON t.{_col(PresentType, "id")} = g.{_col(PresentRow, "present_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = g.{_col(PresentRow, "employee")})"""  # noqa: S608 (as above)
    job_t = _table(JobRecord)
    job_history = f"""CREATE OR ALTER VIEW GOV_JOB_HISTORY (JOB_ID, EMP_ID, START_DATE, END_DATE, DEPARTMENT_NAME,
POSITION_NAME, MANAGER_NAME, STATUS, EMPLOYEE_TYPE, CONTRACT_TYPE, CONTRACT_NUMBER, CONTRACT_START, CONTRACT_END,
CHANGE_TYPE) AS
SELECT j.{_col(JobRecord, "id")}, j.{_col(JobRecord, "employee")}, j.{_col(JobRecord, "start_date")},
j.{_col(JobRecord, "end_date")}, d.{_col(Department, "name")}, p.{_col(Position, "name")},
TRIM(CASE WHEN m.{_col(Employee, "id")} IS NULL THEN NULL ELSE COALESCE(TRIM(m.{_col(Employee, "given_name")}), '')
|| ' ' || COALESCE(TRIM(m.{_col(Employee, "family_name")}), '') END),
j.{_col(JobRecord, "status")}, j.{_col(JobRecord, "employee_type")}, j.{_col(JobRecord, "contract_type")},
j.{_col(JobRecord, "contract_no")}, j.{_col(JobRecord, "contract_start")}, j.{_col(JobRecord, "contract_end")},
TRIM(CASE WHEN j.{_col(JobRecord, "change_type")} = '{ChangeType.SALARY_CHANGE.value}' THEN NULL
ELSE j.{_col(JobRecord, "change_type")} END)
FROM {job_t} j
LEFT JOIN {dep} d ON d.{_col(Department, "id")} = j.{_col(JobRecord, "department")}
LEFT JOIN {pos} p ON p.{_col(Position, "id")} = j.{_col(JobRecord, "position")}
LEFT JOIN {emp} m ON m.{_col(Employee, "id")} = j.{_col(JobRecord, "manager")}
AND EXISTS (SELECT 1 FROM GOV_SCOPE ms WHERE ms.EMP_ID = m.{_col(Employee, "id")})
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = j.{_col(JobRecord, "employee")})"""  # noqa: S608 (as above)
    event_t, fired_t = _table(Event), _table(FiredReason)
    event_status = (
        f"TRIM(CASE WHEN e.{_col(Event, 'cancelled_at')} IS NOT NULL THEN 'cancelled'"
        f" WHEN e.{_col(Event, 'applied_at')} IS NULL THEN 'awaiting_signature' ELSE 'applied' END)"
    )
    events = f"""CREATE OR ALTER VIEW GOV_EVENTS (EVENT_ID, EMP_ID, EVENT_TYPE, EFFECTIVE_DATE,
FIRED_REASON_NAME, EXPECTED_RETURN, STATUS_NAME) AS
SELECT e.{_col(Event, "id")}, e.{_col(Event, "employee")}, e.{_col(Event, "type")}, e.{_col(Event, "effective")},
f.{_col(FiredReason, "name")}, e.{_col(Event, "expected_return")}, {event_status}
FROM {event_t} e
LEFT JOIN {fired_t} f ON f.{_col(FiredReason, "id")} = e.{_col(Event, "fired_reason")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = e.{_col(Event, "employee")})
AND e.{_col(Event, "type")} <> '{EventType.SALARY_CHANGE.value}'"""  # noqa: S608 (as above)
    ent_t = _table(Entitlement)
    entitlements = f"""CREATE OR ALTER VIEW GOV_ENTITLEMENTS (ENTITLEMENT_ID, EMP_ID, LEAVE_TYPE_NAME, START_DATE,
END_DATE, DAYS) AS
SELECT n.{_col(Entitlement, "id")}, n.{_col(Entitlement, "employee")}, t.{_col(LeaveTypeRow, "name")},
n.{_col(Entitlement, "date1")}, n.{_col(Entitlement, "date2")}, n.{_col(Entitlement, "ent_days")}
FROM {ent_t} n
LEFT JOIN {leave_t} t ON t.{_col(LeaveTypeRow, "id")} = n.{_col(Entitlement, "leave_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = n.{_col(Entitlement, "employee")})"""  # noqa: S608 (as above)
    request_t = _table(LeaveRequest)
    leave_requests = f"""CREATE OR ALTER VIEW GOV_LEAVE_REQUESTS (REQUEST_ID, EMP_ID, LEAVE_TYPE_NAME, START_DATE,
END_DATE, WORKING_DAYS, STATUS_NAME) AS
SELECT r.{_col(LeaveRequest, "id")}, r.{_col(LeaveRequest, "employee")}, t.{_col(LeaveTypeRow, "name")},
r.{_col(LeaveRequest, "start_date")}, r.{_col(LeaveRequest, "end_date")}, r.{_col(LeaveRequest, "working_days")},
TRIM(r.{_col(LeaveRequest, "status")})
FROM {request_t} r
LEFT JOIN {leave_t} t ON t.{_col(LeaveTypeRow, "id")} = r.{_col(LeaveRequest, "leave_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = r.{_col(LeaveRequest, "employee")})"""  # noqa: S608 (as above)
    # Every department is a row (not employee-scoped). HEADCOUNT counts only the working employees the asker may see.
    dep_id, dep_name = _col(Department, "id"), _col(Department, "name")
    emp_id, emp_dep = _col(Employee, "id"), _col(Employee, "department")
    departments = f"""CREATE OR ALTER VIEW GOV_DEPARTMENTS (DEPARTMENT_ID, DEPARTMENT_NAME, HEADCOUNT) AS
SELECT d.{dep_id}, d.{dep_name},
(SELECT COUNT(*) FROM {emp} e JOIN GOV_SCOPE s ON s.EMP_ID = e.{emp_id}
WHERE s.WORKING = 1 AND e.{emp_dep} = d.{dep_id})
FROM {dep} d"""  # noqa: S608 (as above)
    # Every position is a row (not employee-scoped). HEADCOUNT counts only the working employees the asker may see.
    pos_name = _col(Position, "name")
    pos_id, emp_pos = _col(Position, "id"), _col(Employee, "position")
    positions = f"""CREATE OR ALTER VIEW GOV_POSITIONS (POSITION_ID, POSITION_NAME, HEADCOUNT) AS
SELECT p.{pos_id}, p.{pos_name},
(SELECT COUNT(*) FROM {emp} e JOIN GOV_SCOPE s ON s.EMP_ID = e.{emp_id}
WHERE s.WORKING = 1 AND e.{emp_pos} = p.{pos_id})
FROM {pos} p"""  # noqa: S608 (as above)
    return [
        employees,
        children,
        leave,
        orders,
        salary,
        loans,
        education,
        qualifications,
        certificates,
        awards,
        gifts,
        job_history,
        events,
        entitlements,
        leave_requests,
        departments,
        positions,
    ]


_VIEW_HEADER = re.compile(r"CREATE OR ALTER VIEW (\w+) \(([^)]*)\)", re.DOTALL)


def view_columns() -> dict[str, tuple[str, ...]]:
    """The column names of each governed view, read from its CREATE header in view_statements(). No database."""
    found: dict[str, tuple[str, ...]] = {}
    for statement in view_statements():
        match = _VIEW_HEADER.search(statement)
        if match is None:
            raise ValueError(f"no column list in view statement: {statement[:60]!r}")
        names = tuple(part.strip() for part in match.group(2).split(",") if part.strip())
        found[match.group(1)] = names
    return found


def _drop_governed(cursor: Any) -> None:
    """Drop every GOV_* view, then GOV_SCOPE. A view that reads GOV_SCOPE blocks the table's drop, so views go first."""
    cursor.execute(_GOV_VIEW_LIST)
    names = [str(row[0]) for row in cursor.fetchall()]
    for name in names:
        if not re.fullmatch(r"GOV_[A-Z0-9_]+", name):
            raise ValueError(f"not a governed view name: {name!r}")
        cursor.execute(f"DROP VIEW {name}")  # noqa: S608 (name checked above)
    cursor.execute("DROP TABLE GOV_SCOPE")


def install(connection: BaseDatabaseWrapper) -> None:
    """Create or update the governed objects in one transaction. Safe to run again.

    A table cannot be altered in place, so when GOV_SCOPE exists without the WORKING column (a database installed
    before it was added), the GOV_* views and GOV_SCOPE are dropped and created again, in this same transaction.
    The rows of GOV_SCOPE are temporary (they are filled per query), so nothing is lost. The views use CREATE OR ALTER.
    Dropping the table drops its grants: the administrator must run scripts/grant_governed_fb.sql again afterwards.
    """
    with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM RDB$RELATIONS WHERE TRIM(RDB$RELATION_NAME) = 'GOV_SCOPE'")
        exists = bool(int(cursor.fetchone()[0]))
        if exists:
            cursor.execute(_SCOPE_WORKING_CHECK)
            if not int(cursor.fetchone()[0]):
                _drop_governed(cursor)
                exists = False
        if not exists:
            cursor.execute(_SCOPE_CREATE)
        for statement in view_statements():
            cursor.execute(statement)

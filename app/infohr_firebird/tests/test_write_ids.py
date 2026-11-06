"""Every MACS table HR writes returns a generated ID, and the sequence helpers never target MACS tables (plan 3, Task 10).

Part A: each production table HR inserts into is written twice through its real service (or the ORM the way the
service does it) on the migrated clone. The ids must be positive, distinct and increasing: they come from the MACS
generators through the MACS triggers (or from macs.dialect.next_value for employee_history). The same subprocess checks two
Django paths that could reach a wrong generator name `<TABLE>_SQ`, which does not exist in MACS:
- ORM inserts use RETURNING, so DatabaseOperations.last_insert_id is never called for these tables;
- sequence_reset_sql (manage.py sqlsequencereset) must emit nothing for unmanaged MACS models.

Part B: system check W011 (server clock in Asia/Ulaanbaatar). Unit tests with a mocked cursor and clock, no database.
Each scenario runs in a subprocess on the migrated clone (the same pattern as test_write_hire.py) and reports JSON.
"""

from datetime import datetime
from typing import Any

import pytest
from django.core.checks import Warning as DjangoWarning

from infohr_firebird import checks
from infohr_firebird.tests.test_settings_seam import result_of, run_django

# Writes made by HR on MACS tables, by label. Each maker returns the ids it created for employee number n (1 or 2).
TABLE_LABELS = [
    "employee",
    "customer",
    "address",
    "contacting",
    "family",
    "qualification",
    "given_present",
    "birth_place",
    "emp_photo",
    "leave_type",
    "leave_assign",
    "entitlement",
    "hr_legalholidays",
    "command",
    "employee_history",
    "nazg",
    "movement",
    "deps",
    "occupation",
    "relative",
    "before_work",
    "spec_edu",
    "hr_training",
    "foreign_lang",
    "hr_skillwork",
    "material_help",
    "awards",
    "discipline",
    "hr_complaints",
    "body",
    "driver",
    "military",
    "army_rank",
]
# Tables HR writes without a generated primary key (composite keys); the test only checks that rows exist.
NO_GENERATOR_LABELS = ["emp_talents", "emp_vacation"]

WRITES_CODE = """
import json
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.db import connection, transaction
from employees.models import Employee, HrOrder, OrderType
from employees.services import macs_writes, orders as order_services, personal_writes
from leave.models import GrantKind
from leave.services import writes as leave_writes
from macs.models import (
    AcademicDegree, BirthPlace, City, ContactType, District, DisciplineType, DriverType, EducationLevel,
    EmployeePhoto, FamilyRelation, ForeignLanguage, LegalHoliday, Branch, Department, MaterialHelpType, Position,
    PresentType, SpecEduType, TalentKind, Command, Movement,
)
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"t10_{tag}", password="x-long-pass-123")

def first(model):
    # The first row of a code list; an empty list gets one row (the template ships some lists empty).
    row = model.objects.order_by("pk").first()
    if row is None:
        row = model.objects.create(name=f"Т10 {model.__name__}")
    return row

def hire(n):
    values = {
        "family_name": "Тест",
        "given_name": f"Т10{tag}{n}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9010{n:04d}",
        "first_hire_date": dt.date(2026, 1, 5),
        "work_conditions": 1,
    }
    return macs_writes.create_employee(values, {}, code=f"T{tag}{n}", by=by)

emps = {1: hire(1), 2: hire(2)}
city = first(City)
district = District.objects.filter(city=city).order_by("pk").first()
leave_type = leave_writes.save_leave_type("T10 чөлөө", {"uses_annual_balance": True})
dep = first(Department)
pos = first(Position)
branch = first(Branch)

def makers():
    m = {}
    m["employee"] = lambda n: [emps[n].pk]
    def customer(n):
        with connection.cursor() as c:
            c.execute("select cust_id from customer where employee_ident = %s order by cust_id", [emps[n].pk])
            return [int(c.fetchone()[0])]
    m["customer"] = customer
    m["address"] = lambda n: [int(personal_writes.add("address", emps[n], {
        "street": f"Т10 гудамж {n}", "city_id": city.pk, "district_id": district.pk}, {}, by=by))]
    m["contacting"] = lambda n: [int(personal_writes.add("contact", emps[n], {
        "contact_type_id": first(ContactType).pk, "value": f"9900{n}000", "name": "Дорж", "relative": "Ах"}, {}, by=by))]
    m["family"] = lambda n: [int(personal_writes.add("family", emps[n], {
        "relation_id": first(FamilyRelation).pk, "given_name": f"Гэр{n}", "surname": "Тест"}, {}, by=by))]
    m["qualification"] = lambda n: [int(personal_writes.add("education", emps[n], {
        "org_name": "Т10 сургууль", "start_year": 2005, "end_year": 2009}, {}, by=by))]
    m["given_present"] = lambda n: [int(personal_writes.add("gift", emps[n], {
        "present_type_id": first(PresentType).pk, "childqty": 1, "price": 1000, "given_year": 2026,
        "child_age": 3, "given": 1, "pdate": dt.date(2026, 2, 1)}, {}, by=by))]
    def birth_place(n):
        macs_writes.save_birth_place(emps[n], city, district, "Т10 төрсөн газар")
        return [BirthPlace.objects.get(employee=emps[n]).pk]
    m["birth_place"] = birth_place
    def emp_photo(n):
        macs_writes.save_photo(emps[n], b"\\xff\\xd8\\xff\\xe0T10")
        return [EmployeePhoto.objects.get(employee=emps[n]).pk]
    m["emp_photo"] = emp_photo
    m["leave_type"] = lambda n: [leave_writes.save_leave_type(f"T10 төрөл {n}", {}).pk]
    m["leave_assign"] = lambda n: [leave_writes.record_assign(
        emps[n], leave_type, dt.date(2026, 3, 10 + n), dt.date(2026, 3, 10 + n), 1, "Т10", by).pk]
    m["entitlement"] = lambda n: [leave_writes.add_grant(
        emps[n], leave_type, dt.date(2026, 1, 1), dt.date(2026, 12, 31), 5 + n, "Т10", GrantKind.MANUAL, by).pk]
    def legal(n):
        year = 2090 + n
        leave_writes.set_holiday_dates(year, {dt.date(year, 1, 1): "Т10 А", dt.date(year, 3, 1): "Т10 Б"})
        return list(LegalHoliday.objects.filter(start_date__year=year).order_by("pk").values_list("pk", flat=True))
    m["hr_legalholidays"] = legal
    def command(n):
        # The MACS write itself (write_order inserts the command row). Order registration is probed separately.
        order = HrOrder.objects.create(employee=emps[n], event=None, is_hire=True, order_type=OrderType.HIRED,
                                       created_by=by)
        order.number, order.date, order.summary, order.issued_by = f"Т10-{n}", dt.date(2026, 2, n), "Т10", "Т10"
        macs_writes.write_order(order)
        return [order.command_id]
    m["command"] = command
    m["employee_history"] = lambda n: [macs_writes.snapshot_history(emps[n])]
    m["nazg"] = lambda n: [macs_writes.save_slot_row(
        position=pos, branch=branch, kind="Main", year=2090 + n, qty=1).pk]
    m["movement"] = lambda n: [macs_writes.record_movement(
        emps[n], "in", dt.date(2026, 3, 2), new={"department_id": dep.pk, "position_id": pos.pk, "emptype": 1})]
    m["deps"] = lambda n: [macs_writes.save_department(f"Т10 хэлтэс {n}").pk]
    m["occupation"] = lambda n: [macs_writes.save_position(f"Т10 ажлын байр {n}").pk]
    m["relative"] = lambda n: [int(personal_writes.add("relative", emps[n], {
        "given_name": "Ах", "description": "Ах"}, {}, by=by))]
    m["before_work"] = lambda n: [int(personal_writes.add("before_work", emps[n], {
        "start_year": 2010, "end_year": 2015}, {}, by=by))]
    m["spec_edu"] = lambda n: [int(personal_writes.add("certificate", emps[n], {
        "cert_type_id": first(SpecEduType).pk, "org_edu": "Т10 сургууль", "certify_year": 2012}, {}, by=by))]
    m["hr_training"] = lambda n: [int(personal_writes.add("training", emps[n], {
        "tr_type": 1, "description": "Т10 сургалт", "amount": Decimal("1000.00"), "pay_type": 1,
        "start_year": 2020}, {}, by=by))]
    m["foreign_lang"] = lambda n: [int(personal_writes.add("language", emps[n], {
        "language_id": first(ForeignLanguage).pk}, {}, by=by))]
    m["hr_skillwork"] = lambda n: [int(personal_writes.add("skill", emps[n], {
        "norm": Decimal("1.00")}, {}, by=by))]
    m["material_help"] = lambda n: [int(personal_writes.add("material_help", emps[n], {
        "amount": Decimal("100.00"), "material_type_id": first(MaterialHelpType).pk,
        "help_date": dt.date(2026, 2, 1)}, {}, by=by))]
    m["awards"] = lambda n: [int(personal_writes.add("award", emps[n], {
        "award_name": "Т10 шагнал", "description": "Т10"}, {}, by=by))]
    m["discipline"] = lambda n: [int(personal_writes.add("discipline", emps[n], {
        "discipline_type_id": first(DisciplineType).pk, "discipline_date": dt.date(2026, 2, 1)}, {}, by=by))]
    m["hr_complaints"] = lambda n: [int(personal_writes.add("complaint", emps[n], {
        "cdate": dt.date(2026, 2, 1), "ctype": 1, "complaint_name": 1}, {}, by=by))]
    m["body"] = lambda n: [int(personal_writes.add("body", emps[n], {}, {}, by=by))]
    m["driver"] = lambda n: [int(personal_writes.add("driver", emps[n], {
        "driver_type_id": first(DriverType).pk}, {}, by=by))]
    m["military"] = lambda n: [int(personal_writes.add("military", emps[n], {}, {}, by=by))]
    m["army_rank"] = lambda n: [int(personal_writes.add("army_rank", emps[n], {}, {}, by=by))]
    return m

def no_generator_writes():
    talent = first(TalentKind)
    personal_writes.add("talent", emps[1], {"talent_ident": talent.pk, "trained_year": 2020, "description": "Т10"},
                        {}, by=by)
    out = {}
    with connection.cursor() as c:
        c.execute("select count(*) from emp_talents where emp_ident = %s", [emps[1].pk])
        out["emp_talents"] = int(c.fetchone()[0])
        c.execute("select count(*) from emp_vacation where emp_ident in (%s, %s)", [emps[1].pk, emps[2].pk])
        out["emp_vacation"] = int(c.fetchone()[0])
    return out

ops = connection.ops
original_last_insert_id = ops.last_insert_id
last_insert_id_calls = []

def counting_last_insert_id(cursor, table, column):
    last_insert_id_calls.append(table)
    return original_last_insert_id(cursor, table, column)

ops.last_insert_id = counting_last_insert_id
tables = {}
for label, make in makers().items():
    ids, error = [], None
    try:
        for n in (1, 2):
            with transaction.atomic():
                ids += [int(x) for x in make(n)]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    tables[label] = {"ids": ids, "error": error}
no_generator = {}
try:
    no_generator = no_generator_writes()
except Exception as exc:
    no_generator = {"error": f"{type(exc).__name__}: {exc}"}
ops.last_insert_id = original_last_insert_id

with connection.cursor() as c:
    c.execute("select trim(rdb$generator_name) from rdb$generators")
    generators = {row[0] for row in c.fetchall()}
macs_models = list(apps.get_app_config("macs").get_models())
derived = {m._meta.db_table: ops.get_sequence_name(m._meta.db_table).strip('"') for m in macs_models}
reset_lengths = {}
for model in macs_models:
    try:
        reset_lengths[model._meta.label] = len(ops.sequence_reset_sql(no_style(), [model]))
    except Exception as exc:
        reset_lengths[model._meta.label] = f"error {type(exc).__name__}: {exc}"
managed_reset = len(ops.sequence_reset_sql(no_style(), [apps.get_model("accounts", "User")]))
try:
    order_services.create_for_change(employee=emps[1], event=None, is_hire=True, order_type=OrderType.HIRED,
                                     number="Т10-R", date=dt.date(2026, 2, 9), summary="Т10", issued_by="Т10", by=by)
    registration_error = None
except Exception as exc:
    registration_error = f"{type(exc).__name__}: {exc}"
print("RESULT " + json.dumps({
    "tables": tables,
    "no_generator": no_generator,
    "last_insert_id_calls": last_insert_id_calls,
    "derived_names_that_exist": sorted(name for name in derived.values() if name in generators),
    "reset_lengths": reset_lengths,
    "managed_reset_length": managed_reset,
    "returning_supported": bool(connection.features.can_return_columns_from_insert),
    "order_registration_error": registration_error,
}))
"""


@pytest.fixture(scope="module")
def written(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(WRITES_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_every_label_in_the_sweep_ran(written: dict[str, Any]) -> None:
    assert sorted(written["tables"]) == sorted(TABLE_LABELS)


@pytest.mark.parametrize("label", TABLE_LABELS)
def test_hr_insert_returns_positive_increasing_generated_ids(written: dict[str, Any], label: str) -> None:
    entry = written["tables"][label]
    assert entry["error"] is None, entry["error"]
    ids = entry["ids"]
    assert len(ids) >= 2, ids
    assert all(i > 0 for i in ids), ids
    assert ids == sorted(set(ids)), f"ids must be distinct and increasing: {ids}"


@pytest.mark.parametrize("label", NO_GENERATOR_LABELS)
def test_composite_key_tables_still_get_rows(written: dict[str, Any], label: str) -> None:
    assert "error" not in written["no_generator"], written["no_generator"]
    assert written["no_generator"][label] >= 1


def test_orm_inserts_never_reach_last_insert_id(written: dict[str, Any]) -> None:
    """Firebird reports RETURNING support, so Django reads the new pk from the insert itself. The wrong-name path
    (<TABLE>_SQ) is not used by any HR write."""
    assert written["returning_supported"] is True
    assert written["last_insert_id_calls"] == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "orders._validate runs SELECT pg_advisory_xact_lock(...), a PostgreSQL-only function, so registering an "
        "order (create_for_change / register) fails on Firebird before any MACS row is written. Needs a Firebird "
        "lock (for example a lock row) chosen by the user; strict so the marker is removed when it is fixed."
    ),
)
def test_order_registration_runs_on_firebird(written: dict[str, Any]) -> None:
    assert written["order_registration_error"] is None, written["order_registration_error"]


def test_derived_sequence_names_are_not_real_generators(written: dict[str, Any]) -> None:
    """The premise of the sequence check: no generator is named <TABLE>_SQ, so any path that derives one fails."""
    assert written["derived_names_that_exist"] == []


def test_sequence_reset_sql_emits_nothing_for_unmanaged_macs_tables(written: dict[str, Any]) -> None:
    non_empty = {label: n for label, n in written["reset_lengths"].items() if n != 0}
    assert non_empty == {}, non_empty


def test_sequence_reset_sql_still_works_for_managed_models(written: dict[str, Any]) -> None:
    assert written["managed_reset_length"] > 0


# Part B: system check W011, the Firebird server clock must be on Asia/Ulaanbaatar wall-clock time.


class _FakeCursor:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.sql: list[str] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str) -> None:
        self.sql.append(sql)

    def fetchone(self) -> tuple[datetime]:
        return (self.value,)


class _FakeConnection:
    def __init__(self, value: datetime) -> None:
        self.cursor_obj = _FakeCursor(value)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


NOW = datetime(2026, 11, 6, 10, 0, 0)


def test_w011_is_silent_when_the_server_clock_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks, "_enabled", lambda: True)
    monkeypatch.setattr(checks, "_ulaanbaatar_now", lambda: NOW)
    monkeypatch.setattr(checks, "connection", _FakeConnection(datetime(2026, 11, 6, 10, 1, 59)))
    assert checks.check_server_time_zone(databases=["default"]) == []


def test_w011_warns_when_the_server_is_eight_hours_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks, "_enabled", lambda: True)
    monkeypatch.setattr(checks, "_ulaanbaatar_now", lambda: NOW)
    fake = _FakeConnection(datetime(2026, 11, 6, 2, 0, 0))  # a server on UTC: 8 hours behind Ulaanbaatar
    monkeypatch.setattr(checks, "connection", fake)
    issues = checks.check_server_time_zone(databases=["default"])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.id == "infohr_firebird.W011"
    assert isinstance(issue, DjangoWarning)
    assert "2026-11-06 02:00:00" in issue.hint and "2026-11-06 10:00:00" in issue.hint
    assert "the Firebird server time zone must be Asia/Ulaanbaatar" in issue.hint
    assert fake.cursor_obj.sql == ["select current_timestamp from rdb$database"]


def test_w011_is_silent_outside_firebird_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks, "_enabled", lambda: False)
    monkeypatch.setattr(checks, "_ulaanbaatar_now", lambda: NOW)
    monkeypatch.setattr(checks, "connection", _FakeConnection(datetime(2026, 11, 6, 2, 0, 0)))
    assert checks.check_server_time_zone(databases=["default"]) == []


def test_w011_does_not_run_without_a_database_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks, "_enabled", lambda: True)
    monkeypatch.setattr(checks, "_ulaanbaatar_now", lambda: NOW)
    fake = _FakeConnection(datetime(2026, 11, 6, 2, 0, 0))
    monkeypatch.setattr(checks, "connection", fake)
    assert checks.check_server_time_zone(databases=None) == []
    assert checks.check_server_time_zone(databases=["other"]) == []
    assert fake.cursor_obj.sql == []

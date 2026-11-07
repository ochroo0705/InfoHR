"""Code that used PostgreSQL-only SQL, tested on Firebird (plan 4, Task 4 on).

Each scenario runs in a subprocess on the migrated clone (``migrated_clone``) and reports a JSON result. Later tasks
of the plan append their scenarios to this file: add a code string built from PRELUDE, one ``_firebird`` call and
the assertions in the test function.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PRELUDE = """
import json
import threading
import django
django.setup()
from django.db import connection, transaction
from employees.models import StaffImportDraft
from employees.staff_import import run

BUSY = "Өөр импорт явагдаж байна."


def make_draft(label):
    return StaffImportDraft.objects.create(filename=f"{label}.xlsx", data=b"x")


def states(*drafts):
    return [StaffImportDraft.objects.get(pk=draft.pk).state for draft in drafts]
"""

DOUBLE_CLAIM_CODE = (
    PRELUDE
    + """
out = {}
first = make_draft("first")
second = make_draft("second")
with transaction.atomic():
    # Writer A claims the first draft and keeps its transaction open, so it still holds the STAFF_IMPORT lock.
    run._claim(first)

    def attempt_b():
        try:
            with transaction.atomic():
                run._claim(second)
            out["b"] = "ok"
        except run.DraftBusy as exc:
            out["b"] = "busy" if str(exc) == BUSY else f"other:{exc}"
        except Exception as exc:
            out["b"] = f"unexpected:{type(exc).__name__}: {exc}"
        finally:
            connection.close()

    thread = threading.Thread(target=attempt_b)
    thread.start()
    thread.join(30)
    out["b_finished"] = not thread.is_alive()
# Writer A has committed: exactly one draft is running, the other was never claimed.
out["states"] = states(first, second)
print("RESULT " + json.dumps(out))
"""
)


def _firebird(migrated_clone: str, code: str) -> dict[str, Any]:
    return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_double_claim_starts_one_run(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, DOUBLE_CLAIM_CODE)
    assert data["b_finished"] is True, data
    assert data["b"] == "busy", data
    assert data["states"] == ["running", "uploaded"], data


# Task 5: the talent list reads its rows in physical order (ctid on PostgreSQL, RDB$DB_KEY on Firebird).
TALENT_CODE = (
    PRELUDE  # noqa: S608 (ruff reports this whole concatenation here; the SQL is a fixed test literal)
    + """
import uuid
from employees.models import Employee
from employees.services import personal_rows
from macs.models import TalentKind

tag = uuid.uuid4().hex[:6]
emp = Employee.objects.order_by("pk").first()
empty = Employee.objects.exclude(pk=emp.pk).order_by("pk").first()
kinds = [TalentKind.objects.create(name=f"Авьяас{tag}{i}") for i in range(3)]
# Inserted in this order: the list must come back in the same order.
inserted = [(kinds[2], 2015, "c"), (kinds[0], 2016, "a"), (kinds[1], 2017, "b")]
with connection.cursor() as cur:
    for kind, year, text in inserted:
        cur.execute(
            "INSERT INTO emp_talents (emp_ident, talent_ident, trained_year, description) VALUES (%s, %s, %s, %s)",
            [emp.pk, kind.pk, year, text],
        )
found = personal_rows.rows("talent", emp)
print("RESULT " + json.dumps({
    "keys": [row.key for row in found],
    "expected_keys": [kind.pk for kind, _, _ in inserted],
    "descriptions": [row.values["description"] for row in found],
    "empty": [row.key for row in personal_rows.rows("talent", empty)],
}))
"""
)


def test_talent_list_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, TALENT_CODE)
    assert data["keys"] == data["expected_keys"], data
    assert data["descriptions"] == ["c", "a", "b"], data
    assert data["empty"] == [], data


# Task 6: the Ctrl+K people search counts its matches without a window expression.
PALETTE_CODE = (
    PRELUDE
    + """
import datetime as dt
import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from employees import palette
from employees.models import ContractType, EmployeeType, JobStatus, ensure_ext
from employees.services import history
from macs.models import Branch, Department, Position

User = get_user_model()
TODAY = dt.date(2026, 10, 14)
START = dt.date(2026, 1, 5)
tag = uuid.uuid4().hex[:6]
hr = User.objects.create_user(f"palette_{tag}", password="x-long-pass-123")
hr.groups.add(Group.objects.get(name="HR"))
dep = Department.objects.order_by("pk").values_list("pk", flat=True).first()
pos = Position.objects.order_by("pk").values_list("pk", flat=True).first()
br = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
job = {
    "department_id": dep,
    "position_id": pos,
    "employee_type": EmployeeType.FULL_TIME,
    "status": JobStatus.ACTIVE,
    "contract_type": ContractType.OPEN_ENDED,
}
# A capital Ө and Ү name, found by a search typed with о and у (the fold maps ө to о and ү to у).
oy = history.hire(
    {
        "family_name": "ӨЛЗИЙ",
        "given_name": "ҮҮРЭН",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": "УБ91010001",
        "first_hire_date": START,
        "work_conditions": 1,
        "branch_id": br,
    },
    {},
    start=START,
    job=job,
    salary=Decimal("1500000.00"),
    by=hr,
)
ensure_ext(oy)
oy_hits = [h.employee.pk for h in palette.find_people(hr, "олзий", TODAY)[0]]
oy_hits_u = [h.employee.pk for h in palette.find_people(hr, "уурэн", TODAY)[0]]
# The same letters stored in lowercase: the fold must map them too.
low = history.hire(
    {
        "family_name": "Дорж",
        "given_name": "өлзий",
        "gender": "M",
        "birth_date": dt.date(1991, 3, 2),
        "register_no": "УБ91010002",
        "first_hire_date": START,
        "work_conditions": 1,
        "branch_id": br,
    },
    {},
    start=START,
    job=job,
    salary=Decimal("1500000.00"),
    by=hr,
)
ensure_ext(low)
low_hits = [h.employee.pk for h in palette.find_people(hr, "олзий", TODAY)[0]]
# Names already in the clone count too, so the expected total is measured first, then 12 new matches are added.
baseline = palette.find_people(hr, "бат", TODAY, limit=1000)[1]
for n in range(12):
    values = {
        "family_name": "Батын",
        "given_name": f"Нэр{tag}{n}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9100{n:04d}",
        "first_hire_date": START,
        "work_conditions": 1,
        "branch_id": br,
    }
    emp = history.hire(values, {}, start=START, job=job, salary=Decimal("1500000.00"), by=hr)
    ensure_ext(emp)
hits, total = palette.find_people(hr, "бат", TODAY, limit=8)
none_hits, none_total = palette.find_people(hr, "zzqx", TODAY)
print("RESULT " + json.dumps({
    "baseline": baseline,
    "hits": len(hits),
    "total": total,
    "none": [len(none_hits), none_total],
    "oy_pk": oy.pk,
    "oy_hits": oy_hits,
    "oy_hits_u": oy_hits_u,
    "low_pk": low.pk,
    "low_hits": low_hits,
}))
"""
)


def test_palette_search_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, PALETTE_CODE)
    assert data["hits"] == 8, data
    assert data["total"] == data["baseline"] + 12, data
    assert data["none"] == [0, 0], data
    assert data["oy_pk"] in data["oy_hits"], data
    assert data["oy_pk"] in data["oy_hits_u"], data
    assert data["low_pk"] in data["low_hits"], data


# Task 7: the checklist template for a reason is picked in Python, not with a JSON contains lookup.
LIFECYCLE_CODE = (
    PRELUDE
    + """
import uuid
from checklists.models import ChecklistKind, ChecklistTemplate
from checklists.services import lifecycle

tag = uuid.uuid4().hex[:6]
# The clone already has the active default offboarding template (the starter), so only the reason template is new.
resigned = ChecklistTemplate.objects.create(
    kind=ChecklistKind.OFFBOARDING, name=f"Өөрөө гарсан {tag}", reasons=["resigned"], active=True
)
default = ChecklistTemplate.objects.get(kind=ChecklistKind.OFFBOARDING, is_default=True, active=True)
print("RESULT " + json.dumps({
    "resigned_pk": resigned.pk,
    "default_pk": default.pk,
    "for_resigned": getattr(lifecycle.template_for("offboarding", "resigned"), "pk", None),
    "for_retired": getattr(lifecycle.template_for("offboarding", "retired"), "pk", None),
    "for_none": getattr(lifecycle.template_for("offboarding", None), "pk", None),
}))
"""
)


def test_template_for_reason_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, LIFECYCLE_CODE)
    assert data["for_resigned"] == data["resigned_pk"], data
    assert data["for_retired"] == data["default_pk"], data
    assert data["for_none"] == data["default_pk"], data


# Task 8: the log screens' field filter and free-text search. Django stores changes as JSON text with non-ASCII
# written as \uXXXX escapes, so the field filter compares the escaped `"field": "<label>"` text. The free-text search
# compares the folded `change_text` column (plan 5, task 6), which holds the plain values, so it works on the same
# words as PostgreSQL. Each message ends with a random tag, and the results keep only the rows of this run, so
# earlier rows in the clone do not count.
LOG_CODE = (
    PRELUDE
    + """
import uuid
from accounts.audit import Category
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from employees.models import ActivityEntry, ActivityKind, Employee
from logs.employee_query import EmployeeLogFilter, filtered
from logs.system_query import SystemLogFilter
from logs.system_query import filtered as system_filtered

BS = chr(92)  # one backslash, without writing it in this code string
QUOTED = 'a"b' + BS + "c"
# Letters only (a to p, no digits and no "u"): a digit or "u0" search must not match through the message tag.
tag = "".join(chr(97 + int(digit, 16)) for digit in uuid.uuid4().hex[:6])
admin = User.objects.create_user(f"log_fb_{tag}", password="x-long-pass-123")
admin.groups.add(Group.objects.get(name="Admin"))
admin = User.objects.get(pk=admin.pk)
emp = Employee.objects.order_by("pk").first()


def add(message, changes):
    text = f"{message} {tag}"
    return ActivityEntry.objects.create(employee=emp, kind=ActivityKind.CHANGED, message=text, changes=changes)


def base(rows):
    return [row.message[: -len(tag) - 1] for row in rows if row.message.endswith(tag)]


add("Цалин өөрчлөгдсөн", [{"field": "Цалин", "old": "1000", "new": "2000"}])
add("Нэмэгдэл", [{"field": "Цалингийн нэмэгдэл", "old": "", "new": "5"}])
add("Тэмдэгт", [{"field": QUOTED, "old": "x", "new": "y"}])
add("Ascii Ab", [{"field": "Ab", "old": "Hoh", "new": "2"}])
add("Ascii ab", [{"field": "ab", "old": "1", "new": "2"}])
add("Хаяг", [{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
SystemLogEntry.objects.create(
    message=f"Тохиргоо {tag}",
    category=Category.SETTINGS,
    action="setting_added",
    actor_name="x",
    changes=[{"field": "Ажлын цаг", "old": "Сүхбаатар", "new": "Баянзүрх"}],
)


def by_field(label):
    return base(filtered(admin, EmployeeLogFilter(field=label)))


def by_text(word):
    return base(filtered(admin, EmployeeLogFilter(q=word)))


print("RESULT " + json.dumps({
    "label_cyr": by_field("Цалин"),
    "label_long": by_field("Цалингийн нэмэгдэл"),
    "label_quoted": by_field(QUOTED),
    "label_ab": by_field("Ab"),
    "label_ab_lower": by_field("ab"),
    "old_cyr": by_text("Сүхбаатар"),
    "new_cyr": by_text("Баянзүрх"),
    "lower_cyr": by_text("сүхбаатар"),
    "ascii_value": by_text("hoh"),
    "fragment_u0": by_text("u0"),
    "fragment_4": by_text("4"),
    "key_old": by_text("old"),
    "key_field": by_text("field"),
    "system": [row.message[: -len(tag) - 1] for row in system_filtered(SystemLogFilter(q="Баянзүрх"))
               if row.message.endswith(tag)],
}))
"""
)


def test_field_filter_matches_exact_label(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["label_cyr"] == ["Цалин өөрчлөгдсөн"], data  # not "Цалингийн нэмэгдэл"
    assert data["label_long"] == ["Нэмэгдэл"], data
    assert data["label_quoted"] == ["Тэмдэгт"], data  # a label with a quote and a backslash matches itself
    assert data["label_ab"] == ["Ascii Ab"], data
    assert data["label_ab_lower"] == ["Ascii ab"], data  # the field filter is case-sensitive, as on PostgreSQL


def test_text_search_finds_old_and_new_values(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["old_cyr"] == ["Хаяг"], data
    assert data["new_cyr"] == ["Хаяг"], data
    assert data["ascii_value"] == ["Ascii Ab"], data  # ASCII values stay case-insensitive


def test_lowercase_cyrillic_search_finds_uppercase_value(migrated_clone: str) -> None:
    # Was a pin: the escaped JSON kept the letter's case. The folded change_text column finds it now.
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["lower_cyr"] == ["Хаяг"], data


def test_short_ascii_fragment_does_not_match_cyrillic_entries(migrated_clone: str) -> None:
    # Was a pin: "u0" and "4" matched inside the \uXXXX escapes of every Cyrillic value. The plain text has no escapes.
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["fragment_u0"] == [], data
    assert data["fragment_4"] == [], data


def test_search_never_matches_json_key_names(migrated_clone: str) -> None:
    # Was a pin: the escaped JSON text carried the key names "old" and "field". change_text holds values only.
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["key_old"] == [], data
    assert data["key_field"] == [], data


def test_system_log_search_runs(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, LOG_CODE)
    assert data["system"] == ["Тохиргоо"], data


# Task 11, fix A: the employee list hashes the photos in Python on Firebird (Firebird 3 has no MD5 function). The digest
# must equal the hash of the stored bytes, and the lowest photo id wins, as on PostgreSQL.
PHOTO_DIGEST_CODE = (
    PRELUDE
    + """
import hashlib
import uuid
from employees.images import attach_photo_digests
from employees.models import Employee
from macs.models import EmployeePhoto

with_photo_ids = EmployeePhoto.objects.values("employee_id")
single, none = list(Employee.objects.exclude(pk__in=with_photo_ids).order_by("pk")[:2])
jpeg_start = bytes([255, 216, 255])  # JPEG signature, written as numbers
first = jpeg_start + uuid.uuid4().bytes  # created first, so the lower id: this one must win
second = jpeg_start + uuid.uuid4().bytes
EmployeePhoto.objects.create(employee=single, data=first)
EmployeePhoto.objects.create(employee=single, data=second)
attach_photo_digests([single, none])
print("RESULT " + json.dumps({
    "single": single._photo_md5,
    "none": none._photo_md5,
    "expected": hashlib.md5(first, usedforsecurity=False).hexdigest(),
}))
"""
)


def test_photo_digest_list_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, PHOTO_DIGEST_CODE)
    assert data["single"] == data["expected"], data
    assert data["none"] == "", data


# Task 11, fix B: the hire form's duplicate check on Firebird compares normalised numbers in Python (no REGEXP_REPLACE).
# A stored number may hold spaces between the letters and the digits, or inside the digits, and must still block.
REGISTER_CODE = (
    PRELUDE
    + """
import uuid
from django.core.exceptions import ValidationError
from employees.forms import EmployeeForm
from employees.models import Employee
from macs.models import EmployeePhoto

MSG = "Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй."
with_photo_ids = EmployeePhoto.objects.values("employee_id")
stored_emp = list(Employee.objects.exclude(pk__in=with_photo_ids).order_by("pk")[:1])[0]
digits = f"{uuid.uuid4().int % 10**8:08d}"
other_digits = f"{(int(digits) + 1) % 10**8:08d}"


def clean(value, employee=None):
    form = EmployeeForm({}, employee=employee)
    form.cleaned_data = {"register_no": value}
    try:
        return form.clean_register_no()
    except ValidationError as exc:
        return "error:" + exc.messages[0]


Employee.objects.filter(pk=stored_emp.pk).update(register_no=f"уб {digits}")
plain = clean(f"УБ{digits}")
Employee.objects.filter(pk=stored_emp.pk).update(register_no=f"уб {digits[:4]} {digits[4:]}")
inside = clean(f"УБ{digits}")
self_edit = clean(f"УБ{digits}", employee=stored_emp)
different = clean(f"УБ{other_digits}")
print("RESULT " + json.dumps({
    "msg": MSG,
    "plain": plain,
    "inside": inside,
    "self_edit": self_edit,
    "different": different,
    "expected_different": f"УБ{other_digits}",
    "expected_self": f"УБ{digits}",
}))
"""
)


def test_register_duplicate_check_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, REGISTER_CODE)
    assert data["plain"] == "error:" + data["msg"], data  # "уб 99112233" stored, "УБ99112233" typed
    assert data["inside"] == "error:" + data["msg"], data  # a space inside the digits does not hide the clash
    assert data["self_edit"] == data["expected_self"], data  # editing the same employee is accepted
    assert data["different"] == data["expected_different"], data


# Task 12: the checklist tick, untick, cancel and cancel_open lock one table each. Firebird refuses FOR UPDATE on a join
# ("WITH LOCK can be used only with a single physical table"), so each call below runs one of the four locking sites.
CHECKLIST_CODE = (
    PRELUDE
    + """
import uuid
from datetime import date
from accounts.models import User
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask
from checklists.services import lifecycle
from macs.models import Employee

tag = uuid.uuid4().hex[:6]
admin = User.objects.create_user(f"chk_fb_{tag}", password="x-long-pass-123")
emp = (
    Employee.objects.exclude(
        pk__in=Checklist.objects.filter(kind=ChecklistKind.ONBOARDING, state=ChecklistState.OPEN).values("employee_id")
    )
    .order_by("pk")
    .first()
)
ANCHOR = date(2026, 12, 1)
out = {"started": False}
checklist = lifecycle.start(emp, ChecklistKind.ONBOARDING, reason=None, anchor_day=ANCHOR, by=admin)
out["started"] = checklist is not None
required = list(checklist.tasks.filter(required=True).order_by("position", "pk"))
out["required_count"] = len(required)
first_pk = required[0].pk


def task_done(pk):
    return ChecklistTask.objects.get(pk=pk).done_at is not None


def state_of(checklist):
    return Checklist.objects.get(pk=checklist.pk).state


# Site 1 (tick) and site 2 (untick, on an open checklist).
lifecycle.tick(ChecklistTask.objects.get(pk=first_pk), by=admin)
out["tick_done"] = task_done(first_pk)
out["tick_state"] = state_of(checklist)
lifecycle.untick(ChecklistTask.objects.get(pk=first_pk), by=admin)
out["untick_done"] = task_done(first_pk)
# Finish the onboarding with the required ticks, then untick one: the checklist reopens (site 2 on a completed one).
for task in required:
    lifecycle.tick(ChecklistTask.objects.get(pk=task.pk), by=admin)
out["completed_state"] = state_of(checklist)
lifecycle.untick(ChecklistTask.objects.get(pk=first_pk), by=admin)
out["reopened_state"] = state_of(checklist)
# Site 3 (cancel).
lifecycle.cancel(Checklist.objects.get(pk=checklist.pk), by=admin)
out["cancelled_state"] = state_of(checklist)
# Site 4 (cancel_open) on a fresh open checklist of the same kind.
again = lifecycle.start(emp, ChecklistKind.ONBOARDING, reason=None, anchor_day=ANCHOR, by=admin)
out["again_is_new"] = again is not None and again.pk != checklist.pk
cancelled = lifecycle.cancel_open(emp, ChecklistKind.ONBOARDING, by=admin, reason="тест")
out["cancel_open_state"] = None if cancelled is None else cancelled.state
print("RESULT " + json.dumps(out))
"""
)


def test_checklist_lifecycle_locks_one_table_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, CHECKLIST_CODE)
    assert data["started"] is True, data
    assert data["required_count"] > 0, data
    assert data["tick_done"] is True and data["tick_state"] == "open", data
    assert data["untick_done"] is False, data
    assert data["completed_state"] == "completed", data
    assert data["reopened_state"] == "open", data
    assert data["cancelled_state"] == "cancelled", data
    assert data["again_is_new"] is True, data
    assert data["cancel_open_state"] == "cancelled", data


# Plan 5, task 5b: the folded change_text column on both log tables.
CHANGE_TEXT_CODE = (
    PRELUDE  # noqa: S608 (ruff reports the SQL inside this fixed test literal)
    + """
import uuid
from accounts.models import SystemLogEntry
from employees.models import ActivityEntry, ActivityKind
from macs.models import Employee
from logs.foldtext import backfill

tag = uuid.uuid4().hex[:6]
emp = Employee.objects.order_by("pk").first()
activity = ActivityEntry.objects.create(
    employee=emp, kind=ActivityKind.CHANGED, message=f"t5b {tag}",
    changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}],
)
system = SystemLogEntry.objects.create(
    category="test", action="change", changes=[{"field": "Нэр", "old": "Сүхбаатар", "new": None}],
)


def column_exists(model):
    with connection.cursor() as cur:
        cur.execute(
            "select 1 from rdb$relation_fields where rdb$relation_name = %s and rdb$field_name = %s",
            [model._meta.db_table.upper(), "CHANGE_TEXT"],  # Firebird keeps unquoted names upper case
        )
        return cur.fetchone() is not None


print("RESULT " + json.dumps({
    "activity_column": column_exists(ActivityEntry),
    "system_column": column_exists(SystemLogEntry),
    "activity_text": ActivityEntry.objects.get(pk=activity.pk).change_text,
    "system_text": SystemLogEntry.objects.get(pk=system.pk).change_text,
}))
"""
)


def test_change_text_column_exists_and_is_filled_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, CHANGE_TEXT_CODE)
    assert data["activity_column"] is True, data
    assert data["system_column"] is True, data
    assert "сухбаатар" in data["activity_text"] and "баянзурх" in data["activity_text"], data
    assert "сухбаатар" in data["system_text"], data


BACKFILL_CODE = (
    PRELUDE  # noqa: S608 (ruff reports the SQL inside this fixed test literal)
    + """
import uuid
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from employees.models import ActivityEntry, ActivityKind
from macs.models import Employee
from logs.employee_query import EmployeeLogFilter, filtered
from logs.foldtext import backfill

tag = uuid.uuid4().hex[:6]
emp = Employee.objects.order_by("pk").first()
admin = User.objects.create_user(f"bf_fb_{tag}", password="x-long-pass-123")
admin.groups.add(Group.objects.get(name="Admin"))
admin = User.objects.get(pk=admin.pk)
activities = [
    ActivityEntry.objects.create(
        employee=emp, kind=ActivityKind.CHANGED, message=f"t5b {tag}",
        changes=[{"field": "Хэлтэс", "old": "Нягтлан", "new": f"Хэлтэс{i}"}],
    )
    for i in range(5)
]


def found_by_search():
    # The message carries the tag; the Cyrillic word can only come from the stored change text.
    rows = filtered(admin, EmployeeLogFilter(q=f"нягтлан {tag}"))
    return [row.message for row in rows if row.message.endswith(tag)]
systems = [
    SystemLogEntry.objects.create(
        category="test", action="change", changes=[{"field": "Нэр", "old": "Өнөр", "new": f"Үнэн{i}"}],
    )
    for i in range(5)
]


def blank_rows(model):
    return [row for row in model.objects.filter(change_text="") if row.changes]


def blank_out(model, rows):
    # A row written before the column existed: its change_text is blank, its changes are kept.
    ids = [row.pk for row in rows]
    placeholders = ", ".join(["%s"] * len(ids))
    table = connection.ops.quote_name(model._meta.db_table)
    with connection.cursor() as cur:
        cur.execute(f"UPDATE {table} SET change_text = %s WHERE id IN ({placeholders})", ["", *ids])  # noqa: S608


blank_out(ActivityEntry, activities)
blank_out(SystemLogEntry, systems)
out = {"activity_blank_before": len(blank_rows(ActivityEntry)), "system_blank_before": len(blank_rows(SystemLogEntry))}
out["found_before"] = len(found_by_search())
out["activity_written"] = backfill(ActivityEntry, batch=2)
out["system_written"] = backfill(SystemLogEntry, batch=2)
out["found_after"] = len(found_by_search())
out["activity_blank_after"] = len(blank_rows(ActivityEntry))
out["system_blank_after"] = len(blank_rows(SystemLogEntry))
out["activity_texts"] = [ActivityEntry.objects.get(pk=row.pk).change_text for row in activities]
out["system_texts"] = [SystemLogEntry.objects.get(pk=row.pk).change_text for row in systems]
out["activity_changes_kept"] = [ActivityEntry.objects.get(pk=row.pk).changes == row.changes for row in activities]
out["system_changes_kept"] = [SystemLogEntry.objects.get(pk=row.pk).changes == row.changes for row in systems]
print("RESULT " + json.dumps(out))
"""
)


def test_backfill_fills_blank_change_text_in_batches_on_firebird(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, BACKFILL_CODE)
    # Five blanked rows per table, in batches of two (three transactions each); every other row was saved with text.
    assert data["activity_blank_before"] == 5, data
    assert data["system_blank_before"] == 5, data
    assert data["activity_written"] == 5 and data["system_written"] == 5, data
    assert data["activity_blank_after"] == 0 and data["system_blank_after"] == 0, data
    assert data["found_before"] == 0, data  # a row with blank change text is not found by its changed value
    assert data["found_after"] == 5, data  # ...and all five are found once the backfill has run
    assert data["activity_texts"] == [f"хэлтэс нягтлан хэлтэс{i}" for i in range(5)], data
    assert data["system_texts"] == [f"нэр онор унэн{i}" for i in range(5)], data
    assert all(data["activity_changes_kept"]) and all(data["system_changes_kept"]), data

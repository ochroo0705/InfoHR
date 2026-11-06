"""CHAR values read through the ORM lose their trailing spaces (plan 3, Task 2).

Firebird pads CHAR columns with spaces to their declared length, so EMPLOYEE.STATUS reads back as 'active  '.
``DatabaseOperations.get_db_converters`` trims trailing spaces from every ``CharField`` value on read. Writes are not
padded by Python, and raw cursor results are unchanged.

Accepted effect: trailing spaces are never meaningful in HR text, so a VARCHAR value saved with a trailing space
(``ChecklistTemplate.name = "x "``) also reads back trimmed. ``TextField`` values keep their value.
"""

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PADDING_CODE = """
import json
import django
django.setup()
from django.db import connection
from checklists.models import ChecklistKind, ChecklistTemplate
from macs.models import Employee
employee = Employee(
    family_name="Т", given_name="Б", gender="M", hr_flag="no", sector_years=0, emptype=1,
    status="active", contract_flag="no",
)
employee.save(force_insert=True)
fresh = Employee.objects.get(pk=employee.pk)
matched = list(Employee.objects.filter(status="active", pk=employee.pk).values_list("pk", flat=True))
template = ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="x ", reasons=[])
fresh_template = ChecklistTemplate.objects.get(pk=template.pk)
with connection.cursor() as cursor:
    cursor.execute(
        f"SELECT status FROM {Employee._meta.db_table} WHERE {Employee._meta.pk.column} = %s", [employee.pk],
    )
    raw_status = cursor.fetchone()[0]
print("RESULT " + json.dumps({
    "status": fresh.status,
    "contract_flag": fresh.contract_flag,
    "filter_matches": matched == [employee.pk],
    "raw_status": raw_status,
    "template_name": fresh_template.name,
    "template_name_stored": template.name,
}))
"""


def test_orm_read_trims_char_padding_and_filter_still_matches(migrated_clone: str) -> None:
    """A CHAR status read through the ORM comes back as 'active'; an ORM filter on 'active' still matches the padded row.

    The raw cursor is checked too: the converter must not change raw results. Only the ORM path is trimmed.
    Assertions on ``raw_status`` expect the padded value (Firebird CHAR pads to the declared length).
    """
    data = result_of(run_django(PADDING_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["status"] == "active"
    assert data["contract_flag"] == "no"
    assert data["filter_matches"] is True
    assert data["raw_status"].rstrip(" ") == "active"


def test_orm_read_of_varchar_with_trailing_space_is_trimmed(migrated_clone: str) -> None:
    """Accepted effect (see module docstring): ChecklistTemplate.name = "x " reads back as "x".

    The in-memory object keeps "x " (template_name_stored); only the value read from the database is trimmed.
    """
    data = result_of(run_django(PADDING_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["template_name_stored"] == "x "
    assert data["template_name"] == "x"

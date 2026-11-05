from employees.forms import EmployeeForm, SalaryInsuranceForm
from employees.models import JobRecord

from assistant.fields import EXCLUDED, AskableField, all_fields, field_by_key, hints_for


def _field(key: str) -> AskableField:
    found = field_by_key(key)
    assert found is not None, key
    return found


def _page_names() -> set[str]:
    """Every field name the employee pages and the job record can show."""
    names = set(EmployeeForm(employee=None, user=None).fields)
    names |= set(SalaryInsuranceForm(employee=None).fields)
    names |= set(JobRecord.JOB_FIELDS)
    return names


def test_every_page_field_is_registered_or_excluded() -> None:
    registered = {field.key for field in all_fields()}
    for name in _page_names():
        assert name in registered or name in EXCLUDED, name
    assert "base_salary" in registered
    assert _field("base_salary").source == "salary"


def test_excluded_names_are_not_registered() -> None:
    registered = {field.key for field in all_fields()}
    assert not registered & set(EXCLUDED)
    assert "photo" in EXCLUDED
    assert "photo_clear" in EXCLUDED


def test_work_tab_codes_left_out_have_a_reason() -> None:
    # emptype (a type code no page shows) and status (one value per job row) are excluded, each with its reason.
    for name in ("emptype", "status"):
        assert name in EXCLUDED, name
        assert EXCLUDED[name].strip(), name
        assert field_by_key(name) is None, name
    assert _field("employee_type").tab == "work"


def test_edit_page_only_fields_are_registered() -> None:
    # Shown on the employee page once a person exists, so the empty form above does not list them.
    for name in ("code", "branch", "foreign_emp", "sector_years"):
        _field(name)
    assert _field("code").tab == "work"
    assert _field("sector_years").tab == "work"
    assert _field("foreign_emp").tab == "personal"  # listed under the personal identity section


def test_tabs() -> None:
    assert _field("private_phone").tab == "personal"
    assert _field("work_phone").tab == "work"
    assert _field("account_no").tab == "salary"
    assert _field("position").source == "job"


def test_hints_for_matches_by_label_and_synonym() -> None:
    keys = [field.key for field in hints_for("Батын утасны дугаар")]
    assert "private_phone" in keys
    assert "work_phone" in keys
    assert hints_for("zzz") == []


def test_hints_never_exceed_limit() -> None:
    assert len(hints_for("утас", limit=2)) <= 2
    assert len(hints_for("утас")) > 2


def test_labels_are_not_empty() -> None:
    for field in all_fields():
        assert field.label.strip(), field.key

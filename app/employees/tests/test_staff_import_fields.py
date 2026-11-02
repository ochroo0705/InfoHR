from datetime import date, timedelta

from macs.models import Employee

from employees.staff_import.derive import derive_from_register
from employees.staff_import.fields import BY_KEY, FIELD_KINDS, FIELDS, normalize_heading

SALARY_KEYS = {
    "base_salary",
    "bank",
    "account_no",
    "social_insurance_no",
    "health_insurance_no",
    "taxpayer_no",
    "insured_category",
}
ALLOWED_LOOKUPS = {"department", "position", "branch", "country", "bank", "insured", "work_conditions"}
# Skipped by the attribute check: `start` is Employee.first_hire_date (a different name), `department` and
# `position` are skipped as the review asked, and `base_salary` is SalaryRecord.base_salary; Employee has `salary`.
NOT_EMPLOYEE_ATTRIBUTES = {"start", "department", "position", "base_salary"}


def _register_for(born: date, gender_digit: int) -> str:
    """Build a register number ("УБ" + YY MM DD G C) for a birth date; the month gets +20 for 2000 or later."""
    month = born.month + (20 if born.year >= 2000 else 0)
    return f"УБ{born.year % 100:02d}{month:02d}{born.day:02d}{gender_digit}0"


def test_derive_1900s_register_number() -> None:
    assert derive_from_register("УБ99112233") == (date(1999, 11, 22), "M")


def test_derive_2000s_register_number_month_above_20() -> None:
    assert derive_from_register("УБ05211104") == (date(2005, 1, 11), "F")


def test_derive_invalid_month_is_rejected() -> None:
    assert derive_from_register("УБ99133233") == (None, None)


def test_derive_month_20_in_1900s_is_rejected() -> None:
    assert derive_from_register("УБ99201234") == (None, None)


def test_derive_invalid_day_in_2000s_is_rejected() -> None:
    assert derive_from_register("УБ05233201") == (None, None)


def test_derive_non_register_text_is_rejected() -> None:
    assert derive_from_register("abc") == (None, None)


def test_derive_future_birth_date_is_rejected() -> None:
    tomorrow = date.today() + timedelta(days=1)
    assert derive_from_register(_register_for(tomorrow, 3)) == (None, None)


def test_derive_birth_date_today_is_accepted() -> None:
    today = date.today()
    assert derive_from_register(_register_for(today, 4)) == (today, "F")


def test_derive_birth_date_in_the_past_is_accepted() -> None:
    born = date(2001, 6, 15)
    assert derive_from_register(_register_for(born, 7)) == (born, "M")


def test_normalize_heading_trims_lowercases_and_drops_punctuation() -> None:
    assert normalize_heading("  Регистрийн  дугаар: ") == "регистрийн дугаар"
    assert normalize_heading("№ Овог.") == "овог"
    assert normalize_heading(None) == ""


def test_normalize_heading_collapses_spaces_around_slash() -> None:
    assert normalize_heading("Эцэг / эхийн нэр") == "эцэг/эхийн нэр"
    assert normalize_heading("Эцэг/ эхийн   нэр") == "эцэг/эхийн нэр"


def test_every_alias_is_normalised() -> None:
    for field in FIELDS:
        for alias in field.aliases:
            assert alias == normalize_heading(alias), (field.key, alias)


def test_no_alias_is_shared_between_fields() -> None:
    seen: dict[str, str] = {}
    for field in FIELDS:
        for alias in field.aliases:
            assert alias not in seen, (alias, seen.get(alias), field.key)
            seen[alias] = field.key


def test_by_key_has_every_field_and_salary_gating_is_exact() -> None:
    expected_keys = {
        "family_name",
        "given_name",
        "register_no",
        "passport_no",
        "birth_date",
        "gender",
        "work_phone",
        "private_phone",
        "email",
        "start",
        "department",
        "position",
        "branch",
        "citizenship",
        "work_conditions",
        "base_salary",
        "bank",
        "account_no",
        "social_insurance_no",
        "health_insurance_no",
        "taxpayer_no",
        "insured_category",
    }
    assert set(BY_KEY) == expected_keys
    assert len(FIELDS) == len(expected_keys)
    assert {key for key, field in BY_KEY.items() if field.needs_salary} == SALARY_KEYS


def test_every_kind_is_allowed_and_lookups_are_known() -> None:
    for field in FIELDS:
        assert field.kind in FIELD_KINDS, field.key
        if field.lookup is not None:
            assert field.lookup in ALLOWED_LOOKUPS, field.key
            assert field.kind == "text", field.key


def test_field_keys_match_employee_attributes() -> None:
    for field in FIELDS:
        if field.key in NOT_EMPLOYEE_ATTRIBUTES:
            continue
        assert hasattr(Employee, field.key), field.key


def test_gender_is_the_second_to_last_digit() -> None:
    """YY MM DD G C: the gender digit is the seventh of the eight digits, not the last one."""
    assert derive_from_register("УБ99112230") == (date(1999, 11, 22), "M")  # 3 odd -> M, last 0 even
    assert derive_from_register("УБ99112207") == (date(1999, 11, 22), "F")  # 0 even -> F, last 7 odd


def test_template_example_uses_a_valid_work_condition_and_no_guessed_lookups() -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    from employees.staff_import.template import template_bytes
    from employees.staff_import.views import WORK_CONDITION_CHOICES

    sheet = load_workbook(BytesIO(template_bytes(include_salary=True))).active
    assert sheet is not None
    example = {
        sheet.cell(row=1, column=c).value: sheet.cell(row=2, column=c).value for c in range(1, sheet.max_column + 1)
    }
    assert example[BY_KEY["work_conditions"].label] in WORK_CONDITION_CHOICES
    for key in ("branch", "citizenship", "bank", "insured_category"):
        assert example[BY_KEY[key].label] is None

from datetime import date, datetime
from decimal import Decimal

import pytest

from employees.staff_import.rows import DATE_FORMATS, MAX_LENGTH, ParsedRow, parse_row

REGISTER_LABEL = "Регистр эсвэл паспортын дугаар дутуу байна"

# A complete, valid row. A test changes one cell by passing it as a keyword; None means an empty cell.
BASE: dict[str, object] = {
    "family_name": "Бат",
    "given_name": "Дорж",
    "register_no": "УБ99112233",
    "start": "2026-03-01",
    "department": "Санхүү",
    "position": "Нягтлан",
}


def _parse(date_format: str = "iso", defaults: dict[str, str] | None = None, **changes: object) -> ParsedRow:
    data = {**BASE, **changes}
    keys = list(data)
    mapping = {str(index): key for index, key in enumerate(keys)}
    return parse_row(1, [data[key] for key in keys], mapping, defaults or {}, date_format)


def test_date_formats_are_the_three_offered_choices() -> None:
    assert DATE_FORMATS == {
        "iso": ("yyyy-mm-dd", "%Y-%m-%d"),
        "slash": ("yyyy/mm/dd", "%Y/%m/%d"),
        "dmy": ("dd.mm.yyyy", "%d.%m.%Y"),
    }


def test_text_limits_are_read_from_the_employee_model() -> None:
    assert MAX_LENGTH["given_name"] == 25
    assert MAX_LENGTH["work_phone"] == 14
    assert MAX_LENGTH["register_no"] == 20
    assert all(isinstance(limit, int) for limit in MAX_LENGTH.values())


def test_number_typed_phone_becomes_text_without_decimal_point() -> None:
    row = _parse(work_phone=99112233.0)

    assert row.errors == []
    assert row.values["work_phone"] == "99112233"


def test_date_text_in_chosen_format_is_accepted() -> None:
    row = _parse(date_format="slash", start="2026/03/01")

    assert row.errors == []
    assert row.values["start"] == date(2026, 3, 1)


def test_date_text_in_other_format_is_an_error() -> None:
    row = _parse(date_format="slash", start="2026-03-01")

    assert row.errors == ["Анх ажилд орсон огноо буруу байна (yyyy/mm/dd хэлбэрээр бичнэ үү)"]
    assert "start" not in row.values


def test_excel_datetime_is_accepted() -> None:
    row = _parse(start=datetime(2026, 3, 1, 0, 0))

    assert row.errors == []
    assert row.values["start"] == date(2026, 3, 1)


def test_serial_number_in_date_cell_is_an_error_not_a_crash() -> None:
    row = _parse(start=46082)

    assert len(row.errors) == 1
    assert row.errors[0].startswith("Анх ажилд орсон огноо буруу байна")


def test_text_that_is_not_a_date_is_an_error() -> None:
    row = _parse(start="хэзээ нэгэн цагт")

    assert len(row.errors) == 1
    assert row.errors[0].startswith("Анх ажилд орсон огноо буруу байна")


def test_given_name_longer_than_column_is_an_error_naming_the_field() -> None:
    row = _parse(given_name="А" * 26)

    assert row.errors == ["Нэр хэт урт байна (дээд тал 25 тэмдэгт)"]
    assert "given_name" not in row.values


def test_phone_longer_than_column_is_an_error() -> None:
    row = _parse(work_phone="1" * 15)

    assert row.errors == ["Ажлын утас хэт урт байна (дээд тал 14 тэмдэгт)"]


def test_phone_keeps_digits_plus_minus_and_spaces() -> None:
    row = _parse(private_phone="+976 9911-2233")

    assert row.errors == []
    assert row.values["private_phone"] == "+976 9911-2233"


def test_phone_with_other_characters_is_an_error() -> None:
    row = _parse(private_phone="7711 2233 (x)")

    assert row.errors == ["Хувийн утас буруу байна (зөвхөн тоо, +, - болон зай)"]


def test_register_number_is_normalised() -> None:
    row = _parse(register_no=" уб 99112233 ")

    assert row.errors == []
    assert row.values["register_no"] == "УБ99112233"


def test_invalid_register_number_is_an_error() -> None:
    row = _parse(register_no="УБ9911223")

    assert len(row.errors) == 1
    assert "register_no" not in row.values


def test_passport_number_is_upper_cased_without_spaces() -> None:
    row = _parse(register_no=None, passport_no="ab 123 4567", birth_date="1990-01-01", gender="M")

    assert row.errors == []
    assert row.values["passport_no"] == "AB1234567"


def test_birth_date_and_gender_are_derived_from_register_number() -> None:
    row = _parse(register_no="УБ99112233")

    assert row.errors == []
    assert row.values["birth_date"] == date(1999, 11, 22)
    assert row.values["gender"] == "M"


def test_explicit_gender_beats_the_derived_one() -> None:
    row = _parse(gender="эмэгтэй")

    assert row.errors == []
    assert row.values["gender"] == "F"


def test_explicit_birth_date_beats_the_derived_one() -> None:
    row = _parse(birth_date="1980-05-05")

    assert row.errors == []
    assert row.values["birth_date"] == date(1980, 5, 5)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("эрэгтэй", "M"),
        ("эр", "M"),
        ("male", "M"),
        ("M", "M"),
        ("ЭМЭГТЭЙ", "F"),
        ("эм", "F"),
        ("female", "F"),
        ("f", "F"),
    ],
)
def test_gender_words_and_letters_are_accepted(text: str, code: str) -> None:
    row = _parse(gender=text)

    assert row.errors == []
    assert row.values["gender"] == code


def test_unknown_gender_text_is_an_error() -> None:
    row = _parse(gender="хэзээ")

    assert len(row.errors) == 1
    assert row.errors[0].startswith("Хүйс буруу байна")


def test_row_with_only_passport_needs_birth_date_and_gender() -> None:
    row = _parse(register_no=None, passport_no="AB1234567")

    assert row.errors == ["Төрсөн огноо дутуу байна", "Хүйс дутуу байна"]


def test_row_with_neither_register_nor_passport_has_one_error() -> None:
    row = _parse(register_no=None)

    assert row.errors == [REGISTER_LABEL]


def test_defaults_never_fill_register_or_passport() -> None:
    row = _parse(
        register_no=None,
        passport_no=None,
        defaults={"register_no": "УБ99112233", "passport_no": "AB1234567"},
    )

    assert row.errors == [REGISTER_LABEL]
    assert "register_no" not in row.values
    assert "passport_no" not in row.values


def test_unknown_default_key_is_ignored() -> None:
    row = _parse(defaults={"nationality": "Монгол"})

    assert row.errors == []
    assert "nationality" not in row.values


def test_salary_text_with_spaces_becomes_decimal() -> None:
    row = _parse(base_salary="2 500 000")

    assert row.errors == []
    assert row.values["base_salary"] == Decimal("2500000")


def test_salary_text_with_commas_becomes_decimal() -> None:
    row = _parse(base_salary="2,500,000")

    assert row.values["base_salary"] == Decimal("2500000")


def test_negative_salary_is_an_error() -> None:
    row = _parse(base_salary="-5")

    assert row.errors == ["Цалин сөрөг байж болохгүй"]
    assert "base_salary" not in row.values


def test_salary_that_is_not_a_number_is_an_error() -> None:
    row = _parse(base_salary="много")

    assert row.errors == ["Цалин буруу байна (зөвхөн тоо)"]


def test_email_without_dot_after_at_is_an_error() -> None:
    row = _parse(email="a@b")

    assert row.errors == ["И-мэйл буруу байна"]


def test_valid_email_is_kept() -> None:
    row = _parse(email="a@b.mn")

    assert row.errors == []
    assert row.values["email"] == "a@b.mn"


def test_missing_family_name_is_an_error() -> None:
    row = _parse(family_name=None)

    assert row.errors == ["Эцэг/эхийн нэр дутуу байна"]


def test_missing_start_date_and_position_are_each_an_error() -> None:
    row = _parse(start=None, position=None)

    assert row.errors == ["Анх ажилд орсон огноо дутуу байна", "Албан тушаал дутуу байна"]


def test_department_from_default_fills_empty_column() -> None:
    row = _parse(department=None, defaults={"department": "Бусад"})

    assert row.errors == []
    assert row.values["department"] == "Бусад"


def test_lookup_text_is_kept_stripped_and_unresolved() -> None:
    row = _parse(department="  Санхүү  ", work_conditions=" Үндсэн ")

    assert row.errors == []
    assert row.values["department"] == "Санхүү"
    assert row.values["work_conditions"] == "Үндсэн"


def test_every_problem_in_one_row_is_reported() -> None:
    row = _parse(family_name=None, start="хэзээ нэгэн цагт", email="a@b")

    assert len(row.errors) == 3
    assert row.errors[0] == "Эцэг/эхийн нэр дутуу байна"
    assert row.errors[1] == "И-мэйл буруу байна"
    assert row.errors[2].startswith("Анх ажилд орсон огноо буруу байна")


def test_default_birth_date_does_not_beat_register_derivation() -> None:
    row = _parse(defaults={"birth_date": "1980-01-01"})

    assert row.errors == []
    assert row.values["birth_date"] == date(1999, 11, 22)


def test_default_gender_is_ignored() -> None:
    row = _parse(defaults={"gender": "F"})

    assert row.errors == []
    assert row.values["gender"] == "M"


def test_default_fills_a_blank_department_cell() -> None:
    row = _parse(department="   ", defaults={"department": "Бусад"})

    assert row.errors == []
    assert row.values["department"] == "Бусад"


@pytest.mark.parametrize("text", ["2,5", "1e3", "1_000", "12,34", "1,0000"])
def test_money_forms_other_than_plain_or_grouped_digits_are_errors(text: str) -> None:
    row = _parse(base_salary=text)

    assert row.errors == ["Цалин буруу байна (зөвхөн тоо)"]
    assert "base_salary" not in row.values


@pytest.mark.parametrize(
    ("text", "amount"), [("2,500,000", "2500000"), ("2 500 000", "2500000"), ("2,500,000.50", "2500000.50")]
)
def test_money_grouped_forms_are_accepted(text: str, amount: str) -> None:
    row = _parse(base_salary=text)

    assert row.errors == []
    assert row.values["base_salary"] == Decimal(amount)


def test_bool_cell_in_text_field_is_an_error_not_true() -> None:
    row = _parse(family_name=True)

    assert row.errors == ["Эцэг/эхийн нэр буруу байна"]
    assert "family_name" not in row.values


def test_unknown_date_format_falls_back_to_iso() -> None:
    row = _parse(date_format="bogus", start="2026-03-01")

    assert row.errors == []
    assert row.values["start"] == date(2026, 3, 1)


def test_negative_mapping_position_is_ignored_not_read_from_the_end() -> None:
    row = parse_row(1, ["Бат"], {"-1": "family_name"}, {}, "iso")

    assert "Эцэг/эхийн нэр дутуу байна" in row.errors
    assert "family_name" not in row.values


def test_register_that_gives_no_date_needs_birth_date_and_gender_from_file() -> None:
    row = _parse(register_no="УБ99133233")

    assert row.errors == ["Төрсөн огноо дутуу байна", "Хүйс дутуу байна"]


def test_register_that_gives_no_date_keeps_explicit_birth_date_and_gender() -> None:
    row = _parse(register_no="УБ99133233", birth_date="1990-02-03", gender="эмэгтэй")

    assert row.errors == []
    assert row.values["birth_date"] == date(1990, 2, 3)
    assert row.values["gender"] == "F"


def test_register_that_gives_no_date_with_explicit_birth_date_needs_only_gender() -> None:
    row = _parse(register_no="УБ99133233", birth_date="1990-02-03")

    assert row.errors == ["Хүйс дутуу байна"]
    assert row.values["birth_date"] == date(1990, 2, 3)


def test_non_integer_mapping_key_is_ignored_not_a_crash() -> None:
    row = parse_row(1, ["Бат"], {"x": "given_name", "0": "family_name"}, {}, "iso")

    assert row.values["family_name"] == "Бат"
    assert "given_name" not in row.values


def test_non_string_default_is_coerced_to_text() -> None:
    row = _parse(department=None, defaults={"department": 12})  # type: ignore[dict-item]

    assert row.errors == []
    assert row.values["department"] == "12"


def test_parsed_row_starts_as_new_with_no_note() -> None:
    row = _parse()

    assert row.number == 1
    assert row.status == "new"
    assert row.note == ""

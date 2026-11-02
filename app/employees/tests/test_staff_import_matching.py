import pytest

from employees.models import StaffImportSettings
from employees.staff_import.matching import auto_match, ignored_salary_headings, missing_required, remember

REGISTER_LABEL = "Регистр эсвэл паспортын дугаар"


def test_known_headings_map_to_their_fields() -> None:
    mapping = auto_match(["Овог", "Нэр", "Регистр", "Утас"], remembered={}, allow_salary=False)

    assert mapping == {"0": "family_name", "1": "given_name", "2": "register_no", "3": "private_phone"}


def test_unknown_heading_is_left_out() -> None:
    mapping = auto_match(["Овог", "Col7"], remembered={}, allow_salary=False)

    assert mapping == {"0": "family_name"}


def test_field_is_assigned_to_first_column_only() -> None:
    mapping = auto_match(["Нэр", "Name"], remembered={}, allow_salary=False)

    assert mapping == {"0": "given_name"}


def test_salary_column_is_dropped_when_salary_not_allowed() -> None:
    headings = ["Овог", "Цалин"]

    assert auto_match(headings, remembered={}, allow_salary=False) == {"0": "family_name"}
    assert ignored_salary_headings(headings, remembered={}) == ["Цалин"]


def test_salary_column_is_mapped_when_salary_allowed() -> None:
    mapping = auto_match(["Цалин"], remembered={}, allow_salary=True)

    assert mapping == {"0": "base_salary"}
    assert ignored_salary_headings(["Цалин"], remembered={}) == ["Цалин"]


def test_ignored_salary_headings_skips_plain_columns() -> None:
    assert ignored_salary_headings(["Овог", "Нэр"], remembered={}) == []


def test_empty_normalised_heading_matches_nothing() -> None:
    assert auto_match(["", "Col7"], remembered={"": "work_phone", "col7": "email"}, allow_salary=False) == {
        "1": "email"
    }


@pytest.mark.django_db
def test_remembered_mapping_wins_for_a_nonsense_heading() -> None:
    settings = StaffImportSettings.get()
    headings = ["Овог", "Col7"]
    remember(settings, headings, {"0": "family_name", "1": "work_phone"}, {}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"овог": "family_name", "col7": "work_phone"}
    assert auto_match(headings, remembered=settings.mapping, allow_salary=False) == {
        "0": "family_name",
        "1": "work_phone",
    }


@pytest.mark.django_db
def test_remember_stores_defaults_and_date_format() -> None:
    settings = StaffImportSettings.get()
    remember(settings, ["Овог"], {"0": "family_name"}, {"department": "Санхүү"}, "dmy")
    settings.refresh_from_db()

    assert settings.defaults == {"department": "Санхүү"}
    assert settings.date_format == "dmy"


@pytest.mark.django_db
def test_remember_skips_out_of_range_negative_and_unknown_entries() -> None:
    settings = StaffImportSettings.get()
    headings = ["Овог", "Нэр"]
    remember(settings, headings, {"0": "family_name", "2": "email", "-1": "email", "1": "no_such_key"}, {}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"овог": "family_name"}


@pytest.mark.django_db
def test_remember_first_column_wins_for_identical_normalised_headings() -> None:
    settings = StaffImportSettings.get()
    headings = ["Овог", "Овог:"]
    remember(settings, headings, {"0": "family_name", "1": "given_name"}, {}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"овог": "family_name"}


@pytest.mark.django_db
def test_remember_does_not_store_blank_defaults() -> None:
    settings = StaffImportSettings.get()
    remember(
        settings, ["Овог"], {"0": "family_name"}, {"department": "  ", "position": "Инженер", "citizenship": ""}, "iso"
    )
    settings.refresh_from_db()

    assert settings.defaults == {"position": "Инженер"}


@pytest.mark.django_db
def test_empty_normalised_heading_is_not_remembered() -> None:
    settings = StaffImportSettings.get()
    remember(settings, [" : ", "Овог"], {"0": "given_name", "1": "family_name"}, {}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"овог": "family_name"}


def test_missing_required_lists_all_labels_for_empty_mapping() -> None:
    assert missing_required({}, {}) == [
        "Эцэг/эхийн нэр",
        "Нэр",
        "Анх ажилд орсон огноо",
        "Хэлтэс",
        "Албан тушаал",
        REGISTER_LABEL,
    ]


def test_missing_required_is_empty_for_full_mapping_with_default_department() -> None:
    mapping = {"0": "family_name", "1": "given_name", "2": "register_no", "3": "start", "4": "position"}

    assert missing_required(mapping, {"department": "Санхүү"}) == []


def test_missing_required_counts_a_default_as_supplied_except_for_identity_numbers() -> None:
    mapping = {"0": "family_name", "1": "given_name", "3": "position"}

    # start and department come from a fixed value; register/passport never do
    assert missing_required(mapping, {"start": "2026-01-01", "department": "Санхүү"}) == [REGISTER_LABEL]
    assert missing_required(mapping, {"start": "2026-01-01", "department": "Санхүү", "passport_no": "AB1"}) == [
        REGISTER_LABEL
    ]
    assert missing_required(mapping, {"start": "2026-01-01", "department": "  "}) == ["Хэлтэс", REGISTER_LABEL]


def test_missing_required_accepts_a_mapped_passport_column() -> None:
    mapping = {
        "0": "family_name",
        "1": "given_name",
        "2": "passport_no",
        "3": "start",
        "4": "department",
        "5": "position",
    }

    assert missing_required(mapping, {}) == []


@pytest.mark.django_db
def test_remember_keeps_entries_other_users_saved() -> None:
    """The settings row is shared: an HR save must not drop the salary entries an Admin saved."""
    settings = StaffImportSettings.get()
    settings.mapping = {"цалин": "base_salary", "овог": "family_name"}
    settings.defaults = {"citizenship": "Монгол"}
    settings.save()
    remember(settings, ["Нэр"], {"0": "given_name"}, {"department": "Санхүү"}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"цалин": "base_salary", "овог": "family_name", "нэр": "given_name"}
    assert settings.defaults == {"citizenship": "Монгол", "department": "Санхүү"}


@pytest.mark.django_db
def test_remember_replaces_only_the_same_heading() -> None:
    settings = StaffImportSettings.get()
    settings.mapping = {"овог": "family_name", "цалин": "base_salary"}
    settings.save()
    remember(settings, ["Овог"], {"0": "given_name"}, {}, "iso")
    settings.refresh_from_db()

    assert settings.mapping == {"овог": "given_name", "цалин": "base_salary"}


@pytest.mark.django_db
def test_remember_blank_default_does_not_clear_a_remembered_one() -> None:
    settings = StaffImportSettings.get()
    settings.defaults = {"position": "Инженер"}
    settings.save()
    remember(settings, ["Овог"], {"0": "family_name"}, {"position": "  "}, "iso")
    settings.refresh_from_db()

    assert settings.defaults == {"position": "Инженер"}

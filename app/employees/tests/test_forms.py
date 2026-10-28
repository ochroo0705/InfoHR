import json
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from accounts.models import User
from django import forms
from macs.models import (
    Country,
    DisciplineType,
    DriverType,
    ForeignLanguage,
    LanguageLevel,
    MaterialHelpType,
    SpecEduType,
)

from employees.forms import (
    FORMS,
    ArmyRankRowForm,
    BodyRowForm,
    CertificateRowForm,
    ComplaintRowForm,
    DisciplineRowForm,
    DriverRowForm,
    EducationRowForm,
    EmployeeForm,
    HireJobForm,
    JobCorrectionForm,
    LanguageRowForm,
    MaterialHelpRowForm,
    MilitaryRowForm,
    TrainingRowForm,
)
from employees.models import DepartmentExt, Employee
from employees.services import history

from .conftest import hire_values

BASE: dict[str, Any] = {
    "family_name": "Батын",
    "given_name": "Сараа",
    "register_no": "УБ99112233",
    "birth_date": "1999-11-22",
    "gender": "F",
    "work_phone": "99112233",
    "first_hire_date": "2026-01-05",
    "work_conditions": "1",
}


@pytest.mark.django_db
def test_25_cyrillic_letters_fit_26_do_not() -> None:
    assert EmployeeForm({**BASE, "given_name": "Ө" * 25}).is_valid()
    form = EmployeeForm({**BASE, "given_name": "Ө" * 26})
    assert not form.is_valid() and "given_name" in form.errors  # Review Focus 3


@pytest.mark.django_db
def test_register_duplicate_refused_after_normalising(hired: Employee) -> None:
    form = EmployeeForm({**BASE, "register_no": " уб99112233 "})
    assert not form.is_valid() and "register_no" in form.errors  # Review Focus 2


@pytest.mark.django_db
def test_work_conditions_required_and_three_values() -> None:
    assert not EmployeeForm({**BASE, "work_conditions": ""}).is_valid()
    assert EmployeeForm({**BASE, "work_conditions": "3"}).is_valid()


@pytest.mark.django_db
def test_editing_own_record_does_not_trip_duplicate_check(hired: Employee) -> None:
    form = EmployeeForm({**BASE}, employee=hired)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_duplicate_found_when_stored_value_is_unnormalised(hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(register_no="уб 99112233")
    form = EmployeeForm({**BASE, "register_no": "УБ99112233"}, employee=None)
    assert not form.is_valid() and "register_no" in form.errors


@pytest.mark.django_db
def test_editing_other_employee_to_existing_number_is_refused(
    hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    other = history.hire(
        hire_values("УБ11223344"), {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("1"), by=actor
    )
    form = EmployeeForm({**BASE, "register_no": "уб 99112233"}, employee=other)
    assert not form.is_valid() and "register_no" in form.errors


@pytest.mark.django_db
def test_photo_bytes_states(hired: Employee) -> None:
    assert EmployeeForm({**BASE}, employee=hired).is_valid()
    unchanged = EmployeeForm({**BASE}, employee=hired)
    unchanged.is_valid()
    assert unchanged.photo_bytes() is None
    cleared = EmployeeForm({**BASE, "photo_clear": "on"}, employee=hired)
    cleared.is_valid()
    assert cleared.photo_bytes() is False


@pytest.mark.django_db
def test_values_splits_changed_columns_and_ext(hired: Employee) -> None:
    form = EmployeeForm({**BASE, "given_name": "Болд", "prior_service_months": "3"}, employee=hired)
    assert form.is_valid(), form.errors
    columns, ext = form.values()
    assert columns["given_name"] == "Болд"
    assert ext["prior_service_months"] == 3
    assert "family_name" not in columns and "prior_service_months" not in columns


@pytest.mark.django_db
def test_inactive_department_not_offered_on_hire_but_kept_on_correction(
    hired: Employee, job_values: dict[str, Any]
) -> None:
    old = job_values["department"]
    DepartmentExt.objects.filter(department=old).update(active=False)
    assert old not in HireJobForm().fields["department"].queryset  # type: ignore[attr-defined]
    record = hired.job_records.get()
    assert old in JobCorrectionForm(instance=record).fields["department"].queryset  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_malformed_register_number_is_refused_with_field_error() -> None:
    form = EmployeeForm({**BASE, "register_no": "12345"})
    assert not form.is_valid() and "register_no" in form.errors


# --- Personal tab: education row (qualification, production) ---


def _edu(**extra: Any) -> dict[str, Any]:
    return {"org_name": "МУИС", "start_year": "2005", "end_year": "2009", **extra}


@pytest.mark.django_db
def test_education_form_country_written_as_id_text() -> None:
    country = Country.objects.create(name="Япон")
    form = EducationRowForm(_edu(country=str(country.pk)))
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["country"] == str(country.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["Монгол", "99999"])
def test_education_form_keeps_unknown_country_text(text: str) -> None:
    # Legacy free text (or an id that no longer exists) is shown blank and must survive an unrelated edit.
    form = EducationRowForm(_edu(loaded_country=json.dumps(text)))
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["country"] == text


@pytest.mark.django_db
def test_education_form_known_country_id_preselected_and_clearing_it_clears() -> None:
    country = Country.objects.create(name="Япон")
    initial = EducationRowForm.from_snapshot(
        {
            "org_name": "МУИС",
            "start_year": 2005,
            "end_year": 2009,
            "country": str(country.pk),
            "edu_level_id": None,
            "grade_id": None,
            "qualification_type_id": None,
            "profession_type_id": None,
            "diplom_number": None,
            "credit_score": None,
            "start_date": None,
            "ending_date": None,
            "employee_id": 1,
        },
        {},
    )
    assert initial["country"] == country.pk
    form = EducationRowForm(_edu(loaded_country=json.dumps(str(country.pk))))  # no country picked now
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["country"] is None


@pytest.mark.django_db
def test_education_form_end_before_start_refused() -> None:
    form = EducationRowForm(_edu(start_year="2009", end_year="2005"))
    assert not form.is_valid() and "end_year" in form.errors
    assert EducationRowForm(_edu(start_year="2005", end_year="2005")).is_valid()


@pytest.mark.django_db
def test_education_form_requires_school_and_years() -> None:
    form = EducationRowForm({})
    assert not form.is_valid()
    assert {"org_name", "start_year", "end_year"} <= set(form.errors)
    assert not {"country", "credit_score", "diplom_number", "grade"} & set(form.errors)


@pytest.mark.django_db
def test_education_form_diplom_max_10_and_credit_score_range() -> None:
    assert EducationRowForm(_edu(diplom_number="1234567890")).is_valid()
    assert "diplom_number" in EducationRowForm(_edu(diplom_number="12345678901")).errors
    assert EducationRowForm(_edu(credit_score="3.5")).is_valid()
    assert EducationRowForm(_edu(credit_score="999.99")).is_valid()  # old rows may sit on another scale
    assert "credit_score" in EducationRowForm(_edu(credit_score="1000")).errors
    assert "credit_score" in EducationRowForm(_edu(credit_score="-0.5")).errors


@pytest.mark.django_db
def test_education_form_lists_are_the_registry_slugs() -> None:
    assert EducationRowForm.LISTS == (
        ("country", "country"),
        ("edu_level", "education"),
        ("profession_type", "profession_type"),
        ("qualification_type", "qualification_type"),
        ("grade", "degree"),
    )


# --- Personal tab: certificate, training and language row forms (Task 6) ---

SNAP_CERT: dict[str, Any] = {
    "employee_id": 1,
    "cert_type_id": 1,
    "org_edu": "Сургууль",
    "certify_number": "C-1",
    "certify_date": date(2010, 1, 2),
    "profession": None,
    "end_date": date(2011, 3, 4),
    "spec_profession": "",
    "certify_year": 2011,
}
SNAP_TRAINING: dict[str, Any] = {
    "employee_id": 1,
    "tr_type": 2,
    "description": "Python",
    "start_date": date(2024, 3, 1),
    "days": None,
    "amount": Decimal("2500000.00"),
    "pay_type": 5,
    "training_center": "Төв",
    "start_year": 2024,
}
SNAP_LANGUAGE: dict[str, Any] = {
    "employee_id": 1,
    "language_id": 1,
    "understand_lvl": "Native",
    "speaking_lvl": None,
    "reading_lvl": "",
    "writing_lvl": "Дунд",
    "description": "Ярианы",
}


def _posted(form_cls: type[Any], snap: dict[str, Any]) -> dict[str, Any]:
    """The loaded_* hidden values a form posts back, as the edit pop-up sends them."""
    initial = form_cls.from_snapshot(snap, {})
    return {k: v for k, v in initial.items() if k.startswith("loaded_")}


@pytest.mark.django_db
def test_certificate_form_values_and_required() -> None:
    cert = SpecEduType.objects.create(name="Жолооч")
    form = CertificateRowForm(
        {
            "cert_type": str(cert.pk),
            "org_edu": "Сургууль",
            "profession": "",
            "spec_profession": "",
            "certify_number": "C-9",
            "certify_date": "2010-01-02",
            "end_date": "",
            "certify_year": "2011",
        }
    )
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["cert_type_id"] == cert.pk
    assert columns["profession"] is None and columns["spec_profession"] is None
    assert columns["certify_year"] == 2011
    assert columns["certify_date"] == date(2010, 1, 2)

    missing = CertificateRowForm({})
    assert not missing.is_valid()
    assert {"cert_type", "org_edu", "certify_year"} <= set(missing.errors)


@pytest.mark.django_db
def test_certificate_loaded_dates_parse_back() -> None:
    form = CertificateRowForm(_posted(CertificateRowForm, SNAP_CERT))
    assert form.snapshot() == SNAP_CERT


@pytest.mark.django_db
def test_training_form_values_and_required() -> None:
    form = TrainingRowForm(
        {
            "tr_type": "1",
            "description": "Python курс",
            "start_year": "2024",
            "start_date": "2024-03-01",
            "days": "5",
            "amount": "2,500,000",
            "pay_type": "3",
            "training_center": "",
        }
    )
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["amount"] == Decimal("2500000")
    assert columns["tr_type"] == 1 and columns["pay_type"] == 3
    assert columns["training_center"] is None

    missing = TrainingRowForm({"tr_type": "", "amount": "", "pay_type": ""})
    assert not missing.is_valid()
    assert {"start_year", "description", "tr_type", "amount", "pay_type"} <= set(missing.errors)


@pytest.mark.django_db
def test_training_form_pay_type_5_allowed() -> None:
    data = {"tr_type": "2", "description": "Курс", "start_year": "2024", "amount": "0", "pay_type": "5"}
    assert TrainingRowForm(data).is_valid()


@pytest.mark.django_db
def test_training_loaded_amount_and_dates_parse_back() -> None:
    form = TrainingRowForm(_posted(TrainingRowForm, SNAP_TRAINING))
    assert form.snapshot() == SNAP_TRAINING


@pytest.mark.django_db
def test_language_form_values_and_required() -> None:
    lang = ForeignLanguage.objects.create(name="Англи")
    LanguageLevel.objects.create(name="Дунд")
    form = LanguageRowForm(
        {
            "language": str(lang.pk),
            "understand_lvl": "Дунд",
            "speaking_lvl": "",
            "reading_lvl": "",
            "writing_lvl": "",
            "description": "",
        }
    )
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["language_id"] == lang.pk
    assert columns["understand_lvl"] == "Дунд"
    assert columns["speaking_lvl"] is None and columns["description"] is None

    assert "language" in LanguageRowForm({}).errors


@pytest.mark.django_db
def test_language_form_keeps_unknown_level() -> None:
    LanguageLevel.objects.create(name="Дунд")
    lang = ForeignLanguage.objects.create(name="Англи")
    form = LanguageRowForm(
        _posted(LanguageRowForm, SNAP_LANGUAGE)
        | {
            "language": str(lang.pk),
            "understand_lvl": "Native",
            "speaking_lvl": "",
            "reading_lvl": "",
            "writing_lvl": "Дунд",
            "description": "Ярианы",
        }
    )
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["understand_lvl"] == "Native"
    assert form.snapshot() == SNAP_LANGUAGE


@pytest.mark.django_db
def test_language_form_stored_unknown_level_is_offered() -> None:
    LanguageLevel.objects.create(name="Дунд")
    initial = LanguageRowForm.from_snapshot(SNAP_LANGUAGE, {})
    form = LanguageRowForm(initial=initial)
    level = cast(forms.ChoiceField, form.fields["understand_lvl"])
    values = [value for value, _ in cast(list[tuple[str, str]], level.choices)]
    assert values == ["", "Дунд", "Native"]


@pytest.mark.django_db
def test_language_form_warns_when_no_levels() -> None:
    assert ("language_level", "Хэлний түвшин") in LanguageRowForm().empty_lists()
    LanguageLevel.objects.create(name="Дунд")
    assert ("language_level", "Хэлний түвшин") not in LanguageRowForm().empty_lists()


def test_row_forms_registered() -> None:
    assert FORMS["certificate"] is CertificateRowForm
    assert FORMS["training"] is TrainingRowForm
    assert FORMS["language"] is LanguageRowForm
    assert FORMS["material_help"] is MaterialHelpRowForm
    assert FORMS["discipline"] is DisciplineRowForm
    assert FORMS["complaint"] is ComplaintRowForm
    assert FORMS["body"] is BodyRowForm
    assert FORMS["driver"] is DriverRowForm
    assert FORMS["military"] is MilitaryRowForm
    assert FORMS["army_rank"] is ArmyRankRowForm


def test_no_dashes_empty_label(hired: Employee) -> None:
    # Placeholder noise: a choice or model field must not render Django's "---------" empty entry.
    form = EmployeeForm(employee=hired)
    for name in ("blood_type", "social_origin"):
        assert "---------" not in str(form[name]), name


@pytest.mark.django_db
def test_material_help_amount_comma_input() -> None:
    material_type = MaterialHelpType.objects.create(name="Эмчилгээ")
    form = MaterialHelpRowForm(
        {
            "material_type": str(material_type.pk),
            "help_date": "2026-01-15",
            "amount": "1,250,000",
            "description": "",
        }
    )
    assert form.is_valid(), form.errors
    columns, _ = form.values()
    assert columns["amount"] == Decimal("1250000")
    assert columns["material_type_id"] == material_type.pk
    assert columns["description"] is None


@pytest.mark.django_db
def test_material_help_form_warns_when_no_types() -> None:
    assert ("material_help_type", "Үндэслэл") in MaterialHelpRowForm().empty_lists()
    MaterialHelpType.objects.create(name="Эмчилгээ")
    assert ("material_help_type", "Үндэслэл") not in MaterialHelpRowForm().empty_lists()


@pytest.mark.django_db
def test_discipline_empty_type_list_shows_notice() -> None:
    assert ("discipline_type", "Шийтгэлийн нэр") in DisciplineRowForm().empty_lists()
    DisciplineType.objects.create(name="Анхааруулга")
    assert ("discipline_type", "Шийтгэлийн нэр") not in DisciplineRowForm().empty_lists()


@pytest.mark.django_db
def test_driver_requires_type() -> None:
    form = DriverRowForm({"number_driver": "1234567", "inserted_ognoo": "2026-03-01"})
    assert not form.is_valid()
    assert "driver_type" in form.errors


@pytest.mark.django_db
def test_driver_empty_type_list_shows_notice() -> None:
    assert ("driver_type", "Жолооны ангилал") in DriverRowForm().empty_lists()
    DriverType.objects.create(name="B ангилал")
    assert ("driver_type", "Жолооны ангилал") not in DriverRowForm().empty_lists()


def test_military_form_every_field_optional() -> None:
    form = MilitaryRowForm({})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["army_rank"] is None
    assert form.cleaned_data["sacking_date"] is None


def test_army_rank_form_every_field_optional() -> None:
    form = ArmyRankRowForm({})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["rank"] is None
    assert form.cleaned_data["rank_date"] is None
    assert form.cleaned_data["addition_r"] is None


def test_body_form_has_all_fields() -> None:
    form = BodyRowForm()
    names = [name for name in form.fields if not name.startswith("loaded_")]
    assert names == [
        "inserted_ognoo",
        "term_type",
        "end_date",
        "own_letter",
        "ear",
        "dotor",
        "medrel",
        "setgel_medrel",
        "mes_zasal",
        "nud",
        "female",
        "rentgen",
        "skin",
        "conclusion",
        "sign",
    ]
    labels = {name: form.fields[name].label for name in names}
    assert labels == {
        "inserted_ognoo": "Үзлэгийн огноо",
        "term_type": "Үзлэгийн төрөл",
        "end_date": "Дуусах хугацаа",
        "own_letter": "Өөрийн мэдүүлэгээр",
        "ear": "Чих хамар хоолой",
        "dotor": "Дотор",
        "medrel": "Мэдрэл",
        "setgel_medrel": "Сэтгэл мэдрэл",
        "mes_zasal": "Мэс засал",
        "nud": "Нүд",
        "female": "Эмэгтэйчүүд",
        "rentgen": "Рентген",
        "skin": "Арьс",
        "conclusion": "Дүгнэлт",
        "sign": "Гарын үсэг",
    }
    for name in (
        "ear",
        "dotor",
        "medrel",
        "setgel_medrel",
        "mes_zasal",
        "nud",
        "female",
        "rentgen",
        "skin",
        "conclusion",
    ):
        assert form.fields[name].widget.attrs.get("rows") == 2, name

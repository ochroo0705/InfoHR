from typing import cast

import pytest
from django import forms
from django.test import Client
from employees.models import Employee
from macs import models as m

from lists.forms import entry_form
from lists.registry import LISTS
from lists.usage import usage_count


@pytest.mark.django_db
def test_personal_list_slugs_registered() -> None:
    for slug in ("family_relation", "edu_type", "talent", "present_type", "contact_type"):
        assert slug in LISTS


@pytest.mark.django_db
def test_family_relation_form_offers_six_fm_types() -> None:
    form = entry_form(LISTS["family_relation"])()
    field = form.fields["fm_type"]
    assert isinstance(field, forms.ChoiceField)
    values = [value for value, _ in cast(list[tuple[str, str]], field.choices) if value]
    assert values == ["son", "daughter", "dad", "mother", "spouse", "other"]


@pytest.mark.django_db
def test_anketa_lists_registered() -> None:
    expected = {
        "qualification_type": (m.QualificationType, "Мэргэшил"),
        "profession_type": (m.ProfessionType, "Мэргэжил"),
        "spec_edu_type": (m.SpecEduType, "Тусгай мэргэжлийн төрөл"),
        "language": (m.ForeignLanguage, "Гадаад хэл"),
        "language_level": (m.LanguageLevel, "Хэлний түвшин"),
    }
    for slug, (model, label) in expected.items():
        assert LISTS[slug].model is model
        assert LISTS[slug].label == label


@pytest.mark.django_db
def test_qualification_type_in_use_cannot_be_removed(admin_client: Client, hired: Employee) -> None:
    qtype = m.QualificationType.objects.create(name="Бакалавр")
    m.QualificationRow.objects.create(
        employee=hired, qualification_type=qtype, org_name="Их сургууль", start_year=2010, end_year=2014
    )
    assert usage_count(m.QualificationType, qtype.pk) == 1
    admin_client.post(f"/lists/qualification_type/{qtype.pk}/delete/")
    assert m.QualificationType.objects.filter(pk=qtype.pk).exists()

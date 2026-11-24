import pytest
from django import forms
from django.db import connection
from django.http import Http404
from django.test.utils import CaptureQueriesContext
from employees.models import DepartmentExt
from employees.services import macs_writes, records
from employees.services.macs_writes import ListEntryInUse
from macs.models import Bank, City, ClothesSize, Country, Department, District, FiredReason, MaritalStatus

from lists.forms import entry_form
from lists.models import DEATH, MONGOLIA, MeaningfulEntry
from lists.registry import LISTS, QUICK
from lists.service import (
    delete_entry,
    entry_fields,
    existing_entry,
    index_items,
    list_page,
    meaning_rows,
    quick_add,
    save_entry,
    save_meanings,
    show_meanings,
)


@pytest.mark.django_db
def test_index_lists_every_list_in_registry_order_without_hits() -> None:
    items = index_items("")
    assert [item.slug for item in items] == list(LISTS)
    assert all(item.hits == 0 for item in items)
    assert index_items("   ") == items
    marital = next(item for item in items if item.slug == "marital_status")
    assert marital.label == LISTS["marital_status"].label
    assert marital.count == MaritalStatus.objects.count()


@pytest.mark.django_db
def test_word_in_a_list_label_matches_that_list_with_no_hits() -> None:
    MaritalStatus.objects.create(name="Гэрлэсэн")
    items = {item.slug: item for item in index_items("  ГЭР  ")}
    assert items["marital_status"].hits == 0  # the list's own name wins, even though an entry also matches
    assert "family_relation" in items  # «Гэр бүлийн хамаарал» also has the word


@pytest.mark.django_db
def test_word_in_entry_names_counts_entries_that_have_every_word() -> None:
    MaritalStatus.objects.create(name="Гэрлэсэн эхнэртэй")
    MaritalStatus.objects.create(name="Гэрлэсэн")
    items = {item.slug: item for item in index_items("гэрлэсэн")}
    assert items["marital_status"].hits == 2
    items = {item.slug: item for item in index_items("гэрлэсэн  ЭХНЭР")}
    assert items["marital_status"].hits == 1


@pytest.mark.django_db
def test_word_found_nowhere_returns_nothing() -> None:
    assert index_items("zzzqqq") == []


def test_meanings_card_shows_for_empty_search_or_its_own_words() -> None:
    assert show_meanings("")
    assert show_meanings("   ")
    assert show_meanings("утгын")
    assert show_meanings("утгын холбоо")
    assert not show_meanings("банк")
    assert not show_meanings("утгын банк")


@pytest.mark.django_db
def test_meaning_rows_give_options_and_the_current_entry() -> None:
    mn = Country.objects.create(name="Монгол")
    MeaningfulEntry.objects.update_or_create(key=MONGOLIA, defaults={"value": mn.pk})
    MeaningfulEntry.objects.filter(key=DEATH).delete()
    rows = {row.key: row for row in meaning_rows()}
    assert rows[MONGOLIA].current == mn.pk
    assert (mn.pk, "Монгол") in rows[MONGOLIA].options
    assert rows[DEATH].current is None


@pytest.mark.django_db
def test_save_meanings_sets_and_clears_a_meaning() -> None:
    mn = Country.objects.create(name="Монгол")
    save_meanings({MONGOLIA: str(mn.pk)})
    assert MeaningfulEntry.get(MONGOLIA) == mn.pk
    save_meanings({MONGOLIA: ""})
    assert MeaningfulEntry.get(MONGOLIA) is None


@pytest.mark.django_db
def test_save_meanings_ignores_junk_and_unknown_pks() -> None:
    dead = FiredReason.objects.create(name="Нас барсан")
    save_meanings({DEATH: str(dead.pk)})
    assert MeaningfulEntry.get(DEATH) == dead.pk
    for junk in ("abc", "99999999999", "987654"):  # not a number, out of int4 range, no such fired reason
        save_meanings({DEATH: junk})
        assert MeaningfulEntry.get(DEATH) == dead.pk


@pytest.mark.django_db
def test_list_page_gives_label_columns_and_rows_ordered_by_name() -> None:
    Bank.objects.create(name="Хаан")
    Bank.objects.create(name="Голомт")
    page = list_page("bank")
    assert page.slug == "bank"
    assert page.label == LISTS["bank"].label
    assert [(column.name, column.label) for column in page.columns] == [("name", "Нэр")]
    assert [row.cells for row in page.rows] == [["Голомт"], ["Хаан"]]
    assert all(isinstance(row.pk, int) for row in page.rows)


@pytest.mark.django_db
def test_list_page_shows_the_label_of_a_choice_field_and_empty_for_none() -> None:
    ClothesSize.objects.create(name="M", size_type="clothes", size_men="M", size_women="S")
    ClothesSize.objects.create(name="42", size_type="shoes")
    page = list_page("sizes")
    assert [column.name for column in page.columns] == ["name", "size_type", "size_men", "size_women"]
    assert [row.cells for row in page.rows] == [["42", "Гутал", "", ""], ["M", "Хувцас", "M", "S"]]


@pytest.mark.django_db
def test_list_page_has_the_city_column_for_a_list_with_a_parent() -> None:
    city = City.objects.create(name="Улаанбаатар")
    District.objects.create(name="Баянзүрх", city=city)
    page = list_page("district")
    assert [(column.name, column.label) for column in page.columns] == [
        ("name", "Нэр"),
        ("city", "Аймаг, хот"),
    ]
    assert [row.cells for row in page.rows] == [["Баянзүрх", "Улаанбаатар"]]


def test_list_page_unknown_slug_is_404() -> None:
    with pytest.raises(Http404):
        list_page("no_such_list")


def test_entry_fields_for_bank_is_one_required_text_field() -> None:
    spec = LISTS["bank"]
    (field,) = entry_fields(spec, entry_form(spec)())
    assert field.name == "name"
    assert field.label == "Нэр"
    assert field.kind == "text"
    assert field.required is True
    assert field.max_length == 100
    assert field.choices == []
    assert field.errors == []


def test_entry_fields_for_country_adds_the_code_text_field() -> None:
    spec = LISTS["country"]
    fields = {field.name: field for field in entry_fields(spec, entry_form(spec)())}
    assert list(fields) == ["name", "code"]
    assert fields["code"].kind == "text"
    assert fields["code"].label == "Код"
    assert fields["code"].required is False


def test_entry_fields_for_sizes_make_size_type_a_select_with_two_choices() -> None:
    spec = LISTS["sizes"]
    fields = {field.name: field for field in entry_fields(spec, entry_form(spec)())}
    assert fields["size_type"].kind == "select"
    assert fields["size_type"].choices == [("", ""), ("clothes", "Хувцас"), ("shoes", "Гутал")]
    assert fields["size_men"].kind == "text"


@pytest.mark.django_db
def test_entry_fields_for_district_lists_every_city_with_a_blank_first() -> None:
    spec = LISTS["district"]
    ulaanbaatar = City.objects.create(name="Улаанбаатар")
    darkhan = City.objects.create(name="Дархан")
    fields = {field.name: field for field in entry_fields(spec, entry_form(spec)())}
    city = fields["city"]
    assert city.kind == "select"
    assert city.required is True
    assert city.choices[0] == ("", "")
    assert city.choices[1:] == [(str(c.pk), str(c)) for c in City.objects.all()]
    assert {value for value, _label in city.choices} == {"", str(ulaanbaatar.pk), str(darkhan.pk)}


@pytest.mark.django_db
def test_entry_fields_carry_the_current_value_of_an_edit_form() -> None:
    spec = LISTS["district"]
    city = City.objects.create(name="Улаанбаатар")
    district = District.objects.create(name="Баянзүрх", city=city)
    fields = {field.name: field for field in entry_fields(spec, entry_form(spec)(instance=district))}
    assert fields["name"].value == "Баянзүрх"
    assert fields["city"].value == str(city.pk)


def test_entry_fields_carry_the_errors_of_a_bound_form() -> None:
    spec = LISTS["bank"]
    form = entry_form(spec)({"name": ""})
    assert not form.is_valid()
    (field,) = entry_fields(spec, form)
    assert field.value == ""
    assert len(field.errors) == 1


def test_entry_fields_gives_an_integer_field_the_number_kind() -> None:
    class NumberForm(forms.Form):
        name = forms.IntegerField(required=False)

    spec = LISTS["bank"]
    (field,) = entry_fields(spec, NumberForm({"name": "12"}))
    assert field.kind == "number"
    assert field.value == "12"


@pytest.mark.django_db
def test_every_list_form_field_is_text_select_or_number() -> None:
    for spec in LISTS.values():
        for field in entry_fields(spec, entry_form(spec)()):
            assert field.kind in {"text", "select", "number"}, (spec.slug, field.name)


@pytest.mark.django_db
def test_save_entry_adds_a_valid_entry() -> None:
    result = save_entry(LISTS["bank"], {"name": "Хаан"})
    assert result.ok is True
    assert result.entry is not None
    assert result.entry.name == "Хаан"
    assert Bank.objects.filter(name="Хаан").count() == 1


@pytest.mark.django_db
def test_save_entry_with_an_empty_name_is_refused_with_the_form_error() -> None:
    result = save_entry(LISTS["bank"], {"name": ""})
    assert result.ok is False
    assert result.entry is None
    assert result.form.errors.get("name")
    assert Bank.objects.count() == 0


@pytest.mark.django_db
def test_save_entry_edit_changes_the_name() -> None:
    bank = Bank.objects.create(name="Хаан")
    result = save_entry(LISTS["bank"], {"name": "Хаан банк"}, entry=bank)
    assert result.ok is True
    bank.refresh_from_db()
    assert bank.name == "Хаан банк"


@pytest.mark.django_db
def test_save_entry_edit_of_a_negative_id_bank() -> None:
    bank = Bank.objects.create(id=-1, name="Хаан банк (MACS)")
    result = save_entry(LISTS["bank"], {"name": "Хаан банк"}, entry=bank)
    assert result.ok is True
    bank.refresh_from_db()
    assert bank.name == "Хаан банк"


@pytest.mark.django_db
def test_delete_entry_removes_an_unused_entry() -> None:
    bank = Bank.objects.create(name="Тест банк")
    result = delete_entry(bank)
    assert result.ok is True
    assert result.error == ""
    assert not Bank.objects.filter(pk=bank.pk).exists()


@pytest.mark.django_db
def test_delete_entry_removes_a_negative_id_bank() -> None:
    Bank.objects.create(id=-1, name="Хаан банк (MACS)")
    result = delete_entry(Bank.objects.get(pk=-1))
    assert result.ok is True
    assert not Bank.objects.filter(pk=-1).exists()


@pytest.mark.django_db
def test_delete_entry_in_use_is_refused_with_the_in_use_message(hired, actor) -> None:  # type: ignore[no-untyped-def]
    married = MaritalStatus.objects.create(name="Гэрлэсэн")
    records.update_employee(hired, {"marital_status": married}, actor)
    macs_writes.update_employee_columns(hired, {"status": "inactive", "emptype": 3, "contract_flag": "no"})
    with pytest.raises(ListEntryInUse) as exc:
        macs_writes.delete_list_entry(married)
    result = delete_entry(married)
    assert result.ok is False
    assert result.error == str(exc.value)
    assert MaritalStatus.objects.filter(pk=married.pk).exists()


@pytest.mark.django_db
def test_quick_add_existing_name_in_other_case_and_spaces_returns_the_old_entry() -> None:
    bank = Bank.objects.create(name="Банк")
    before = Bank.objects.count()
    result = quick_add(LISTS["bank"], {"name": " банк "})
    assert result.ok is True
    assert result.existed is True
    assert result.id == bank.pk
    assert result.name == "Банк"
    assert Bank.objects.count() == before


@pytest.mark.django_db
def test_quick_add_district_same_name_in_another_city_is_a_new_entry() -> None:
    ub = City.objects.create(name="Улаанбаатар")
    other = City.objects.create(name="Дархан")
    kept = District.objects.create(name="Хан-Уул", city=ub)
    result = quick_add(QUICK["district"], {"name": "Хан-Уул", "city": str(other.pk)})
    assert result.ok is True
    assert result.existed is False
    assert result.id != kept.pk
    assert District.objects.filter(name="Хан-Уул", city=other, pk=result.id).exists()


@pytest.mark.django_db
def test_quick_add_duplicate_department_that_was_switched_off_is_reactivated() -> None:
    dep = Department.objects.create(name="Хуучин хэлтэс")
    DepartmentExt.objects.create(department=dep, active=False)
    result = quick_add(QUICK["department"], {"name": "хуучин хэлтэс"})
    assert result.ok is True
    assert result.existed is True
    assert result.id == dep.pk
    assert DepartmentExt.objects.get(pk=dep.pk).active is True
    assert Department.objects.filter(name__iexact="хуучин хэлтэс").count() == 1


@pytest.mark.django_db
def test_quick_add_name_longer_than_the_column_is_refused_without_a_lookup() -> None:
    long_name = "А" * 31  # MaritalStatus.name holds 30 characters
    assert existing_entry(LISTS["marital_status"], "") is None
    with CaptureQueriesContext(connection) as queries:
        assert existing_entry(LISTS["marital_status"], long_name) is None
    assert queries.captured_queries == []
    result = quick_add(LISTS["marital_status"], {"name": long_name})
    assert result.ok is False
    assert result.id is None
    assert result.existed is False
    assert result.form.errors.get("name")
    assert not MaritalStatus.objects.filter(name__startswith="АААА").exists()


@pytest.mark.django_db
def test_quick_add_valid_new_name_creates_an_entry() -> None:
    result = quick_add(LISTS["marital_status"], {"name": "  Шинээр гэрлэсэн  "})
    assert result.ok is True
    assert result.existed is False
    assert result.name == "Шинээр гэрлэсэн"
    assert MaritalStatus.objects.get(pk=result.id).name == "Шинээр гэрлэсэн"

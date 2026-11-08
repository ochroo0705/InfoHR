"""Answer validation for the employee self-form: it reuses the real hire and Personal-tab forms."""

import base64
import io
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from macs.models import ContactType, EducationLevel, FamilyRelation, ProfessionType
from PIL import Image

from employees.forms import EducationRowForm, EmployeeForm
from employees.selfform.answers import (
    CONTACT_FIELDS,
    MAX_BODY_BYTES,
    MAX_EDUCATION,
    MAX_FAMILY,
    MAX_PHOTO_BYTES,
    PERSON_FIELDS,
    AnswerErrors,
    rows_for_confirm,
    store_photo,
    validate_answers,
)

from .conftest import named

pytestmark = pytest.mark.django_db


def person(**extra: Any) -> dict[str, Any]:
    base = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "уб 99112233",
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
    }
    return base | extra


def jpeg_upload(name: str = "a.jpg") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def lists() -> dict[str, Any]:
    return {
        "relation": named(FamilyRelation, "Хүү"),
        "contact": named(ContactType, "Утас"),
        "edu_level": named(EducationLevel, "Бакалавр"),
        "profession": named(ProfessionType, "Нягтлан"),
    }


def test_register_no_is_normalized_like_the_hire_form() -> None:
    cleaned = validate_answers({"person": person(register_no="ук 88010122")}, final=True)
    assert cleaned["person"]["register_no"] == "УК88010122"


def test_final_requires_the_six_required_person_fields() -> None:
    with pytest.raises(AnswerErrors) as exc:
        validate_answers({"person": {}}, final=True)
    for name in ("family_name", "given_name", "register_no", "birth_date", "gender", "work_phone"):
        assert f"person.{name}" in exc.value.errors


def test_draft_allows_blank_required_fields() -> None:
    cleaned = validate_answers({"person": {}}, final=False)
    assert cleaned == {
        "person": {name: "" for name in PERSON_FIELDS},
        "education": [],
        "family": [],
        "contact": {name: "" for name in CONTACT_FIELDS},
    }


def test_draft_keeps_education_row_without_end_year() -> None:
    raw = {
        "person": person(),
        "education": [{"org_name": " Сургууль ", "start_year": "2010", "end_year": ""}],
    }
    cleaned = validate_answers(raw, final=False)
    assert cleaned["education"] == [
        {"org_name": "Сургууль", "start_year": "2010", "end_year": "", "edu_level": "", "profession_type": ""}
    ]
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    assert "education.0.end_year" in exc.value.errors


def test_draft_keeps_family_row_without_relation() -> None:
    raw = {"person": person(), "family": [{"given_name": "Бат", "relation": ""}]}
    cleaned = validate_answers(raw, final=False)
    assert cleaned["family"] == [
        {"relation": "", "given_name": "Бат", "surname": "", "birth_date": "", "job": "", "phone": ""}
    ]
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    assert "family.0.relation" in exc.value.errors


def test_draft_keeps_half_typed_contact() -> None:
    raw = {"person": person(), "contact": {"name": "Бат"}}
    cleaned = validate_answers(raw, final=False)
    assert cleaned["contact"] == {"contact_type": "", "name": "Бат", "relative": "", "value": ""}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    assert "contact.contact_type" in exc.value.errors


def test_draft_keeps_partial_register_no_as_typed() -> None:
    cleaned = validate_answers({"person": person(register_no="УБ 9911")}, final=False)
    expected = person(register_no="УБ 9911")
    assert cleaned["person"] == {name: expected.get(name, "") for name in PERSON_FIELDS}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers({"person": person(register_no="УБ 9911")}, final=True)
    assert "person.register_no" in exc.value.errors


def test_draft_caps_text_at_the_form_length() -> None:
    cleaned = validate_answers({"person": person(given_name="а" * 500)}, final=False)
    field: Any = EmployeeForm().fields["given_name"]
    assert len(cleaned["person"]["given_name"]) == field.max_length


def test_draft_still_refuses_too_many_rows() -> None:
    education = [{"org_name": "Сургууль"}] * (MAX_EDUCATION + 1)
    with pytest.raises(AnswerErrors) as exc:
        validate_answers({"person": person(), "education": education}, final=False)
    assert "education" in exc.value.errors


def test_decompression_bomb_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(AnswerErrors) as exc:
        store_photo(jpeg_upload())
    assert "photo" in exc.value.errors


def test_hr_only_fields_are_ignored() -> None:
    raw = {"person": person(first_hire_date="2026-01-05", salary="1000000")}
    cleaned = validate_answers(raw, final=True)
    assert "first_hire_date" not in cleaned["person"]
    assert "salary" not in cleaned["person"]


def test_education_requires_school_and_years(lists: dict[str, Any]) -> None:
    raw = {"person": person(), "education": [{"org_name": "Сургууль", "start_year": 2015, "end_year": 2010}]}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    reference = EducationRowForm({"org_name": "Сургууль", "start_year": 2015, "end_year": 2010}, adding=True)
    assert not reference.is_valid()
    assert exc.value.errors["education.0.end_year"] == [str(reference.errors["end_year"][0])]


def test_family_row_needs_relation_and_name(lists: dict[str, Any]) -> None:
    raw = {"person": person(), "family": [{"relation": None, "given_name": "", "surname": "Ган"}]}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    assert "family.0.relation" in exc.value.errors
    assert "family.0.given_name" in exc.value.errors


def test_contact_partly_filled_needs_type_name_relation(lists: dict[str, Any]) -> None:
    raw = {"person": person(), "contact": {"value": "99112233"}}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=True)
    for name in ("contact_type", "name", "relative"):
        assert f"contact.{name}" in exc.value.errors


def test_empty_contact_is_allowed() -> None:
    cleaned = validate_answers({"person": person(), "contact": {}}, final=True)
    assert cleaned["contact"] == {}


def test_row_caps(lists: dict[str, Any]) -> None:
    education = [{"org_name": "Сургууль", "start_year": 2000, "end_year": 2004}] * (MAX_EDUCATION + 1)
    with pytest.raises(AnswerErrors) as exc:
        validate_answers({"person": person(), "education": education}, final=True)
    assert "education" in exc.value.errors

    family = [{"relation": lists["relation"].pk, "given_name": "Бат"}] * (MAX_FAMILY + 1)
    with pytest.raises(AnswerErrors) as exc:
        validate_answers({"person": person(), "family": family}, final=True)
    assert "family" in exc.value.errors


def test_body_over_200kb_rejected() -> None:
    raw = {"person": person(clan_name="x" * (MAX_BODY_BYTES + 10))}
    with pytest.raises(AnswerErrors) as exc:
        validate_answers(raw, final=False)
    assert "body" in exc.value.errors


def test_photo_not_an_image_rejected() -> None:
    with pytest.raises(AnswerErrors) as exc:
        store_photo(SimpleUploadedFile("a.jpg", b"hello", content_type="image/jpeg"))
    assert "photo" in exc.value.errors


def test_photo_over_5mb_rejected() -> None:
    too_big = SimpleUploadedFile("a.jpg", b"0" * (MAX_PHOTO_BYTES + 1), content_type="image/jpeg")
    with pytest.raises(AnswerErrors) as exc:
        store_photo(too_big)
    assert "photo" in exc.value.errors


def test_photo_is_stored_as_base64_jpeg() -> None:
    encoded = store_photo(jpeg_upload())
    assert base64.b64decode(encoded).startswith(b"\xff\xd8\xff")


def image_upload(image: Image.Image, fmt: str, name: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


def test_photo_gif_is_refused() -> None:
    with pytest.raises(AnswerErrors) as exc:
        store_photo(image_upload(Image.new("RGB", (4, 4)), "GIF", "a.gif"))
    assert "photo" in exc.value.errors


def test_photo_bmp_is_refused() -> None:
    with pytest.raises(AnswerErrors) as exc:
        store_photo(image_upload(Image.new("RGB", (4, 4)), "BMP", "a.bmp"))
    assert "photo" in exc.value.errors


def test_photo_png_declaring_too_many_pixels_is_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 1-bit 6000 x 5000 image is 30 million pixels but a tiny file; the header alone is enough to refuse it.
    from employees.selfform import answers

    def must_not_decode(upload: object) -> None:
        raise AssertionError("the photo was decoded although its header is too large")

    monkeypatch.setattr(answers, "shrink_photo", must_not_decode)
    with pytest.raises(AnswerErrors) as exc:
        store_photo(image_upload(Image.new("1", (6000, 5000)), "PNG", "big.png"))
    assert "photo" in exc.value.errors


def test_small_png_is_accepted() -> None:
    encoded = store_photo(image_upload(Image.new("RGB", (4, 4), "red"), "PNG", "a.png"))
    assert base64.b64decode(encoded).startswith(b"\xff\xd8\xff")


def test_rows_for_confirm_returns_columns_for_personal_writes_add(lists: dict[str, Any]) -> None:
    raw = {
        "person": person(),
        "education": [
            {
                "org_name": "Сургууль",
                "start_year": 2010,
                "end_year": 2014,
                "edu_level": lists["edu_level"].pk,
                "profession_type": lists["profession"].pk,
            }
        ],
        "family": [{"relation": lists["relation"].pk, "given_name": "Бат", "birth_date": "1970-01-01"}],
    }
    cleaned = validate_answers(raw, final=True)
    rows = rows_for_confirm(cleaned)
    kinds = [kind for kind, _, _ in rows]
    assert kinds == ["education", "family"]
    _, edu_columns, edu_ext = rows[0]
    assert edu_columns["org_name"] == "Сургууль"
    assert edu_ext == {}
    _, fam_columns, _ = rows[1]
    assert fam_columns["relation_id"] == lists["relation"].pk

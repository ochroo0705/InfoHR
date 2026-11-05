import pytest
from macs.models import Bank, Branch, ClothesSize, Department, Position

from assistant.resolver import LOOKUPS, MAX_CANDIDATES, Resolution, candidate_names, resolve

pytestmark = pytest.mark.django_db


def _names(resolution: Resolution) -> list[str]:
    return [candidate.name for candidate in resolution.candidates]


def test_exact_name_is_one() -> None:
    Department.objects.create(name="Санхүү")
    Department.objects.create(name="Санхүүгийн хяналт")
    result = resolve("department", "Санхүү")
    assert result.status == "one"
    assert _names(result) == ["Санхүү"]


def test_prefix_is_several() -> None:
    Department.objects.create(name="Санхүүгийн хяналт")
    Department.objects.create(name="Санхүүгийн төлөвлөлт")
    result = resolve("department", "санхүү")
    assert result.status == "several"
    assert len(result.candidates) == 2


@pytest.mark.parametrize("phrase", ["санхүүгийн хэлтэс", "САНХҮҮГИЙН", "санхуугийн"])
def test_case_endings_and_generic_word(phrase: str) -> None:
    Department.objects.create(name="Санхүү")
    result = resolve("department", phrase)
    assert result.status == "one"
    assert _names(result) == ["Санхүү"]


def test_none() -> None:
    Department.objects.create(name="Санхүү")
    assert resolve("department", "маркетинг").status == "none"
    assert resolve("department", "хэлтэс").status == "none"
    assert resolve("department", "").status == "none"
    assert resolve("department", "sanhuu").status == "none"


def test_cap() -> None:
    for i in range(20):
        Department.objects.create(name=f"Санхүүгийн хэсэг {i}")
    result = resolve("department", "санхүү")
    assert result.status == "several"
    assert len(result.candidates) == MAX_CANDIDATES == 15
    assert candidate_names("department", "санхүү") == _names(result)


def test_code_list_lookup() -> None:
    Bank.objects.create(name="Хаан банк")
    result = resolve("bank", "хаан")
    assert result.status == "one"
    assert _names(result) == ["Хаан банк"]


def test_unknown_param() -> None:
    with pytest.raises(KeyError):
        resolve("salary_from", "x")


def test_lookups_cover_lists_and_code_filters() -> None:
    assert {"department", "branch", "position", "bank", "nationality"} <= set(LOOKUPS)
    assert "salary" not in LOOKUPS


def test_size_lookups_are_split_by_type() -> None:
    ClothesSize.objects.create(name="L", size_type="clothes")
    ClothesSize.objects.create(name="42", size_type="shoes")
    assert resolve("shoe_size", "42").status == "one"
    assert resolve("clothing_size", "42").status == "none"
    assert resolve("clothing_size", "L").status == "one"
    assert resolve("shoe_size", "L").status == "none"


def test_short_and_numeric_names_resolve_by_exact_name() -> None:
    ClothesSize.objects.create(name="M", size_type="clothes")
    ClothesSize.objects.create(name="42", size_type="shoes")
    assert _names(resolve("clothing_size", "M")) == ["M"]
    assert _names(resolve("shoe_size", "42")) == ["42"]
    assert resolve("shoe_size", "  42 ").status == "one"


def test_digits_matching_no_name_is_none() -> None:
    Department.objects.create(name="Санхүү")
    assert resolve("department", "7").status == "none"


def test_generic_phrase_without_exact_name_is_none() -> None:
    Department.objects.create(name="Санхүү")
    assert resolve("department", "хэлтэс").status == "none"


def test_generic_phrase_exact_name_is_one() -> None:
    Department.objects.create(name="Хэлтэс")
    result = resolve("department", "хэлтэс")
    assert result.status == "one"
    assert _names(result) == ["Хэлтэс"]


def test_branch_lookup() -> None:
    Branch.objects.create(name="Төв салбар")
    Branch.objects.create(name="Хойд салбар")
    assert _names(resolve("branch", "төв")) == ["Төв салбар"]


def test_position_lookup() -> None:
    Position.objects.create(name="Нягтлан бодогч")
    assert _names(resolve("position", "нягтлан")) == ["Нягтлан бодогч"]


def test_several_is_ranked_by_extra_words_then_name() -> None:
    Department.objects.create(name="Санхүү төлөв хяналт")
    Department.objects.create(name="Санхүүгийн хяналт")
    Department.objects.create(name="Санхүүгийн бодлого")
    result = resolve("department", "санхүү")
    assert result.status == "several"
    assert _names(result) == ["Санхүүгийн бодлого", "Санхүүгийн хяналт", "Санхүү төлөв хяналт"]

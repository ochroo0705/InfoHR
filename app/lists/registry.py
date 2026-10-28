"""Which production lookup tables the Lists screen edits, and in what order (Жагсаалтууд)."""

from dataclasses import dataclass, field
from typing import Any

from macs import models as m

from lists.models import DEATH, MONGOLIA


@dataclass(frozen=True)
class ListSpec:
    slug: str
    model: Any
    label: str
    extra_fields: tuple[str, ...] = field(default=())
    parent: str | None = None

    @property
    def modal(self) -> bool:
        """Needs more than a name, so an add from a form opens a pop-up (docs/UI_RULES.md §2a)."""
        return bool(self.extra_fields or self.parent)


LISTS: dict[str, ListSpec] = {
    s.slug: s
    for s in [
        ListSpec("marital_status", m.MaritalStatus, "Гэр бүлийн байдал"),
        ListSpec("country", m.Country, "Улс, иргэншил", ("code",)),
        ListSpec("nationality", m.Nationality, "Үндэс угсаа"),
        ListSpec("social_origin", m.SocialOrigin, "Нийгмийн гарал"),
        ListSpec("housing", m.HousingCondition, "Орон байрны нөхцөл"),
        ListSpec("car", m.CarOwnership, "Автомашин эзэмшил"),
        ListSpec("elected", m.ElectedPosition, "Сонгуульт ажил"),
        ListSpec("sizes", m.ClothesSize, "Хувцас, гутлын хэмжээ", ("size_type", "size_men", "size_women")),
        ListSpec("city", m.City, "Аймаг, хот"),
        ListSpec("district", m.District, "Сум, дүүрэг", parent="city"),
        ListSpec("education", m.EducationLevel, "Боловсрол"),
        ListSpec("degree", m.AcademicDegree, "Эрдмийн зэрэг"),
        ListSpec("insured", m.InsuredCategory, "Даатгуулагчийн төрөл", ("code",)),
        ListSpec("bank", m.Bank, "Банк"),
        ListSpec("shift", m.Shift, "Ажлын цагийн хуваарь"),
        ListSpec("fired_reason", m.FiredReason, "Ажлаас гарсан шалтгаан"),
        ListSpec("office", m.Office, "Алба"),
        ListSpec("section", m.Section, "Хэсэг"),
        ListSpec("family_relation", m.FamilyRelation, "Гэр бүлийн хамаарал", ("fm_type",)),
        ListSpec("edu_type", m.EduType, "Боловсролын төрөл"),
        ListSpec("qualification_type", m.QualificationType, "Мэргэшил"),
        ListSpec("profession_type", m.ProfessionType, "Мэргэжил"),
        ListSpec("spec_edu_type", m.SpecEduType, "Тусгай мэргэжлийн төрөл"),
        ListSpec("language", m.ForeignLanguage, "Гадаад хэл"),
        ListSpec("language_level", m.LanguageLevel, "Хэлний түвшин"),
        ListSpec("talent", m.TalentKind, "Авьяас"),
        ListSpec("present_type", m.PresentType, "Бэлгийн төрөл"),
        ListSpec("material_help_type", m.MaterialHelpType, "Буцалтгүй тусламжийн үндэслэл"),
        ListSpec("discipline_type", m.DisciplineType, "Шийтгэлийн төрөл"),
        ListSpec("driver_type", m.DriverType, "Жолооны ангилал"),
        ListSpec("contact_type", m.ContactType, "Холбоо барих төрөл"),
    ]
}


# Lists that can also take a new entry straight from a form dropdown (docs/UI_RULES.md §2a).
# Department and Position are edited in admin, so they are not on the Lists screen (LISTS).
QUICK_ONLY: dict[str, ListSpec] = {
    "department": ListSpec("department", m.Department, "Хэлтэс"),
    "position": ListSpec("position", m.Position, "Албан тушаал"),
}
QUICK: dict[str, ListSpec] = {**LISTS, **QUICK_ONLY}
QUICK_BY_MODEL: dict[Any, str] = {spec.model: spec.slug for spec in QUICK.values()}


@dataclass(frozen=True)
class MeaningSpec:
    """One meaning the code relies on: which list entry carries it (MeaningfulEntry)."""

    label: str
    model: Any
    hint: str


MEANINGS: dict[str, MeaningSpec] = {
    MONGOLIA: MeaningSpec("Монгол улс", m.Country, "Иргэншлийн сонголтод «Монгол» гэж тооцох улс."),
    DEATH: MeaningSpec("Нас барсан", m.FiredReason, "Энэ шалтгаанаар гарсан ажилтныг «нас барсан» гэж тэмдэглэнэ."),
}

# Mongolian labels for fields whose model has no verbose_name.
FIELD_LABELS: dict[str, str] = {
    "code": "Код",
    "size_type": "Төрөл",
    "size_men": "Эрэгтэй",
    "size_women": "Эмэгтэй",
    "city": "Аймаг, хот",
}

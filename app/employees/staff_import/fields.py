"""Catalogue of the employee fields a staff spreadsheet can fill, with the column headings that match each one."""

import re
from dataclasses import dataclass

FIELD_KINDS = ("text", "date", "money", "gender")

_DROP = re.compile(r"[.:,№]")
_SLASH = re.compile(r"\s*/\s*")
_SPACES = re.compile(r"\s+")


def normalize_heading(text: object) -> str:
    """Lower case, no `.:,` or `№`, single spaces, none around `/`: '  Регистрийн  дугаар: ' -> 'регистрийн дугаар'."""
    if text is None:
        return ""
    cleaned = _DROP.sub("", str(text)).lower()
    return _SPACES.sub(" ", _SLASH.sub("/", cleaned)).strip()


@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    aliases: tuple[str, ...]
    kind: str
    lookup: str | None = None
    needs_salary: bool = False


FIELDS: tuple[ImportField, ...] = (
    ImportField(
        key="family_name",
        label="Эцэг/эхийн нэр",
        aliases=("овог", "эцэг эхийн нэр", "эцэг/эхийн нэр", "surname", "last name", "family name"),
        kind="text",
    ),
    ImportField(
        key="given_name",
        label="Нэр",
        aliases=("нэр", "name", "first name", "given name"),
        kind="text",
    ),
    ImportField(
        key="register_no",
        label="Регистрийн дугаар",
        aliases=("регистр", "регистрийн дугаар", "register no", "register number"),
        kind="text",
    ),
    ImportField(
        key="passport_no",
        label="Иргэний үнэмлэх / паспорт",
        aliases=("паспорт", "паспортын дугаар", "passport", "passport no"),
        kind="text",
    ),
    ImportField(
        key="birth_date",
        label="Төрсөн огноо",
        aliases=("төрсөн огноо", "төрсөн", "birth date", "date of birth"),
        kind="date",
    ),
    ImportField(
        key="gender",
        label="Хүйс",
        aliases=("хүйс", "gender", "sex"),
        kind="gender",
    ),
    ImportField(
        key="work_phone",
        label="Ажлын утас",
        aliases=("ажлын утас", "work phone"),
        kind="text",
    ),
    ImportField(
        key="private_phone",
        label="Хувийн утас",
        aliases=("хувийн утас", "утас", "private phone", "phone"),
        kind="text",
    ),
    ImportField(
        key="email",
        label="И-мэйл",
        aliases=("и-мэйл", "имэйл", "email", "e-mail"),
        kind="text",
    ),
    ImportField(
        key="start",
        label="Анх ажилд орсон огноо",
        aliases=("ажилд орсон огноо", "ажилд орсон", "start date", "hire date"),
        kind="date",
    ),
    ImportField(
        key="department",
        label="Хэлтэс",
        aliases=("хэлтэс", "department"),
        kind="text",
        lookup="department",
    ),
    ImportField(
        key="position",
        label="Албан тушаал",
        aliases=("албан тушаал", "position", "job title"),
        kind="text",
        lookup="position",
    ),
    ImportField(
        key="branch",
        label="Салбар",
        aliases=("салбар", "branch"),
        kind="text",
        lookup="branch",
    ),
    ImportField(
        key="citizenship",
        label="Иргэншил",
        aliases=("иргэншил", "citizenship", "country"),
        kind="text",
        lookup="country",
    ),
    ImportField(
        key="work_conditions",
        label="Ажлын нөхцөл",
        aliases=("ажлын нөхцөл", "work conditions"),
        kind="text",
        lookup="work_conditions",
    ),
    ImportField(
        key="base_salary",
        label="Цалин",
        aliases=("цалин", "base salary", "salary"),
        kind="money",
        needs_salary=True,
    ),
    ImportField(
        key="bank",
        label="Банк",
        aliases=("банк", "bank"),
        kind="text",
        lookup="bank",
        needs_salary=True,
    ),
    ImportField(
        key="account_no",
        label="Дансны дугаар",
        aliases=("дансны дугаар", "данс", "account no", "account number"),
        kind="text",
        needs_salary=True,
    ),
    ImportField(
        key="social_insurance_no",
        label="НДД-ийн дугаар",
        aliases=("ндд-ийн дугаар", "ндд", "social insurance no"),
        kind="text",
        needs_salary=True,
    ),
    ImportField(
        key="health_insurance_no",
        label="ЭМДД-ийн дугаар",
        aliases=("эмдд-ийн дугаар", "эмдд", "health insurance no"),
        kind="text",
        needs_salary=True,
    ),
    ImportField(
        key="taxpayer_no",
        label="Татвар төлөгчийн дугаар",
        aliases=("татвар төлөгчийн дугаар", "татварын дугаар", "taxpayer no", "tax no"),
        kind="text",
        needs_salary=True,
    ),
    ImportField(
        key="insured_category",
        label="Даатгуулагчийн төрөл",
        aliases=("даатгуулагчийн төрөл", "даатгуулагчийн ангилал", "insured category"),
        kind="text",
        lookup="insured",
        needs_salary=True,
    ),
)

BY_KEY: dict[str, ImportField] = {field.key: field for field in FIELDS}

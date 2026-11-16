"""Catalogue of the employee fields a staff spreadsheet can fill, with the column headings that match each one."""

import re
from dataclasses import dataclass

FIELD_KINDS = ("text", "date", "money", "gender", "int", "yesno")

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
        key="clan_name",
        label="Ургийн овог",
        aliases=("ургийн овог", "clan name"),
        kind="text",
    ),
    ImportField(
        key="phone2",
        label="Утас #2",
        aliases=("утас 2", "утас #2", "утас2", "second phone", "phone 2"),
        kind="text",
    ),
    ImportField(
        key="prior_service_years",
        label="Өмнөх ажилласан жил",
        aliases=("өмнөх ажилласан жил", "ажилласан жил", "prior service years", "years of service"),
        kind="int",
    ),
    ImportField(
        key="probation_end",
        label="Туршилтын хугацаа дуусах",
        aliases=("туршилтын хугацаа дуусах", "туршилт дуусах", "probation end"),
        kind="date",
    ),
    ImportField(
        key="employee_type",
        label="Ажилтны төрөл",
        aliases=("ажилтны төрөл", "employee type"),
        kind="text",
    ),
    ImportField(
        key="contract_type",
        label="Гэрээний төрөл",
        aliases=("гэрээний төрөл", "contract type"),
        kind="text",
    ),
    ImportField(
        key="contract_no",
        label="Гэрээний дугаар",
        aliases=("гэрээний дугаар", "contract no", "contract number"),
        kind="text",
    ),
    ImportField(
        key="contract_start",
        label="Гэрээ эхлэх огноо",
        aliases=("гэрээ эхлэх огноо", "гэрээ эхлэх", "contract start"),
        kind="date",
    ),
    ImportField(
        key="contract_end",
        label="Гэрээ дуусах огноо",
        aliases=("гэрээ дуусах огноо", "гэрээ дуусах", "contract end"),
        kind="date",
    ),
    ImportField(
        key="work_schedule",
        label="Ажлын цагийн хуваарь",
        aliases=("ажлын цагийн хуваарь", "цагийн хуваарь", "work schedule", "shift"),
        kind="text",
        lookup="work_schedule",
    ),
    ImportField(
        key="marital_status",
        label="Гэрлэлтийн байдал",
        aliases=("гэрлэлтийн байдал", "гэр бүлийн байдал", "marital status"),
        kind="text",
        lookup="marital_status",
    ),
    ImportField(
        key="nationality",
        label="Үндэс угсаа",
        aliases=("үндэс угсаа", "үндэстэн", "nationality"),
        kind="text",
        lookup="nationality",
    ),
    ImportField(
        key="education_level",
        label="Боловсрол",
        aliases=("боловсрол", "боловсролын түвшин", "education", "education level"),
        kind="text",
        lookup="education_level",
    ),
    ImportField(
        key="academic_degree",
        label="Эрдмийн зэрэг",
        aliases=("эрдмийн зэрэг", "academic degree", "degree"),
        kind="text",
        lookup="academic_degree",
    ),
    ImportField(
        key="social_origin",
        label="Нийгмийн гарал",
        aliases=("нийгмийн гарал", "social origin"),
        kind="text",
        lookup="social_origin",
    ),
    ImportField(
        key="housing_condition",
        label="Орон байрны нөхцөл",
        aliases=("орон байрны нөхцөл", "housing"),
        kind="text",
        lookup="housing_condition",
    ),
    ImportField(
        key="car_ownership",
        label="Автомашин эзэмшил",
        aliases=("автомашин эзэмшил", "car ownership"),
        kind="text",
        lookup="car_ownership",
    ),
    ImportField(
        key="clothing_size",
        label="Хувцасны хэмжээ",
        aliases=("хувцасны хэмжээ", "clothing size"),
        kind="text",
        lookup="clothing_size",
    ),
    ImportField(
        key="shoe_size",
        label="Гутлын хэмжээ",
        aliases=("гутлын хэмжээ", "shoe size"),
        kind="text",
        lookup="shoe_size",
    ),
    ImportField(
        key="elected_position",
        label="Сонгуульт ажил",
        aliases=("сонгуульт ажил", "elected position"),
        kind="text",
        lookup="elected_position",
    ),
    ImportField(
        key="blood_type",
        label="Цусны бүлэг",
        aliases=("цусны бүлэг", "blood type"),
        kind="text",
    ),
    ImportField(
        key="military_service",
        label="Цэргийн алба хаасан",
        aliases=("цэргийн алба хаасан", "цэргийн алба", "military service"),
        kind="yesno",
    ),
    ImportField(
        key="has_disability",
        label="Хөгжлийн бэрхшээлтэй",
        aliases=("хөгжлийн бэрхшээлтэй", "хөгжлийн бэрхшээл", "disability"),
        kind="yesno",
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

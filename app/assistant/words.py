"""The words the assistant knows for the staff table's filters: the Mongolian label of each filter, the words people
use for it, and the values of the fixed lists with their synonyms. This is the semantic layer: a question's words are
looked up here, and only the filters the staff table offers a user (`offered_words`) are ever offered to that user.

`WORDS` is keyed by query parameter. A `kind` says how the value is given: "fixed" (a short list in `values`), "lookup"
(a code list the resolver searches by name), "date" or "number". `confirmed=False` marks a value whose meaning is not
yet checked with HR: it is applied like any listed value, and only the accuracy gate (evalset.TableCase) leaves it out.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from accounts.models import User
from reports.column_filters import COLUMN_FILTERS, params_of
from reports.filters import EMPTYPES, GENDERS, STATES
from reports.staff_list import REPORT
from reports.table import offered_column_filters, offered_filters


@dataclass(frozen=True)
class ValueWords:
    value: str  # the stored value: "5", "M", "working"
    label: str  # Mongolian label shown to the user
    synonyms: tuple[str, ...]  # other Mongolian/English words people use
    confirmed: bool = True


@dataclass(frozen=True)
class FilterWords:
    param: str  # the query parameter: "department", "emptype", "hired_from", "age_to" ...
    label: str  # Mongolian label («Хэлтэс»)
    kind: str  # "fixed" | "lookup" | "date" | "number"
    description: str  # one English sentence for the model
    synonyms: tuple[str, ...]
    values: tuple[ValueWords, ...] = ()  # only for kind "fixed"


# The labels of the fixed values come from the filter tables, so they cannot drift from what the staff table shows.
# Only the synonyms are written here, by stored value.
_WORK_CONDITIONS: dict[str, str] = {str(k): label for k, label in COLUMN_FILTERS["work_conditions"].choices}
_EMPTYPE_LABELS: dict[str, str] = {str(k): label for k, label in EMPTYPES.items()}
_STATE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "working": ("ажиллаж байгаа", "идэвхтэй"),
    "upcoming": ("удахгүй ажилд орох",),
    "left": ("гарсан", "ажлаас гарсан"),
    "all": ("бүгд",),
}
_EMPTYPE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "1": ("ажилчид",),
    "2": ("гадаад нөөц",),
    "3": ("ажиллаж байсан",),
    "4": ("орохоор бүртгүүлсэн",),
    "5": ("гэрээт", "гэрээт ажилтан"),
    "6": ("өндөр настан",),
    "8": ("хөлсөөр ажиллах гэрээтэй",),
    "9": ("туршилтын хугацаатай", "туршилтын хугацааны ажилтан", "туршилтын"),
}
_EMPTYPE_UNCONFIRMED: frozenset[str] = frozenset({"8", "9"})  # meanings not yet checked with HR
_GENDER_SYNONYMS: dict[str, tuple[str, ...]] = {"M": ("эрэгтэй",), "F": ("эмэгтэй",)}
_WORK_CONDITION_SYNONYMS: dict[str, tuple[str, ...]] = {"1": ("хэвийн",), "2": ("хүнд",), "3": ("бусад",)}


def _values(
    labels: Mapping[str, str], synonyms: Mapping[str, tuple[str, ...]], unconfirmed: frozenset[str] = frozenset()
) -> tuple[ValueWords, ...]:
    """The fixed values in the table's order: the label from the table, the synonyms from `synonyms`."""
    return tuple(
        ValueWords(value=v, label=label, synonyms=synonyms[v], confirmed=v not in unconfirmed)
        for v, label in labels.items()
    )


WORDS: dict[str, FilterWords] = {
    w.param: w
    for w in (
        FilterWords(
            param="state",
            label="Төлөв",
            kind="fixed",
            description="Whether the person works here: working, upcoming (not yet started), left, or all.",
            synonyms=("төлөв", "ажиллаж байгаа эсэх"),
            values=_values(STATES, _STATE_SYNONYMS),
        ),
        FilterWords(
            param="branch",
            label="Салбар",
            kind="lookup",
            description="The branch (office) the person is placed in, given by its name.",
            synonyms=("салбар",),
        ),
        FilterWords(
            param="department",
            label="Хэлтэс",
            kind="lookup",
            description="The department the person is placed in, given by its name.",
            synonyms=("хэлтэс",),
        ),
        FilterWords(
            param="position",
            label="Албан тушаал",
            kind="lookup",
            description="The job position the person holds, given by its name.",
            synonyms=("албан тушаал", "тушаал"),
        ),
        FilterWords(
            param="emptype",
            label="Ажилтны төрөл",
            kind="fixed",
            description="The employee type (staff, contract, foreign reserve, trial period and so on).",
            synonyms=("ажилтны төрөл", "төрөл"),
            values=_values(_EMPTYPE_LABELS, _EMPTYPE_SYNONYMS, _EMPTYPE_UNCONFIRMED),
        ),
        FilterWords(
            param="gender",
            label="Хүйс",
            kind="fixed",
            description="The sex of the person: M for male, F for female.",
            synonyms=("хүйс",),
            values=_values(GENDERS, _GENDER_SYNONYMS),
        ),
        FilterWords(
            param="age_from",
            label="Нас (доод)",
            kind="number",
            description="The lowest age in years, counted on the day chosen.",
            synonyms=("нас", "доод нас", "-аас дээш нас"),
        ),
        FilterWords(
            param="age_to",
            label="Нас (дээд)",
            kind="number",
            description="The highest age in years, counted on the day chosen.",
            synonyms=("нас", "дээд нас", "-аас доош нас"),
        ),
        FilterWords(
            param="nationality",
            label="Үндэс угсаа",
            kind="lookup",
            description="The nationality (ethnic group) of the person, given by its name.",
            synonyms=("үндэс угсаа", "үндэстэн"),
        ),
        FilterWords(
            param="citizenship",
            label="Иргэншил",
            kind="lookup",
            description="The citizenship (country) of the person, given by its name.",
            synonyms=("иргэншил", "улс"),
        ),
        FilterWords(
            param="social_origin",
            label="Нийгмийн гарал",
            kind="lookup",
            description="The social origin of the person, given by its name.",
            synonyms=("нийгмийн гарал",),
        ),
        FilterWords(
            param="elected_position",
            label="Сонгуульт ажил",
            kind="lookup",
            description="The elected position the person holds, given by its name.",
            synonyms=("сонгуульт ажил", "сонгуулийн ажил"),
        ),
        FilterWords(
            param="education_level",
            label="Боловсрол",
            kind="lookup",
            description="The education level of the person, given by its name.",
            synonyms=("боловсрол", "боловсролын түвшин"),
        ),
        FilterWords(
            param="academic_degree",
            label="Эрдмийн зэрэг",
            kind="lookup",
            description="The academic degree of the person, given by its name.",
            synonyms=("эрдмийн зэрэг", "зэрэг"),
        ),
        FilterWords(
            param="marital_status",
            label="Гэрлэлтийн байдал",
            kind="lookup",
            description="The marital status of the person, given by its name.",
            synonyms=("гэрлэлтийн байдал", "гэр бүл"),
        ),
        FilterWords(
            param="housing_condition",
            label="Орон байрны нөхцөл",
            kind="lookup",
            description="The housing condition of the person, given by its name.",
            synonyms=("орон байрны нөхцөл", "орон байр"),
        ),
        FilterWords(
            param="car_ownership",
            label="Автомашин эзэмшил",
            kind="lookup",
            description="The car ownership of the person, given by its name.",
            synonyms=("автомашин эзэмшил", "машин"),
        ),
        FilterWords(
            param="clothing_size",
            label="Хувцасны хэмжээ",
            kind="lookup",
            description="The clothing size of the person, given by its name.",
            synonyms=("хувцасны хэмжээ",),
        ),
        FilterWords(
            param="shoe_size",
            label="Гутлын хэмжээ",
            kind="lookup",
            description="The shoe size of the person, given by its name.",
            synonyms=("гутлын хэмжээ",),
        ),
        FilterWords(
            param="bank",
            label="Банк",
            kind="lookup",
            description="The bank the person's salary is paid to, given by its name.",
            synonyms=("банк",),
        ),
        FilterWords(
            param="insured_category",
            label="Даатгуулагчийн төрөл",
            kind="lookup",
            description="The insured category of the person, given by its name.",
            synonyms=("даатгуулагчийн төрөл", "даатгал"),
        ),
        FilterWords(
            param="work_conditions",
            label="Ажлын нөхцөл",
            kind="fixed",
            description="The working conditions of the job: 1 normal, 2 hard, 3 other.",
            synonyms=("ажлын нөхцөл",),
            values=_values(_WORK_CONDITIONS, _WORK_CONDITION_SYNONYMS),
        ),
        FilterWords(
            param="hired_from",
            label="Ажилд орсон (-аас)",
            kind="date",
            description="first hire date on or after (ISO date)",
            synonyms=("ажилд орсон", "ажилд авсан", "хойш"),
        ),
        FilterWords(
            param="hired_to",
            label="Ажилд орсон (-хүртэл)",
            kind="date",
            description="first hire date on or before (ISO date)",
            synonyms=("өмнө",),
        ),
        FilterWords(
            param="contract_end_from",
            label="Гэрээ дуусах (-аас)",
            kind="date",
            description="contract end date on or after (ISO date)",
            synonyms=("гэрээ дуусах",),
        ),
        FilterWords(
            param="contract_end_to",
            label="Гэрээ дуусах (-хүртэл)",
            kind="date",
            description="contract end date on or before (ISO date)",
            synonyms=("гэрээ дуусах",),
        ),
        FilterWords(
            param="salary_from",
            label="Үндсэн цалин (доод)",
            kind="number",
            description="The lowest basic salary (a number).",
            synonyms=("цалин", "доод цалин"),
        ),
        FilterWords(
            param="salary_to",
            label="Үндсэн цалин (дээд)",
            kind="number",
            description="The highest basic salary (a number).",
            synonyms=("цалин", "дээд цалин"),
        ),
    )
}

# The staff table's grouping keys: the only values a chart may be grouped by (the plan's chart_by).
GROUP_OPTIONS: tuple[str, ...] = REPORT.group_options


def offered_words(user: User) -> list[FilterWords]:
    """The words of the filters the staff table offers this user, in the table's order. A range lists both of its
    bounds; the as-of day is not a filter word."""
    params: list[str] = []
    for name in offered_filters(REPORT, user):
        if name == "as_of":
            continue
        params.extend(("age_from", "age_to") if name == "age_range" else (name,))
    for name in offered_column_filters(REPORT, user):
        params.extend(params_of(COLUMN_FILTERS[name]))
    return [WORDS[p] for p in params]

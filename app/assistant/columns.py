"""The staff list columns the assistant may offer the model as rule columns: the columns the user may see, each with its
kind, the operators that kind takes, and the Mongolian words a question may use for it."""

from dataclasses import dataclass
from typing import Any

from accounts.models import User
from reports import rules
from reports.kinds import column_kind
from reports.staff_list import REPORT
from reports.table import allowed_columns

# Mongolian words a question may use for a column, by column key. Written for the staff list; native read pending.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "years_worked": ("ажилласан жил", "стаж", "ажилласан"),
    "contract_end": ("гэрээ дуусах", "гэрээ дуусах хугацаа"),
    "probation_end": ("туршилт дуусах", "туршилтын хугацаа"),
    "work_phone": ("утас", "ажлын утас"),
    "private_phone": ("хувийн утас",),
    "email": ("имэйл", "и-мэйл"),
    "first_hire_date": ("ажилд орсон",),
    "birth_date": ("төрсөн огноо",),
    "salary": ("цалин",),
    "name": ("нэр",),
    "address": ("хаяг",),
}


@dataclass(frozen=True)
class RuleColumn:
    """One staff list column the model may filter on: its key, header label, kind, operators and synonyms."""

    key: str
    label: str
    kind: str
    ops: tuple[str, ...]
    synonyms: tuple[str, ...]


def offered_columns(user: User) -> list[RuleColumn]:
    """The columns the user may see, as the model is offered them."""
    out: list[RuleColumn] = []
    for column in allowed_columns(REPORT, user):
        kind = column_kind(column, [])
        out.append(
            RuleColumn(
                key=column.key,
                label=column.label,
                kind=kind,
                ops=rules.ops_for(kind),
                synonyms=SYNONYMS.get(column.key, ()),
            )
        )
    return out


def plan_extras(provider: object, user: User) -> dict[str, Any]:
    """The extra plan inputs a provider takes: the rule columns, for a provider that builds rules (`takes_rules`)."""
    if getattr(provider, "takes_rules", False):
        return {"rule_columns": offered_columns(user)}
    return {}

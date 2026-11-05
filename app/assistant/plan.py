"""The plan the model returns for a question about the staff table: which tool answers it, the filter parts it
found, and the words it could not place. `parse_plan` checks the shape strictly and clamps the content, so nothing
the model writes can break the code that runs the plan."""

from dataclasses import dataclass
from typing import Any

from assistant.prompt import CHART_KINDS, TOOLS, WANTS
from assistant.providers import ProviderError

MAX_PARTS = 12
MAX_LEAD = 200
MAX_SHORT = 60  # entry, also, chart_by
MAX_PARAM = 40
MAX_VALUE = 200
MAX_UNMAPPED = 100

_SCHEMA_ERROR = "the model reply does not match the schema"


@dataclass(frozen=True)
class Part:
    param: str  # the filter's query parameter: "department", "emptype", "age_from" ...
    value: str  # a listed value, an ISO date, digits, or the words heard for a lookup filter


@dataclass(frozen=True)
class Plan:
    tool: str  # "entry" | "staff_table" | "none"
    entry: str  # help entry key, "" unless tool == "entry"
    also: str
    lead: str
    parts: tuple[Part, ...]
    unmapped: tuple[str, ...]  # words the model could not place
    want: str  # "list" | "count" | "chart"
    chart_kind: str  # "bar" | "pie" | ""
    chart_by: str  # a group option key or ""


def _text(data: dict[str, Any], key: str, limit: int) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProviderError(_SCHEMA_ERROR)
    return value[:limit]


def _parts(data: dict[str, Any]) -> tuple[Part, ...]:
    raw = data.get("parts")
    if not isinstance(raw, list):
        raise ProviderError(_SCHEMA_ERROR)
    parts: list[Part] = []
    for item in raw[:MAX_PARTS]:  # cut first: an item past the cap is never checked
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("param"), str)
            or not isinstance(item.get("value"), str)
        ):
            raise ProviderError(_SCHEMA_ERROR)
        parts.append(Part(param=item["param"][:MAX_PARAM], value=item["value"][:MAX_VALUE]))
    return tuple(parts)


def _unmapped(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("unmapped")
    if not isinstance(raw, list):
        raise ProviderError(_SCHEMA_ERROR)
    words: list[str] = []
    for item in raw[:MAX_PARTS]:  # the same cap as the parts, cut before the check
        if not isinstance(item, str):
            raise ProviderError(_SCHEMA_ERROR)
        words.append(item[:MAX_UNMAPPED])
    return tuple(words)


def parse_plan(data: Any) -> Plan:
    """Build the Plan from a parsed reply. Raises ProviderError when the shape is wrong; clamps the content."""
    if not isinstance(data, dict):
        raise ProviderError(_SCHEMA_ERROR)
    tool = _text(data, "tool", 60)
    entry = _text(data, "entry", MAX_SHORT)
    want = _text(data, "want", 60)
    chart_kind = _text(data, "chart_kind", 60)
    tool = tool if tool in TOOLS else "none"
    if tool == "entry" and not entry:
        tool = "none"  # an entry tool without an entry answers nothing
    return Plan(
        tool=tool,
        entry=entry,
        also=_text(data, "also", MAX_SHORT),
        lead=_text(data, "lead", MAX_LEAD),
        parts=_parts(data),
        unmapped=_unmapped(data),
        want=want if want in WANTS else "list",
        chart_kind=chart_kind if chart_kind in CHART_KINDS else "",
        chart_by=_text(data, "chart_by", MAX_SHORT),
    )

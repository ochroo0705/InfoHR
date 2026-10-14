"""How a field value is written into the activity log: what people see, not the stored code."""

from datetime import date
from typing import Any


def shown(field: Any, value: Any) -> str:
    """'long_leave' -> 'Урт хугацааны чөлөөтэй', True -> 'Тийм', dates as YYYY-MM-DD.

    `field` is what Model._meta.get_field returns (a wide union in the stubs, hence Any).
    """
    if value is None or value == "":
        return ""
    choices = getattr(field, "flatchoices", None)
    if choices:
        return str(dict(choices).get(value, value))
    if isinstance(value, bool):
        return "Тийм" if value else "Үгүй"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

"""Money amounts: one format everywhere (2500000 -> "2,500,000"), and a form field that accepts it back."""

from decimal import Decimal, InvalidOperation
from typing import Any

from django import forms


def group(value: Decimal | int | str) -> str:
    """2500000 -> '2,500,000'; decimals only when not whole (1234.5 -> '1,234.50')."""
    return f"{Decimal(value):,.2f}".removesuffix(".00")


class MoneyInput(forms.TextInput):
    """Text box grouped by commas as the user types (static/js/money.js); inputmode brings up the number pad."""

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        super().__init__({"data-money": "", "inputmode": "decimal", "autocomplete": "off", **(attrs or {})})

    def format_value(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        try:
            return group(value)
        except (InvalidOperation, ValueError, TypeError):
            return str(value)  # whatever the user typed, shown back with the error


class MoneyField(forms.DecimalField):
    """DecimalField that takes "2,500,000" (commas and spaces are ignored)."""

    widget = MoneyInput

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", 0)
        super().__init__(**kwargs)

    def to_python(self, value: Any) -> Any:
        if isinstance(value, str):
            value = value.replace(",", "").replace(" ", "").replace(" ", "")
        return super().to_python(value)

    def widget_attrs(self, widget: forms.Widget) -> dict[str, Any]:
        attrs = super().widget_attrs(widget)
        attrs.pop("step", None)  # number-input attrs make no sense on a text box
        attrs.pop("min", None)
        attrs.pop("max", None)
        return attrs

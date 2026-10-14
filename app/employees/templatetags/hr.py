from datetime import date, datetime, timedelta
from decimal import Decimal

from django import template
from django.db.models.fields.files import FieldFile
from django.forms import BoundField, CheckboxInput, Select, Textarea
from django.utils import timezone

register = template.Library()


@register.filter
def thumb(photo: FieldFile, side: int) -> str:
    """URL of the photo cropped to a side x side px square (see images.thumbnail_url)."""
    from employees.images import thumbnail_url

    return thumbnail_url(photo, int(side))


@register.filter
def mnt(value: Decimal | str | None) -> str:
    """2500000 -> '2 500 000₮' (space thousands, no decimals unless needed)."""
    if value is None or value == "":  # missing template variable renders as ""
        return "—"
    whole = f"{value:,.2f}".replace(",", " ").removesuffix(".00")
    return f"{whole}₮"


INLINE = "border-b border-transparent bg-transparent hover:border-slate-300 focus:border-violet-600 focus:outline-none"


@register.inclusion_tag("employees/_field.html")
def field(bound: BoundField, width: str = "w-full") -> dict[str, object]:
    """An edit-in-place input: looks like the text it replaces, with its errors underneath."""
    checkbox = isinstance(bound.field.widget, CheckboxInput)
    css = "h-4 w-4 accent-violet-600" if checkbox else f"{width} {INLINE}"
    attrs: dict[str, str | bool] = {"class": css, "form": "emp-form", "autocomplete": "off"}
    attrs["aria-label"] = str(bound.label)
    if not checkbox and not isinstance(bound.field.widget, Select):
        attrs["placeholder"] = "—"
    if isinstance(bound.field.widget, Textarea):
        # Django's default is 10 rows; start at one line and grow with the text.
        attrs["rows"] = "1"
        attrs["class"] = f"{css} resize-none [field-sizing:content]"
    return {"widget": bound.as_widget(attrs=attrs), "errors": bound.errors}


@register.filter
def day_label(value: datetime, today: date) -> str:
    """Activity day heading: Өнөөдөр / Өчигдөр / 2026-10-12."""
    day = timezone.localtime(value).date()
    if day == today:
        return "Өнөөдөр"
    if day == today - timedelta(days=1):
        return "Өчигдөр"
    return day.isoformat()

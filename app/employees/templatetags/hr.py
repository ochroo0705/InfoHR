from datetime import date, datetime, timedelta
from decimal import Decimal

from django import template
from django.forms import BoundField, CheckboxInput, Form, Select, Textarea
from django.utils import timezone

from employees.models import Employee
from employees.money import group

register = template.Library()


@register.filter
def thumb(employee: Employee, side: int) -> str:
    """URL of the employee's photo cropped to a side x side px square ("" when no photo)."""
    from employees.images import thumbnail_url

    return thumbnail_url(employee, int(side))


@register.filter
def mnt(value: Decimal | str | None) -> str:
    """2500000 -> '2,500,000₮' (comma thousands, no decimals unless needed)."""
    if value is None or value == "":  # missing template variable renders as ""
        return "—"
    return f"{group(value)}₮"


BOXED = "rounded-lg border border-slate-300 px-3 py-2 text-sm"
INLINE = "border-b border-transparent bg-transparent hover:border-slate-300 focus:border-violet-600 focus:outline-none"
# Edit on the spot inside a tab's field grid (UI_RULES §2e): a quiet box that is always there, so an
# editable value never looks like plain text. `f-soft` is the hook for the changed-field marker.
SOFT = (
    "f-soft rounded-md border border-slate-200 bg-slate-50 px-2 py-1 hover:border-slate-400 hover:bg-white"
    " focus:border-violet-600 focus:bg-white focus:outline-none"
)


@register.inclusion_tag("employees/_field.html")
def field(
    bound: BoundField,
    width: str = "w-full",
    form_id: str = "emp-form",
    boxed: bool = False,
    soft: bool = False,
) -> dict[str, object]:
    """An edit-in-place input: looks like the text it replaces, with its errors underneath.
    `form_id` is the id of the <form> the input posts with (a section form has its own).
    `boxed` gives the bordered input of a form (UI_RULES §2) instead of the borderless edit-in-place one;
    `soft` gives the quiet always-visible box of a tab's field grid (UI_RULES §2e)."""
    checkbox = isinstance(bound.field.widget, CheckboxInput)
    if checkbox:
        css = "h-4 w-4 accent-violet-600"
    else:
        css = f"{width} {BOXED if boxed else SOFT if soft else INLINE}"
    attrs: dict[str, str | bool] = {"class": css, "form": form_id, "autocomplete": "off"}
    attrs["aria-label"] = str(bound.label)
    if not checkbox and not isinstance(bound.field.widget, Select):
        attrs["placeholder"] = bound.field.widget.attrs.get("placeholder", "—")
    if isinstance(bound.field.widget, Textarea):
        # Django's default is 10 rows; start at one line and grow with the text.
        attrs["rows"] = "1"
        attrs["class"] = f"{css} resize-none [field-sizing:content]"
    conflict = getattr(bound.form, "conflicts", {}).get(bound.name)
    return {
        "widget": bound.as_widget(attrs=attrs),
        "errors": bound.errors,
        "conflict": conflict,
        "resolve_name": f"resolve-{bound.html_name}",
        "form_id": form_id,
    }


@register.filter
def loaded_snapshot(form: Form) -> str:
    """The hidden `loaded` value of an employee page form (employees.stale)."""
    from employees import stale

    return stale.snapshot(form)


@register.filter
def day_label(value: datetime, today: date) -> str:
    """Activity day heading: Өнөөдөр / Өчигдөр / 2026-10-12."""
    day = timezone.localtime(value).date()
    if day == today:
        return "Өнөөдөр"
    if day == today - timedelta(days=1):
        return "Өчигдөр"
    return day.isoformat()


@register.inclusion_tag("employees/_inline_list.html", takes_context=True)
def inline_list(context: template.Context, kind: str) -> dict[str, object]:
    """A personal list edited in its own rows (UI_RULES §2f), closed, from the personal tab's context."""
    from employees import sections

    return sections.inline_context(
        context["employee"], kind, context["personal"][kind], bool(context.get("can_manage"))
    )

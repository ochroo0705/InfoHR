"""Template filters for the log pages."""

from accounts.audit import ACTIONS, Category
from django import template

register = template.Library()


@register.filter
def action_label(code: str) -> str:
    """The Mongolian label of an action code; an unknown code shows as it is stored."""
    return ACTIONS.get(code, code)


@register.filter
def category_label(code: str) -> str:
    """The Mongolian label of a category code. The stored field has no choices, so `get_category_display` is blank."""
    return dict(Category.choices).get(code, code)

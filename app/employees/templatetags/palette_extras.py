"""Template filters for the Ctrl+K palette rows (see `employees.palette.highlight`)."""

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from employees.palette import highlight

register = template.Library()

MARK_CLASS = "rounded bg-violet-200/60 text-inherit"  # the highlight of a typed match (UI_RULES §6c)


@register.filter
def hl(text: object, words: list[str] | None) -> str:
    """The text with the letters of the typed words marked. Every piece is escaped first, so a name with `<` shows as
    text; only the matched pieces are wrapped in a <mark>. No words (the empty box, recent items) marks nothing."""
    if text is None:
        return ""
    parts = []
    for piece, matched in highlight(str(text), list(words or [])):
        escaped = conditional_escape(piece)
        parts.append(f'<mark class="{MARK_CLASS}">{escaped}</mark>' if matched else escaped)
    return mark_safe("".join(parts))  # noqa: S308 - every piece above was escaped

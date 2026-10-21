"""Marks the form dropdowns whose list can take a new entry on the spot (docs/UI_RULES.md §2a)."""

from typing import Any

from django import forms
from django.urls import reverse

from lists.registry import QUICK, QUICK_BY_MODEL


def mark_addable(fields: Any) -> None:
    """Give every addable ModelChoiceField the attributes select.js needs to offer «+ нэмэх»."""
    for field in fields.values():
        if not isinstance(field, forms.ModelChoiceField) or isinstance(field, forms.ModelMultipleChoiceField):
            continue
        slug = QUICK_BY_MODEL.get(getattr(field.queryset, "model", None))
        if slug is None:
            continue
        attrs = field.widget.attrs
        attrs["data-add-url"] = reverse("lists:quick_add", args=[slug])
        if QUICK[slug].modal:
            attrs["data-add-modal"] = "1"
        if QUICK[slug].parent:
            attrs["data-add-parent"] = QUICK[slug].parent

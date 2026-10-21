from django import forms
from employees.forms import StyledModelForm

from lists.registry import FIELD_LABELS, ListSpec


def list_fields(spec: ListSpec) -> list[str]:
    return ["name", *spec.extra_fields, *([spec.parent] if spec.parent else [])]


def entry_form(spec: ListSpec) -> type[forms.ModelForm]:  # type: ignore[type-arg]
    fields = list_fields(spec)
    return forms.modelform_factory(
        spec.model,
        form=StyledModelForm,
        fields=fields,
        labels={name: FIELD_LABELS[name] for name in fields if name in FIELD_LABELS},
    )

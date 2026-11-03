from typing import Any, cast

from django import forms
from django.contrib.auth.models import Group
from employees.models import EmployeeType
from macs.models import FiredReason
from unfold.widgets import UnfoldAdminCheckboxSelectMultiple

from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask

MANAGER_OWNER = "manager"


def owner_choices() -> list[tuple[str, str]]:
    """One choice per role group, plus the direct manager. Values: "manager" or "group:<id>"."""
    return [(MANAGER_OWNER, "Шууд удирдлага")] + [(f"group:{g.pk}", g.name) for g in Group.objects.order_by("name")]


def template_match_choices(kind: str) -> list[tuple[str, str]]:
    """What a template of `kind` can list: fired reasons (value = pk as text) for offboarding, employment types
    (value = EmployeeType value) for onboarding. Unknown kind: nothing."""
    if kind == ChecklistKind.OFFBOARDING:
        return [(str(r.pk), r.name) for r in FiredReason.objects.order_by("name")]
    if kind == ChecklistKind.ONBOARDING:
        return [(str(value), str(label)) for value, label in EmployeeType.choices]
    return []


class GroupedChips(UnfoldAdminCheckboxSelectMultiple):  # type: ignore[misc]
    """Checkboxes as ticking chips, one fieldset per kind (the group name is the kind value)."""

    template_name = "checklists/widgets/grouped_chips.html"
    option_template_name = "checklists/widgets/chip_option.html"


class ChecklistTemplateForm(forms.ModelForm):  # type: ignore[type-arg]
    """The kind may be chosen on this same form, so the field offers both kinds' values (labelled by kind) and
    `clean` keeps only values that belong to the chosen kind."""

    reasons = forms.MultipleChoiceField(
        label="Шалтгаан / ажлын төрөл",
        required=False,
        choices=(),
        widget=GroupedChips,
        help_text="Хоосон бол энэ төрлийн бүх тохиолдолд ашиглана.",
    )

    class Meta:
        model = ChecklistTemplate
        fields = ("kind", "name", "is_default", "reasons", "active")

    class Media:
        js = ("js/admin_checklist_kind.js",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        reasons = cast(forms.ChoiceField, self.fields["reasons"])
        # One group per kind; the widget titles it and the page script shows only the chosen kind's group.
        reasons.choices = [
            (str(kind), template_match_choices(kind)) for kind in (ChecklistKind.OFFBOARDING, ChecklistKind.ONBOARDING)
        ]

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        kind = cleaned.get("kind")
        values = cleaned.get("reasons") or []
        if kind and values:
            allowed = {value for value, _label in template_match_choices(kind)}
            if any(value not in allowed for value in values):
                self.add_error("reasons", "Сонгосон утга энэ төрлийн загварт тохирохгүй байна.")
        return cleaned


class ChecklistTemplateTaskForm(forms.ModelForm):  # type: ignore[type-arg]
    """The one owner field maps onto the model's group / manager pair (exactly one is set)."""

    owner = forms.ChoiceField(label="Хариуцах", choices=())

    class Meta:
        model = ChecklistTemplateTask
        fields = ("position", "title", "owner", "due_offset_days", "required")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["owner"]).choices = owner_choices()
        if self.instance.pk:
            self.initial["owner"] = MANAGER_OWNER if self.instance.manager else f"group:{self.instance.group_id}"

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        owner = cleaned.get("owner")
        if owner == MANAGER_OWNER:
            self.instance.manager = True
            self.instance.group = None
        elif owner:
            self.instance.manager = False
            self.instance.group_id = int(owner.split(":", 1)[1])
        return cleaned

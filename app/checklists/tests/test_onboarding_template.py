"""The starter onboarding template, its migration and the template form's per-kind match values."""

import importlib

import pytest
from accounts.roles import ADMIN, HR
from django.apps import apps
from django.contrib.auth.models import Group
from macs.models import FiredReason

from checklists.forms import ChecklistTemplateForm, template_match_choices
from checklists.models import ChecklistKind, ChecklistTemplate
from checklists.services import lifecycle

migration = importlib.import_module("checklists.migrations.0005_onboarding_starter")

# title, owner group name (None = direct manager), offset days, required
EXPECTED = [
    ("Ажлын байр бэлтгэх", None, -3, True),
    ("Бүртгэл, и-мэйл үүсгэх", "Admin", -1, True),
    ("Бичиг баримт цуглуулж, гэрээ болон тушаалыг баталгаажуулах", "HR", 0, True),
    ("Угтан авч, ажлын үүргийг танилцуулах", None, 0, True),
    ("Дотоод журмыг тайлбарлах", "HR", 1, True),
    ("Цалингийн банкны дансны мэдээлэл авах", "Accountant", 0, True),
    ("Эхний сарын зорилгыг тохиролцох", None, 7, False),
]


def _starter() -> ChecklistTemplate | None:
    return ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING, is_default=True).first()


@pytest.mark.django_db
def test_starter_onboarding_template_has_the_seven_tasks_in_order() -> None:
    template = _starter()
    assert template is not None and template.active and template.reasons == []
    rows = [
        (t.title, t.group.name if t.group else None, t.due_offset_days, t.required)
        for t in template.tasks.select_related("group").order_by("position")
    ]
    assert rows == EXPECTED
    assert [t.manager for t in template.tasks.order_by("position")] == [g is None for _, g, _, _ in EXPECTED]


@pytest.mark.django_db
def test_missing_group_skips_whole_onboarding_starter_with_warning() -> None:
    ChecklistTemplate.objects.filter(is_default=True).delete()  # both starters use the groups
    Group.objects.get(name="Accountant").delete()
    with pytest.warns(UserWarning, match="Accountant"):
        migration.seed_onboarding(apps, None)
    assert not ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).exists()


@pytest.mark.django_db
def test_seed_is_idempotent_and_reversible() -> None:
    migration.seed_onboarding(apps, None)
    assert ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).count() == 1
    migration.unseed_onboarding(apps, None)
    assert _starter() is None
    migration.seed_onboarding(apps, None)
    assert _starter() is not None


@pytest.mark.django_db
def test_intern_template_wins_over_default() -> None:
    default = _starter()
    assert default is not None
    intern = ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="Дадлага", reasons=["intern"])
    assert lifecycle.template_for("onboarding", "intern") == intern
    assert lifecycle.template_for("onboarding", "full_time") == default
    assert lifecycle.template_for("onboarding", None) == default


@pytest.mark.django_db
def test_match_choices_per_kind(fired_reason: FiredReason) -> None:
    off = dict(template_match_choices("offboarding"))
    on = dict(template_match_choices("onboarding"))
    assert str(fired_reason.pk) in off and "intern" not in off
    assert "intern" in on and "full_time" in on and str(fired_reason.pk) not in on


def _data(kind: str, reasons: list[str]) -> dict[str, object]:
    return {"kind": kind, "name": "Загвар", "reasons": reasons, "active": "on"}


@pytest.mark.django_db
def test_form_accepts_values_of_the_chosen_kind(fired_reason: FiredReason) -> None:
    assert ChecklistTemplateForm(_data("onboarding", ["intern"])).is_valid()
    assert ChecklistTemplateForm(_data("offboarding", [str(fired_reason.pk)])).is_valid()


@pytest.mark.django_db
def test_form_rejects_values_outside_the_kinds_choices(fired_reason: FiredReason) -> None:
    for kind, value in (("onboarding", str(fired_reason.pk)), ("offboarding", "intern"), ("onboarding", "nonsense")):
        form = ChecklistTemplateForm(_data(kind, [value]))
        assert not form.is_valid()
        assert "reasons" in form.errors


@pytest.mark.django_db
def test_admin_and_hr_groups_exist_for_seeding() -> None:
    assert Group.objects.filter(name__in=[ADMIN, HR]).count() == 2

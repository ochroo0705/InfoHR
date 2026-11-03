"""The template editor's owner field: one choice maps onto the task's group / manager pair (form tested directly)."""

import pytest
from accounts.roles import ADMIN, HR
from django.contrib.auth.models import Group

from checklists.forms import MANAGER_OWNER, ChecklistTemplateTaskForm
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask


def _template() -> ChecklistTemplate:
    return ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="Админ тест")


def _data(owner: str) -> dict[str, object]:
    return {"position": 1, "title": "Даалгавар", "owner": owner, "due_offset_days": 0, "required": "on"}


@pytest.mark.django_db
def test_role_choice_maps_to_group_and_clears_manager() -> None:
    hr = Group.objects.get(name=HR)
    template = _template()
    task = ChecklistTemplateTask(template=template)
    form = ChecklistTemplateTaskForm(_data(f"group:{hr.pk}"), instance=task)

    assert form.is_valid(), form.errors
    assert form.instance.group_id == hr.pk
    assert form.instance.manager is False


@pytest.mark.django_db
def test_manager_choice_maps_to_manager_flag_and_clears_group() -> None:
    template = _template()
    task = ChecklistTemplateTask(template=template)
    form = ChecklistTemplateTaskForm(_data(MANAGER_OWNER), instance=task)

    assert form.is_valid(), form.errors
    assert form.instance.manager is True
    assert form.instance.group is None


@pytest.mark.django_db
def test_editing_switches_owner_from_manager_to_role() -> None:
    admin = Group.objects.get(name=ADMIN)
    template = _template()
    existing = ChecklistTemplateTask.objects.create(
        template=template, position=1, title="Даалгавар", manager=True, due_offset_days=0
    )
    form = ChecklistTemplateTaskForm(_data(f"group:{admin.pk}"), instance=existing)

    assert form.is_valid(), form.errors
    assert form.instance.group_id == admin.pk
    assert form.instance.manager is False


@pytest.mark.django_db
def test_no_owner_is_rejected() -> None:
    form = ChecklistTemplateTaskForm(_data(""), instance=ChecklistTemplateTask(template=_template()))

    assert not form.is_valid()
    assert "owner" in form.errors


@pytest.mark.django_db
def test_unknown_role_is_rejected() -> None:
    form = ChecklistTemplateTaskForm(_data("group:999999"), instance=ChecklistTemplateTask(template=_template()))

    assert not form.is_valid()
    assert "owner" in form.errors


@pytest.mark.django_db
def test_both_owners_cannot_be_sent_from_the_form() -> None:
    # The form has one owner field, so "group and manager" is not expressible here; the model's constraint
    # (test_models.test_task_needs_exactly_one_owner) is what rejects a task with both.
    template = _template()
    form = ChecklistTemplateTaskForm(
        _data(MANAGER_OWNER) | {"group": Group.objects.get(name=HR).pk},
        instance=ChecklistTemplateTask(template=template),
    )

    assert form.is_valid(), form.errors
    assert form.instance.manager is True
    assert form.instance.group is None

import pytest
from accounts.roles import ADMIN
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask


@pytest.mark.django_db
def test_task_needs_exactly_one_owner() -> None:
    template = ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="Тест")
    no_owner = ChecklistTemplateTask(template=template, position=1, title="Гарчиг")
    with pytest.raises(ValidationError):
        no_owner.full_clean()
    both = ChecklistTemplateTask(
        template=template, position=2, title="Гарчиг", group=Group.objects.get(name=ADMIN), manager=True
    )
    with pytest.raises(ValidationError):
        both.full_clean()


@pytest.mark.django_db
def test_one_default_template_per_kind() -> None:
    # The seeded onboarding default already exists: a second default of that kind is refused.
    assert ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING, is_default=True).exists()
    second = ChecklistTemplate(kind=ChecklistKind.ONBOARDING, name="Хоёр дахь", is_default=True)
    with pytest.raises(ValidationError):
        second.full_clean()


@pytest.mark.django_db
def test_default_templates_of_different_kinds_are_allowed() -> None:
    # Both seeded defaults coexist: one per kind.
    assert ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING, is_default=True).count() == 1
    assert ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING, is_default=True).count() == 1
    for default in ChecklistTemplate.objects.filter(is_default=True):
        default.full_clean()


def _owner_label(task: ChecklistTemplateTask) -> str:
    if task.manager:
        return "manager"
    assert task.group is not None
    return task.group.name


@pytest.mark.django_db
def test_starter_template_and_permissions_after_migrations() -> None:
    template = ChecklistTemplate.objects.get(kind=ChecklistKind.OFFBOARDING, is_default=True)
    # (title, owner: "manager" or the role group name, due_offset_days, required), in order (plan Task 1 step 3).
    expected = [
        ("Ажлаа хүлээлгэн өгөх", "manager", -3, True),
        ("Эд хөрөнгө, тоног төхөөрөмж буцаах", "HR", 0, True),
        ("Нэвтрэх эрх хаах", "Admin", 0, True),
        ("Эцсийн тооцоо шалгах", "Accountant", 0, True),
        ("Ажлаас гарах ярилцлага", "HR", 0, False),
    ]
    got = [
        (task.title, _owner_label(task), task.due_offset_days, task.required)
        for task in template.tasks.select_related("group").order_by("position", "pk")
    ]
    assert got == expected

    admin = Group.objects.get(name=ADMIN)
    codes = admin.permissions.filter(content_type__app_label="checklists").values_list("codename", flat=True)
    assert {"manage_checklists", "override_offboarding"} <= set(codes)

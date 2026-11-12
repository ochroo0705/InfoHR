"""The checklist and order templates an admin keeps are entries built per user."""

from collections.abc import Callable

import pytest
from accounts.models import User
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from employees.models import OrderTemplate, OrderType

from assistant.entries import ENTRY_BY_KEY, allowed_entries
from assistant.tests.conftest import PASSWORD, TODAY

pytestmark = pytest.mark.django_db


def _keys(user: User, prefix: str) -> list[str]:
    return [e.key for e in allowed_entries(user, TODAY) if e.key.startswith(prefix)]


def _root() -> User:
    return User.objects.create_superuser("help_templates_root", password=PASSWORD)


def test_a_checklist_template_becomes_an_entry_naming_its_tasks() -> None:
    template = ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Тусгай гарах загвар")
    ChecklistTemplateTask.objects.create(template=template, title="Түлхүүр хүлээлгэх", manager=True)
    ChecklistTemplateTask.objects.create(template=template, title="Компьютер хураах", manager=True)
    entry = next(e for e in allowed_entries(_root(), TODAY) if e.key == f"checklist.template.{template.pk}")
    assert "Тусгай гарах загвар" in entry.title
    assert "Түлхүүр хүлээлгэх; Компьютер хураах" in " ".join(entry.steps)
    assert "Түлхүүр хүлээлгэх" in entry.words
    assert entry.url().endswith(f"/{template.pk}/change/")
    assert entry.key not in ENTRY_BY_KEY


def test_an_inactive_template_says_so_and_a_long_one_is_cut() -> None:
    template = ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="Хуучин загвар", active=False)
    for n in range(15):
        ChecklistTemplateTask.objects.create(template=template, title=f"Даалгавар {n}", manager=True, position=n)
    entry = next(e for e in allowed_entries(_root(), TODAY) if e.key == f"checklist.template.{template.pk}")
    assert "идэвхгүй" in entry.note
    assert "ба өөр 3 даалгавар" in " ".join(entry.steps)


def test_checklist_templates_follow_the_admin_changes() -> None:
    root = _root()
    template = ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Эхний нэр")
    key = f"checklist.template.{template.pk}"
    assert key in _keys(root, "checklist.template.")
    template.name = "Шинэ нэр"
    template.save()
    entry = next(e for e in allowed_entries(root, TODAY) if e.key == key)
    assert "Шинэ нэр" in entry.title
    template.delete()
    assert key not in _keys(root, "checklist.template.")


def test_an_order_entry_for_each_type_and_the_uploaded_file_is_noticed() -> None:
    root = _root()
    OrderTemplate.ensure_all()
    keys = _keys(root, "order.template.")
    assert keys == [f"order.template.{value}" for value in OrderType.values]
    hired = next(e for e in allowed_entries(root, TODAY) if e.key == f"order.template.{OrderType.HIRED.value}")
    assert "стандарт" in hired.note
    OrderTemplate.objects.filter(order_type=OrderType.HIRED).update(file="templates/own.docx")
    hired = next(e for e in allowed_entries(root, TODAY) if e.key == f"order.template.{OrderType.HIRED.value}")
    assert "өөрийн оруулсан" in hired.note


def test_a_user_without_the_template_rights_gets_none(role_user: Callable[[str], User]) -> None:
    ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Хаалттай загвар")
    for kind in ("hr", "accountant", "staff", "none"):
        user = role_user(kind)
        assert _keys(user, "checklist.template.") == []
        assert _keys(user, "order.template.") == []

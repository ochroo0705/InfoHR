"""The settings page's rules: the type list, the type form's starting values, the approval choices and the two saves.

These tests pin the rules the Django views in app/leave/views.py rely on.
"""

import pytest
from accounts import audit_context
from accounts.models import SystemLogEntry, User
from accounts.roles import ADMIN, ROLE_LABELS
from django.contrib.auth.models import Group
from macs.models import LeaveTypeRow

from leave.forms import GROUP_PREFIX, MANAGER_CHOICE, LeaveTypeForm
from leave.models import LeaveSettings, type_ext
from leave.services import writes
from leave.services.settings_page import (
    approval_choices,
    approval_initial,
    ext_values,
    save_approval,
    save_auto_grant,
    type_initial,
    type_rows,
)

pytestmark = pytest.mark.django_db

VALUES = {"is_paid": True, "uses_annual_balance": False, "is_active": True, "order": 0, "staff_may_request": True}


def _type(name: str, **changes: object) -> LeaveTypeRow:
    return writes.save_leave_type(name, {**VALUES, **changes})


def test_type_rows_sorted_by_order_then_name() -> None:
    late = _type("Б төрөл", order=5)
    early_b = _type("Б төрөл2", order=1)
    early_a = _type("А төрөл", order=1)

    pairs = type_rows()

    assert [row.pk for row, _ in pairs] == [early_a.pk, early_b.pk, late.pk]
    assert all(ext.leave_type_id == row.pk for row, ext in pairs)


def test_type_rows_gives_defaults_to_a_type_without_an_ext_row() -> None:
    bare = LeaveTypeRow.objects.create(name="Ext байхгүй")

    [(row, ext)] = type_rows()

    assert row.pk == bare.pk
    expected = type_ext(bare)
    assert ext.order == expected.order == 0
    assert ext.is_active == expected.is_active
    assert ext.is_paid == expected.is_paid
    assert ext.uses_annual_balance == expected.uses_annual_balance
    assert ext.staff_may_request == expected.staff_may_request


def test_type_initial_keys_match_the_type_form() -> None:
    row = _type("Form төрөл", order=3, staff_may_request=False)

    initial = type_initial(row)

    assert set(initial) == set(LeaveTypeForm().fields)
    assert initial == {
        "name": "Form төрөл",
        "is_paid": True,
        "uses_annual_balance": False,
        "is_active": True,
        "order": 3,
        "staff_may_request": False,
    }


def test_ext_values_keeps_only_the_extension_fields() -> None:
    cleaned = {"name": "Нэр", **VALUES, "order": 7}

    values = ext_values(cleaned)

    assert values == {**VALUES, "order": 7}
    assert "name" not in values


def test_approval_choices_start_with_empty_and_manager_then_each_group() -> None:
    admin, _ = Group.objects.get_or_create(name=ADMIN)
    manager_group = Group.objects.create(name="Pilot role")

    step1, step2 = approval_choices()

    assert step1[0] == ("", "Батлахгүй")
    assert step1[1] == (MANAGER_CHOICE, "Шууд удирдлага")
    group_choices = [choice for choice in step1 if choice[0].startswith(GROUP_PREFIX)]
    assert (f"{GROUP_PREFIX}{admin.pk}", ROLE_LABELS[ADMIN]) in group_choices
    assert (f"{GROUP_PREFIX}{manager_group.pk}", "Pilot role") in group_choices
    assert len(group_choices) == Group.objects.count()

    assert step2[0] == ("", "—")
    assert step2[1:] == step1[1:]


def test_approval_initial_encodes_both_steps() -> None:
    group = Group.objects.create(name="Approver role")
    setting = LeaveSettings.get()
    setting.approval1_group = group
    setting.approval2_manager = True
    setting.save()

    assert approval_initial(setting) == {
        "step1": f"{GROUP_PREFIX}{group.pk}",
        "step2": MANAGER_CHOICE,
    }


def test_approval_initial_empty_when_no_approval_is_set() -> None:
    assert approval_initial(LeaveSettings.get()) == {"step1": "", "step2": ""}


def test_save_approval_stores_groups_and_flags_and_clears_removed_flag() -> None:
    group = Group.objects.create(name="Step role")
    setting = LeaveSettings.get()
    setting.approval_role_removed = True
    setting.save()

    save_approval(
        setting,
        {
            "approval1_group_id": group.pk,
            "approval1_manager": False,
            "approval2_group_id": None,
            "approval2_manager": True,
        },
    )

    stored = LeaveSettings.objects.get(pk=1)
    assert stored.approval1_group_id == group.pk
    assert stored.approval1_manager is False
    assert stored.approval2_group_id is None
    assert stored.approval2_manager is True
    assert stored.approval_role_removed is False


def test_save_auto_grant_flips_only_that_field() -> None:
    setting = LeaveSettings.get()
    setting.approval1_manager = True
    setting.save()

    save_auto_grant(setting, True)

    stored = LeaveSettings.objects.get(pk=1)
    assert stored.auto_annual_grant is True
    assert stored.approval1_manager is True


def test_save_auto_grant_writes_one_system_log_line(actor: User) -> None:
    audit_context.clear_context()
    audit_context.set_context(actor, None)
    try:
        setting = LeaveSettings.get()
        before = SystemLogEntry.objects.filter(action="setting_changed").count()

        save_auto_grant(setting, True)

        entries = list(SystemLogEntry.objects.filter(action="setting_changed").order_by("id"))
        assert len(entries) == before + 1
        assert entries[-1].changes == [
            {"field": "Ээлжийн амралтын эрхийг автоматаар нэмэх", "old": "Үгүй", "new": "Тийм"}
        ]
    finally:
        audit_context.clear_context()

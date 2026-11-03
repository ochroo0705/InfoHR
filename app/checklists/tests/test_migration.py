import importlib

import pytest
from accounts.roles import ADMIN
from django.apps import apps
from django.contrib.auth.models import Group

from checklists.models import ChecklistKind, ChecklistTemplate

migration = importlib.import_module("checklists.migrations.0002_permissions_and_starter")
migration_0005 = importlib.import_module("checklists.migrations.0005_onboarding_starter")


def _starter_exists() -> bool:
    return ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING, is_default=True).exists()


def _admin_has_checklist_perms() -> bool:
    codes = set(
        Group.objects.get(name=ADMIN)
        .permissions.filter(content_type__app_label="checklists")
        .values_list("codename", flat=True)
    )
    return {"manage_checklists", "override_offboarding"} <= codes


@pytest.mark.django_db
def test_missing_group_skips_whole_starter_with_warning() -> None:
    # Remove the starter and the Accountant group the starter's task needs (no task may point at it any more).
    ChecklistTemplate.objects.filter(is_default=True).delete()  # both starters use the groups
    Group.objects.get(name="Accountant").delete()

    assert migration.missing_starter_groups(Group) == ["Accountant"]
    with pytest.warns(UserWarning, match="Accountant"):
        migration.grant_admin_and_seed(apps, None)

    # All or nothing: no partial template, no tasks at all.
    assert not _starter_exists()
    assert not ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING).exists()
    # The Admin grant does not depend on the starter and still happens.
    assert _admin_has_checklist_perms()


@pytest.mark.django_db
def test_missing_admin_group_grants_nothing_and_skips_starter_with_warning() -> None:
    # Admin is also the owner of a starter task ("Нэвтрэх эрх хаах"), so its absence skips the starter as a whole.
    ChecklistTemplate.objects.filter(is_default=True).delete()  # both starters use the groups
    Group.objects.get(name=ADMIN).delete()

    with pytest.warns(UserWarning, match="Admin"):
        migration.grant_admin_and_seed(apps, None)  # must not crash without the Admin group

    assert not _starter_exists()


@pytest.mark.django_db
def test_reverse_then_forward_restores_starter_and_grants() -> None:
    migration.revoke_admin_and_unseed(apps, None)
    assert not _starter_exists()
    assert not _admin_has_checklist_perms()

    migration.grant_admin_and_seed(apps, None)
    assert _starter_exists()
    assert _admin_has_checklist_perms()


def _onboarding_starter_exists() -> bool:
    return ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING, is_default=True).exists()


@pytest.mark.django_db
def test_0005_missing_group_skips_whole_onboarding_starter_with_warning() -> None:
    ChecklistTemplate.objects.filter(is_default=True).delete()  # both starters use the Accountant group
    Group.objects.get(name="Accountant").delete()

    assert migration_0005.missing_starter_groups(Group) == ["Accountant"]
    with pytest.warns(UserWarning, match="Accountant"):
        migration_0005.seed_onboarding(apps, None)

    # All or nothing: no template and no tasks at all.
    assert not ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).exists()


@pytest.mark.django_db
def test_0005_reverse_then_forward_restores_onboarding_starter() -> None:
    migration_0005.seed_onboarding(apps, None)  # already there: a second run changes nothing
    assert ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING, is_default=True).count() == 1

    migration_0005.unseed_onboarding(apps, None)
    assert not _onboarding_starter_exists()

    migration_0005.seed_onboarding(apps, None)
    assert _onboarding_starter_exists()
    assert ChecklistTemplate.objects.get(kind=ChecklistKind.ONBOARDING, is_default=True).tasks.count() == 7

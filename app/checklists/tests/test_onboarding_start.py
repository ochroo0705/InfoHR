"""start_for_hire: which template, reuse of an open checklist, and never raising."""

from datetime import date, timedelta

import pytest
from accounts.models import User
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTemplate, ChecklistTemplateTask
from checklists.services import lifecycle, onboarding

START = date(2026, 12, 1)


def _default() -> ChecklistTemplate:
    return ChecklistTemplate.objects.get(kind=ChecklistKind.ONBOARDING, is_default=True)


def _intern_template() -> ChecklistTemplate:
    template = ChecklistTemplate.objects.create(
        kind=ChecklistKind.ONBOARDING, name="Дадлагажигч", reasons=["intern"], active=True
    )
    ChecklistTemplateTask.objects.create(template=template, position=1, title="Зөвхөн дадлага", manager=True)
    return template


@pytest.mark.django_db
def test_hire_without_active_template_gives_none(hired: Employee, actor: User) -> None:
    ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).update(active=False)
    assert onboarding.start_for_hire(hired, start_date=START, employee_type="full_time", by=actor) is None
    assert not Checklist.objects.filter(employee=hired, kind=ChecklistKind.ONBOARDING).exists()


@pytest.mark.django_db
def test_creates_open_checklist_anchored_on_start_with_due_dates(hired: Employee, actor: User) -> None:
    checklist = onboarding.start_for_hire(hired, start_date=START, employee_type="full_time", by=actor)
    assert checklist is not None
    assert checklist.state == ChecklistState.OPEN and checklist.kind == ChecklistKind.ONBOARDING
    assert checklist.anchor_day == START and checklist.template == _default()
    offsets = [t.due_offset_days for t in _default().tasks.order_by("position", "pk")]
    assert [t.due_on for t in checklist.tasks.order_by("position", "pk")] == [
        START + timedelta(days=o) for o in offsets
    ]


@pytest.mark.django_db
def test_type_specific_template_beats_default_other_types_get_default(hired: Employee, actor: User) -> None:
    intern = _intern_template()
    other = onboarding.start_for_hire(hired, start_date=START, employee_type="full_time", by=actor)
    assert other is not None and other.template == _default()
    Checklist.objects.filter(pk=other.pk).update(state=ChecklistState.CANCELLED)
    chosen = onboarding.start_for_hire(hired, start_date=START, employee_type="intern", by=actor)
    assert chosen is not None and chosen.template == intern
    Checklist.objects.filter(pk=chosen.pk).update(state=ChecklistState.CANCELLED)
    ChecklistTemplate.objects.filter(pk=intern.pk).update(active=False)
    fallback = onboarding.start_for_hire(hired, start_date=START, employee_type="intern", by=actor)
    assert fallback is not None and fallback.template == _default()


@pytest.mark.django_db
def test_second_start_reuses_open_checklist(hired: Employee, actor: User) -> None:
    first = onboarding.start_for_hire(hired, start_date=START, employee_type=None, by=actor)
    again = onboarding.start_for_hire(hired, start_date=START, employee_type=None, by=actor)
    assert first is not None and again is not None and first.pk == again.pk
    assert Checklist.objects.filter(employee=hired, kind=ChecklistKind.ONBOARDING).count() == 1


@pytest.mark.django_db
def test_after_completed_onboarding_a_new_one_starts(hired: Employee, actor: User) -> None:
    first = onboarding.start_for_hire(hired, start_date=START, employee_type=None, by=actor)
    assert first is not None
    Checklist.objects.filter(pk=first.pk).update(state=ChecklistState.COMPLETED)
    second = onboarding.start_for_hire(hired, start_date=START + timedelta(days=90), employee_type=None, by=actor)
    assert second is not None and second.pk != first.pk and second.state == ChecklistState.OPEN


@pytest.mark.django_db
def test_never_raises(hired: Employee, actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("template table gone")

    monkeypatch.setattr(lifecycle, "start", boom)
    assert onboarding.start_for_hire(hired, start_date=START, employee_type=None, by=actor) is None

"""Owner resolution for checklist tasks and the «my tasks» list (checklists.services.owners)."""

from datetime import date, timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import EmployeeExt, JobRecord
from employees.services import macs_writes
from leave.tests.conftest import make_employee
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask
from checklists.services.owners import (
    RULE_ADMIN,
    RULE_MANAGER,
    RULE_ROLE,
    can_tick,
    may_have_tasks,
    my_tasks,
    owners_many,
)

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 2)
LAST_DAY = date(2026, 11, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _user(name: str, *, groups: tuple[Group, ...] = ()) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(*groups)
    return user


def _group(name: str) -> Group:
    return Group.objects.get_or_create(name=name)[0]


def _admin_group() -> Group:
    return Group.objects.get_or_create(name=roles.ADMIN)[0]


def _staff(n: int) -> Employee:
    creator = User.objects.get_or_create(username="owners_test_hr")[0]
    return make_employee(creator, hired=date(2024, 3, 1), register_no=f"УБ991{n:05d}")


def _link(employee: Employee, user: User) -> None:
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})


def _set_manager(employee: Employee, manager: Employee | None) -> None:
    JobRecord.objects.filter(employee=employee).update(manager=manager)


def _checklist(employee: Employee, *, state: str = ChecklistState.OPEN) -> Checklist:
    return Checklist.objects.create(
        employee=employee,
        kind=ChecklistKind.OFFBOARDING,
        template_name="Загвар",
        anchor_day=LAST_DAY,
        state=state,
    )


def _task(
    checklist: Checklist,
    title: str,
    *,
    group: Group | None = None,
    manager: bool = False,
    due: date = LAST_DAY,
    done: bool = False,
) -> ChecklistTask:
    return ChecklistTask.objects.create(
        checklist=checklist,
        title=title,
        group=group,
        manager=manager,
        due_on=due,
        required=True,
        done_at=checklist.created_at if done else None,
    )


@pytest.fixture
def leaver(hired: Employee) -> Employee:
    return hired


def test_role_member_in_scope_owns_task(leaver: Employee) -> None:
    group = _group("Нягтлан бодогч")
    member = _user("role_member", groups=(group,))
    task = _task(_checklist(leaver), "Тооцоо", group=group)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ROLE
    assert result.user_ids == frozenset({member.pk})
    assert can_tick(member, task, DAY)


def test_role_member_outside_scope_falls_to_admin(leaver: Employee) -> None:
    dept_b = macs_writes.save_department("Бусад")
    group = _group("Хяналт")
    limited = _user("limited_member", groups=(group,))
    AccessScope.objects.create(user=limited, limited=True, department_ids=[dept_b.pk])
    admin = _user("admin_user", groups=(_admin_group(),))
    task = _task(_checklist(leaver), "Нэвтрэх эрх", group=group)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ADMIN
    assert result.user_ids == frozenset({admin.pk})
    assert not can_tick(limited, task, DAY)
    assert can_tick(admin, task, DAY)


def test_task_whose_group_was_deleted_falls_to_admin(leaver: Employee) -> None:
    admin = _user("admin_after_delete", groups=(_admin_group(),))
    task = _task(_checklist(leaver), "Устгагдсан бүлэг", group=None, manager=False)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ADMIN
    assert result.user_ids == frozenset({admin.pk})


def test_manager_task_resolves_to_manager_login(leaver: Employee) -> None:
    manager_emp = _staff(2)
    manager = _user("line_manager")
    _link(manager_emp, manager)
    _set_manager(leaver, manager_emp)
    task = _task(_checklist(leaver), "Ажил хүлээлгэх", manager=True)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_MANAGER
    assert result.user_ids == frozenset({manager.pk})
    assert can_tick(manager, task, DAY)


def test_manager_without_login_falls_to_admin(leaver: Employee) -> None:
    _set_manager(leaver, _staff(3))  # manager has no login
    admin = _user("admin_no_manager", groups=(_admin_group(),))
    task = _task(_checklist(leaver), "Ажил хүлээлгэх", manager=True)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ADMIN
    assert result.user_ids == frozenset({admin.pk})


def test_leaver_login_never_ticks_own_task(leaver: Employee) -> None:
    group = _group("Өөрийн бүлэг")
    leaver_user = _user("leaver_login", groups=(group,))
    _link(leaver, leaver_user)
    other = _user("other_member_leaver", groups=(group,))
    task = _task(_checklist(leaver), "Тооцоо", group=group)
    assert owners_many([task], DAY)[task.pk].user_ids == frozenset({other.pk})
    assert not can_tick(leaver_user, task, DAY)


def test_leaver_admin_login_is_not_admin_owner(leaver: Employee) -> None:
    admin_leaver = _user("admin_leaver", groups=(_admin_group(),))
    _link(leaver, admin_leaver)
    other_admin = _user("other_admin", groups=(_admin_group(),))
    task = _task(_checklist(leaver), "Нэвтрэх эрх хаах", group=None, manager=False)
    assert owners_many([task], DAY)[task.pk].user_ids == frozenset({other_admin.pk})
    assert not can_tick(admin_leaver, task, DAY)


def test_done_task_cannot_be_ticked(leaver: Employee) -> None:
    group = _group("Биелсэн бүлэг")
    member = _user("done_member", groups=(group,))
    task = _task(_checklist(leaver), "Биелсэн", group=group, done=True)
    assert not can_tick(member, task, DAY)


def test_completed_checklist_task_cannot_be_ticked(leaver: Employee) -> None:
    group = _group("Дууссан жагсаалт")
    member = _user("completed_member", groups=(group,))
    task = _task(_checklist(leaver, state=ChecklistState.COMPLETED), "Дууссан", group=group)
    assert not can_tick(member, task, DAY)


def test_my_tasks_lists_owned_open_tasks_by_due_date(leaver: Employee) -> None:
    group = _group("Миний бүлэг")
    mine = _user("my_tasks_member", groups=(group,))
    checklist = _checklist(leaver)
    later = _task(checklist, "Хожим", group=group, due=LAST_DAY + timedelta(days=5))
    sooner = _task(checklist, "Эрт", group=group, due=LAST_DAY - timedelta(days=3))
    _task(checklist, "Өөрийнх биш", group=_group("Бусад бүлэг"))
    assert [t.pk for t in my_tasks(mine, DAY)] == [sooner.pk, later.pk]


def test_my_tasks_skip_done_and_completed(leaver: Employee) -> None:
    group = _group("Шүүлтүүр")
    member = _user("filter_member", groups=(group,))
    _task(_checklist(leaver), "Биелсэн", group=group, done=True)
    other = _staff(4)
    _task(_checklist(other, state=ChecklistState.COMPLETED), "Дууссан", group=group)
    assert my_tasks(member, DAY) == []


def test_my_tasks_manager_and_admin_see_their_tasks(leaver: Employee) -> None:
    manager_emp = _staff(5)
    manager = _user("my_manager")
    _link(manager_emp, manager)
    _set_manager(leaver, manager_emp)
    checklist = _checklist(leaver)
    manager_task = _task(checklist, "Удирдлагын", manager=True)
    admin = _user("my_admin", groups=(_admin_group(),))
    admin_task = _task(checklist, "Админы", group=None, manager=False)
    assert [t.pk for t in my_tasks(manager, DAY)] == [manager_task.pk]
    assert [t.pk for t in my_tasks(admin, DAY)] == [admin_task.pk]


def test_my_tasks_query_count_one_versus_thirty_checklists(leaver: Employee) -> None:
    group = _group("Тоолуур")
    member = _user("counted_member", groups=(group,))
    _task(_checklist(leaver), "Нэг", group=group)

    with CaptureQueriesContext(connection) as one:
        assert len(my_tasks(member, DAY)) == 1
    for n in range(6, 35):
        _task(_checklist(_staff(n)), f"Даалгавар {n}", group=group)
    with CaptureQueriesContext(connection) as thirty:
        assert len(my_tasks(member, DAY)) == 30
    assert len(one) == len(thirty)


def test_owners_many_query_count_one_versus_thirty_tasks(leaver: Employee) -> None:
    group = _group("Бүлэг тоолох")
    _user("count_owner", groups=(group,))
    first = _task(_checklist(leaver), "Нэг", group=group)
    with CaptureQueriesContext(connection) as one:
        owners_many([first], DAY)
    tasks = [first]
    for n in range(6, 35):
        tasks.append(_task(_checklist(_staff(n)), f"Даалгавар {n}", group=group))
    with CaptureQueriesContext(connection) as thirty:
        assert len(owners_many(tasks, DAY)) == 30
    assert len(one) == len(thirty)


def test_may_have_tasks_false_without_any_role(leaver: Employee) -> None:
    _task(_checklist(leaver), "Чужой", group=_group("Өөр бүлэг"))
    assert not may_have_tasks(_user("no_role_user"), DAY)


def test_may_have_tasks_true_for_member_manager_and_admin(leaver: Employee) -> None:
    group = _group("Гишүүн")
    _task(_checklist(leaver), "Гишүүний", group=group)
    assert may_have_tasks(_user("group_member_flag", groups=(group,)), DAY)
    assert may_have_tasks(_user("admin_flag", groups=(_admin_group(),)), DAY)

    manager_emp = _staff(7)
    manager = _user("manager_flag")
    _link(manager_emp, manager)
    report = _staff(8)
    _set_manager(report, manager_emp)
    _task(_checklist(report), "Удирдлагын", manager=True)
    assert may_have_tasks(manager, DAY)


def test_admin_who_does_not_own_a_role_task_can_tick_it(leaver: Employee) -> None:
    group = _group("Админ бус бүлэг")
    member = _user("owner_member_for_admin", groups=(group,))
    admin = _user("admin_not_owner", groups=(_admin_group(),))
    task = _task(_checklist(leaver), "Бүлгийн даалгавар", group=group)
    assert admin.pk not in owners_many([task], DAY)[task.pk].user_ids
    assert member.pk in owners_many([task], DAY)[task.pk].user_ids
    assert can_tick(admin, task, DAY)


def test_hr_who_does_not_own_a_role_task_cannot_tick_it(leaver: Employee) -> None:
    group = _group("HR-гүй бүлэг")
    _user("owner_member_for_hr", groups=(group,))
    hr = _user("hr_not_owner", groups=(_group(roles.HR),))
    task = _task(_checklist(leaver), "HR-ийн бус даалгавар", group=group)
    assert not can_tick(hr, task, DAY)


def test_admin_leaver_cannot_tick_own_role_task(leaver: Employee) -> None:
    group = _group("Админ гарагч бүлэг")
    _user("member_for_admin_leaver", groups=(group,))
    admin_leaver = _user("admin_leaver_role", groups=(_admin_group(),))
    _link(leaver, admin_leaver)
    task = _task(_checklist(leaver), "Өөрийн даалгавар", group=group)
    assert not can_tick(admin_leaver, task, DAY)


def test_admin_cannot_tick_done_task_finished_checklist_or_inactive_login(leaver: Employee) -> None:
    group = _group("Админ хаагдсан")
    admin = _user("admin_closed", groups=(_admin_group(),))
    done = _task(_checklist(leaver), "Биелсэн admin", group=group, done=True)
    assert not can_tick(admin, done, DAY)
    completed = _task(_checklist(_staff(9), state=ChecklistState.COMPLETED), "Дууссан admin", group=group)
    assert not can_tick(admin, completed, DAY)
    open_task = _task(_checklist(_staff(10)), "Нээлттэй admin", group=group)
    assert can_tick(admin, open_task, DAY)
    admin.is_active = False
    admin.save()
    assert not can_tick(admin, open_task, DAY)


def test_my_tasks_does_not_list_a_role_task_of_a_non_owner_admin(leaver: Employee) -> None:
    group = _group("Админд жагсаахгүй")
    _user("owner_for_list", groups=(group,))
    admin = _user("admin_list_non_owner", groups=(_admin_group(),))
    _task(_checklist(leaver), "Бүлгийн жагсаалт", group=group)
    assert my_tasks(admin, DAY) == []


def _future_hire() -> Employee:
    creator = User.objects.get_or_create(username="owners_test_hr")[0]
    return make_employee(creator, hired=date(2026, 12, 1), register_no="УБ99200001")  # job row starts after DAY


def _onboarding_checklist(employee: Employee) -> Checklist:
    return Checklist.objects.create(
        employee=employee,
        kind=ChecklistKind.ONBOARDING,
        template_name="Загвар",
        anchor_day=date(2026, 12, 1),
    )


def test_future_start_onboarding_manager_task_is_owned_by_manager_today() -> None:
    newcomer = _future_hire()
    manager_emp = _staff(6)
    manager = _user("future_manager")
    _link(manager_emp, manager)
    _set_manager(newcomer, manager_emp)
    admin = _user("future_admin", groups=(_admin_group(),))
    task = _task(_onboarding_checklist(newcomer), "Угтан авах", manager=True)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_MANAGER and result.user_ids == frozenset({manager.pk})
    assert can_tick(manager, task, DAY)
    assert [t.pk for t in my_tasks(manager, DAY)] == [task.pk]
    assert may_have_tasks(manager, DAY)
    assert can_tick(admin, task, DAY)  # Admin may tick any open task


def test_future_start_onboarding_without_manager_falls_to_admin() -> None:
    newcomer = _future_hire()
    admin = _user("future_admin2", groups=(_admin_group(),))
    task = _task(_onboarding_checklist(newcomer), "Угтан авах", manager=True)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ADMIN and result.user_ids == frozenset({admin.pk})


def test_future_start_offboarding_is_still_resolved_on_the_day() -> None:
    newcomer = _future_hire()  # no job row in force on DAY: an offboarding task cannot find the manager
    manager_emp = _staff(7)
    manager = _user("offboard_manager")
    _link(manager_emp, manager)
    _set_manager(newcomer, manager_emp)
    admin = _user("offboard_admin", groups=(_admin_group(),))
    checklist = Checklist.objects.create(
        employee=newcomer, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=date(2026, 12, 1)
    )
    task = _task(checklist, "Ажил хүлээлгэх", manager=True)
    result = owners_many([task], DAY)[task.pk]
    assert result.rule == RULE_ADMIN and result.user_ids == frozenset({admin.pk})


def test_owners_many_mixed_days_use_each_checklists_own_day(leaver: Employee) -> None:
    newcomer = _future_hire()
    manager_emp = _staff(8)
    manager = _user("mixed_manager")
    _link(manager_emp, manager)
    _set_manager(newcomer, manager_emp)
    _set_manager(leaver, manager_emp)
    onboarding_task = _task(_onboarding_checklist(newcomer), "Угтан авах", manager=True)
    offboarding_task = _task(_checklist(leaver), "Ажил хүлээлгэх", manager=True)
    result = owners_many([onboarding_task, offboarding_task], DAY)
    assert result[onboarding_task.pk].user_ids == frozenset({manager.pk})
    assert result[offboarding_task.pk].user_ids == frozenset({manager.pk})

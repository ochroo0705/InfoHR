from datetime import date
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from macs.models import Branch, Department, FiredReason

from employees import access, history_range
from employees.forms import JobCorrectionForm
from employees.models import Employee, Event, JobRecord, JobStatus
from employees.scope import LOOP_MESSAGE, SELF_MANAGER_MESSAGE, creates_loop, department_ids, restriction, team_ids
from employees.services import events, history, macs_writes
from employees.services.events import EventError
from employees.services.history import HistoryError

from .conftest import hire_values, link_login, named
from .helpers import record_signed

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


def _person(actor: User, job_values: dict[str, Any], register_no: str, manager: Employee | None = None) -> Employee:
    job = {**job_values, "manager": manager}
    return history.hire(hire_values(register_no), {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)


def _set_manager(employee: Employee, manager: Employee | None) -> None:
    JobRecord.objects.filter(employee=employee).update(manager=manager)


def test_team_direct_and_indirect(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    assert team_ids(a.pk, DAY) == {b.pk, c.pk}
    assert team_ids(b.pk, DAY) == {c.pk}
    assert team_ids(c.pk, DAY) == set()


def test_team_excludes_ended_jobs(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    JobRecord.objects.filter(employee=b).update(**history_range.span_kwargs(date(2026, 1, 5), date(2026, 2, 1)))
    assert team_ids(a.pk, DAY) == set()
    assert team_ids(a.pk, date(2026, 1, 20)) == {b.pk}


def test_team_includes_employee_who_left(actor: User, job_values: dict[str, Any]) -> None:
    """Ruling 2026-10-29: a left employee stays in the manager's team (last job row still in force)."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    record_signed(
        b,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    after = date(2026, 4, 1)
    assert JobRecord.objects.get(history_range.on(after), employee=b).status == JobStatus.LEFT
    assert b.pk in team_ids(a.pk, after)


def test_team_terminates_on_loop(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    _set_manager(a, b)
    result = team_ids(a.pk, DAY)
    assert result == {b.pk}
    assert a.pk not in result


def test_five_level_chain(actor: User, job_values: dict[str, Any]) -> None:
    chain: list[Employee] = []
    manager: Employee | None = None
    for n in range(5):
        manager = _person(actor, job_values, f"УБ0000010{n}", manager=manager)
        chain.append(manager)
    top = chain[0]
    assert team_ids(top.pk, DAY) == {e.pk for e in chain[1:]}
    assert team_ids(chain[2].pk, DAY) == {chain[3].pk, chain[4].pk}


def test_department_subtree(actor: User, job_values: dict[str, Any]) -> None:
    root = macs_writes.save_department("Удирдлага")
    child = macs_writes.save_department("Хэлтэс А")
    grand = macs_writes.save_department("Хэлтэс Б")
    other = macs_writes.save_department("Бусад")
    Department.objects.filter(pk=child.pk).update(parent_id_value=root.pk)
    Department.objects.filter(pk=grand.pk).update(parent_id_value=child.pk)
    assert department_ids([root.pk], include_sub=True) == {root.pk, child.pk, grand.pk}
    assert department_ids([root.pk], include_sub=False) == {root.pk}
    assert other.pk not in department_ids([root.pk], include_sub=True)


def test_creates_loop_cases(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    peer = _person(actor, job_values, "УБ00000004", manager=a)
    assert creates_loop(a.pk, a.pk, DAY) is True  # self
    assert creates_loop(a.pk, b.pk, DAY) is True  # direct report of a would become a's manager
    assert creates_loop(a.pk, c.pk, DAY) is True  # grand-report
    assert creates_loop(b.pk, peer.pk, DAY) is False  # peer: sibling under a, not below b
    assert creates_loop(a.pk, None, DAY) is False


# --- Task 3: restriction (who a limited user may see) and visible_employees ---


def _user_in(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def _limit(user: User, **fields: Any) -> None:
    AccessScope.objects.update_or_create(user=user, defaults={"limited": True, **fields})


def _place(employee: Employee, *, branch: Branch | None = None, department: Any = None) -> None:
    values: dict[str, Any] = {}
    if branch is not None:
        values["branch_id"] = branch.pk
    if department is not None:
        values["department_id"] = department.pk
    Employee.objects.filter(pk=employee.pk).update(**values)


def _seen(user: User) -> set[int]:
    return set(access.visible_employees(user).values_list("pk", flat=True))


def test_unlimited_by_default(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002")
    hr = _user_in("HR", "hr_default")
    assert restriction(hr) is None
    assert _seen(hr) == {a.pk, b.pk}


def test_branch_scope(actor: User, job_values: dict[str, Any]) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002")
    _place(a, branch=north)
    _place(b, branch=south)
    hr = _user_in("HR", "hr_branch")
    _limit(hr, branch_ids=[north.pk])
    assert _seen(User.objects.get(pk=hr.pk)) == {a.pk}


def test_department_scope_with_and_without_subs(actor: User, job_values: dict[str, Any]) -> None:
    root = macs_writes.save_department("Удирдлага")
    child = macs_writes.save_department("Хэлтэс А")
    Department.objects.filter(pk=child.pk).update(parent_id_value=root.pk)
    in_root = _person(actor, {**job_values, "department": root}, "УБ00000001")
    in_child = _person(actor, {**job_values, "department": child}, "УБ00000002")
    _place(in_root, department=root)
    _place(in_child, department=child)
    hr = _user_in("HR", "hr_dep")
    _limit(hr, department_ids=[root.pk], include_sub_departments=True)
    assert _seen(User.objects.get(pk=hr.pk)) == {in_root.pk, in_child.pk}
    _limit(hr, department_ids=[root.pk], include_sub_departments=False)
    assert _seen(User.objects.get(pk=hr.pk)) == {in_root.pk}


def test_team_scope(actor: User, job_values: dict[str, Any]) -> None:
    lead = _person(actor, job_values, "УБ00000001")
    report = _person(actor, job_values, "УБ00000002", manager=lead)
    deeper = _person(actor, job_values, "УБ00000003", manager=report)
    outsider = _person(actor, job_values, "УБ00000004")
    manager_user = _user_in("HR", "lead_user")
    link_login(lead, manager_user)
    _limit(manager_user, own_team=True)
    seen = _seen(User.objects.get(pk=manager_user.pk))
    assert {report.pk, deeper.pk, lead.pk} <= seen
    assert outsider.pk not in seen


def test_union_of_all_three(actor: User, job_values: dict[str, Any]) -> None:
    branch = Branch.objects.create(name="Төв")
    dep = macs_writes.save_department("Худалдаа")
    me = _person(actor, job_values, "УБ00000001")
    report = _person(actor, job_values, "УБ00000002", manager=me)
    in_branch = _person(actor, job_values, "УБ00000003")
    in_dep = _person(actor, job_values, "УБ00000004")
    nothing = _person(actor, job_values, "УБ00000005")
    _place(in_branch, branch=branch)
    _place(in_dep, department=dep)
    hr = _user_in("HR", "hr_union")
    link_login(me, hr)
    _limit(hr, branch_ids=[branch.pk], department_ids=[dep.pk], own_team=True)
    seen = _seen(User.objects.get(pk=hr.pk))
    assert seen == {me.pk, report.pk, in_branch.pk, in_dep.pk}
    assert nothing.pk not in seen


def test_own_record_always_visible(actor: User, job_values: dict[str, Any]) -> None:
    me = _person(actor, job_values, "УБ00000001")
    hr = _user_in("HR", "hr_self")
    link_login(me, hr)
    _limit(hr, branch_ids=[Branch.objects.create(name="Элсэн").pk])
    assert me.pk in _seen(User.objects.get(pk=hr.pk))


def test_limited_with_nothing_ticked_sees_only_self(actor: User, job_values: dict[str, Any]) -> None:
    me = _person(actor, job_values, "УБ00000001")
    _person(actor, job_values, "УБ00000002")
    hr = _user_in("HR", "hr_none")
    link_login(me, hr)
    _limit(hr)
    assert _seen(User.objects.get(pk=hr.pk)) == {me.pk}


def test_empty_or_stale_ids_see_only_self(actor: User, job_values: dict[str, Any]) -> None:
    me = _person(actor, job_values, "УБ00000001")
    other = _person(actor, job_values, "УБ00000002")
    hr = _user_in("HR", "hr_stale")
    link_login(me, hr)
    _limit(hr, department_ids=[987654], branch_ids=[987654])
    seen = _seen(User.objects.get(pk=hr.pk))
    assert seen == {me.pk}
    assert other.pk not in seen


def test_login_without_employee_sees_nobody_and_does_not_crash(actor: User, job_values: dict[str, Any]) -> None:
    _person(actor, job_values, "УБ00000001")
    hr = _user_in("HR", "hr_nobody")
    _limit(hr, own_team=True)
    assert _seen(User.objects.get(pk=hr.pk)) == set()


def test_admin_group_and_superuser_not_limited_even_with_row(actor: User, job_values: dict[str, Any]) -> None:
    branch_x = Branch.objects.create(name="Хойд")
    branch_y = Branch.objects.create(name="Өмнөд")
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002")
    _place(a, branch=branch_x)
    _place(b, branch=branch_y)
    total = Employee.objects.count()
    assert total >= 2
    admin = _user_in("Admin", "admin_row")
    _limit(admin, branch_ids=[branch_x.pk])  # a row that would hide b if it applied
    admin = User.objects.get(pk=admin.pk)
    assert restriction(admin) is None
    assert len(_seen(admin)) == total
    assert b.pk in _seen(admin)
    su = User.objects.create_superuser("su_row", "su_row@example.com", "x-long-pass-123")  # noqa: S106
    _limit(su, branch_ids=[branch_x.pk])
    su = User.objects.get(pk=su.pk)
    assert restriction(su) is None
    assert len(_seen(su)) == total
    assert b.pk in _seen(su)


def test_inactive_user_sees_none(actor: User, job_values: dict[str, Any]) -> None:
    _person(actor, job_values, "УБ00000001")
    hr = _user_in("HR", "hr_off")
    _limit(hr)
    User.objects.filter(pk=hr.pk).update(is_active=False)
    assert _seen(User.objects.get(pk=hr.pk)) == set()


def test_scope_follows_current_row(actor: User, job_values: dict[str, Any]) -> None:
    dep_a = macs_writes.save_department("Ая")
    dep_b = macs_writes.save_department("Бэ")
    person = _person(actor, {**job_values, "department": dep_a}, "УБ00000001")
    _place(person, department=dep_a)
    hr = _user_in("HR", "hr_row")
    _limit(hr, department_ids=[dep_a.pk])
    user = User.objects.get(pk=hr.pk)
    assert person.pk in _seen(user)
    _place(person, department=dep_b)
    assert person.pk not in _seen(user)  # same object: the department filter reads the row at query time
    assert person.pk not in _seen(User.objects.get(pk=hr.pk))  # a fresh restriction reflects the move
    _place(person, department=dep_a)
    assert person.pk in _seen(User.objects.get(pk=hr.pk))


def test_hr_role_with_scope_keeps_perms(actor: User, job_values: dict[str, Any]) -> None:
    """Scope decides WHOM a user sees; the role's rights decide WHAT the user may do."""
    branch_x = Branch.objects.create(name="Баруун")
    branch_y = Branch.objects.create(name="Зүүн")
    inside = _person(actor, job_values, "УБ00000001")
    outside = _person(actor, job_values, "УБ00000002")
    _place(inside, branch=branch_x)
    _place(outside, branch=branch_y)

    hr = _user_in("HR", "hr_perms")
    _limit(hr, branch_ids=[branch_x.pk])
    hr = User.objects.get(pk=hr.pk)
    assert outside.pk not in _seen(hr)  # scope hides the person in branch Y
    assert inside.pk in _seen(hr)
    assert access.can_view_personal(hr, inside)  # rights unchanged by the scope
    assert access.can_manage(hr)
    assert not access.can_view_salary(hr)

    acc = _user_in("Accountant", "acc_perms")
    _limit(acc, branch_ids=[branch_x.pk])
    acc = User.objects.get(pk=acc.pk)
    assert access.can_view_salary(acc)  # the salary right comes from the role, not from the scope
    assert outside.pk not in _seen(acc)


# --- Task 6: manager loop validation ---


def _transfer_manager(employee: Employee, actor: User, manager: Employee | None) -> None:
    events.record(
        employee,
        type="transfer",
        effective=DAY,
        changes={"manager": manager},
        salary=None,
        reason="",
        note="",
        by=actor,
    )


def test_transfer_rejects_self_manager(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    jobs, events_before = JobRecord.objects.count(), Event.objects.count()
    with pytest.raises(EventError) as exc:
        _transfer_manager(a, actor, a)
    assert exc.value.errors == {"manager": SELF_MANAGER_MESSAGE}
    assert JobRecord.objects.count() == jobs and Event.objects.count() == events_before
    assert JobRecord.objects.get(employee=a).manager is None


def test_transfer_rejects_loop(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    jobs, events_before = JobRecord.objects.count(), Event.objects.count()
    with pytest.raises(EventError) as exc:
        _transfer_manager(a, actor, b)  # A manages B; moving A under B closes the loop
    assert exc.value.errors == {"manager": LOOP_MESSAGE}
    assert JobRecord.objects.count() == jobs and Event.objects.count() == events_before
    assert JobRecord.objects.get(employee=a).manager is None


def test_correction_service_rejects_loop(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    record = JobRecord.objects.get(employee=a)
    with pytest.raises(HistoryError) as exc:
        history.correct_job(record, changes={"manager": b}, reason="засвар", by=actor)
    assert str(exc.value) == LOOP_MESSAGE
    assert JobRecord.objects.get(employee=a).manager is None


def test_correction_form_rejects_loop(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    record = JobRecord.objects.get(employee=a)
    form = JobCorrectionForm(
        {
            "position": record.position_id,
            "department": record.department_id,
            "manager": b.pk,
            "reason": "засвар",
        },
        instance=record,
    )
    assert form.is_valid() is False
    assert list(form.errors.get("manager", [])) == [LOOP_MESSAGE]


def test_valid_manager_still_works(actor: User, job_values: dict[str, Any]) -> None:
    lead = _person(actor, job_values, "УБ00000001")
    _person(actor, job_values, "УБ00000002", manager=lead)  # an existing report of lead
    other = _person(actor, job_values, "УБ00000003")
    record_signed(
        other,
        type="transfer",
        effective=DAY,
        changes={"manager": lead},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert history.job_on(other, DAY) is not None
    assert history.job_on(other, DAY).manager == lead  # type: ignore[union-attr]


def test_correction_with_existing_loop_and_unchanged_manager_succeeds(actor: User, job_values: dict[str, Any]) -> None:
    """The loop check runs only when the manager changes: correcting A's position in an A<->B loop is allowed."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    JobRecord.objects.filter(employee=a).update(manager=b)  # the loop already exists in the data
    record = JobRecord.objects.get(employee=a)
    senior = macs_writes.save_position("Ахлах нягтлан")
    form = JobCorrectionForm(
        {"position": senior.pk, "department": record.department_id, "manager": b.pk, "reason": "засвар"},
        instance=record,
    )
    form.is_valid()
    assert "manager" not in form.errors
    corrected = history.correct_job(record, changes={"position": senior, "manager": b}, reason="засвар", by=actor)
    assert corrected.position_id == senior.pk
    assert JobRecord.objects.get(employee=a).manager_id == b.pk


def test_former_report_still_refused_as_manager_of_old_manager(actor: User, job_values: dict[str, Any]) -> None:
    """Ruling 2026-10-29: a leaver stays in the team, so making them manager of their old manager is still a loop."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    record_signed(
        b,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    day_after = date(2026, 3, 2)
    assert creates_loop(a.pk, b.pk, day_after) is True
    jobs, events_before = JobRecord.objects.count(), Event.objects.count()
    with pytest.raises(EventError) as exc:
        events.record(
            a,
            type="transfer",
            effective=day_after,
            changes={"manager": b},
            salary=None,
            reason="",
            note="",
            by=actor,
        )
    assert exc.value.errors == {"manager": LOOP_MESSAGE}
    assert JobRecord.objects.count() == jobs and Event.objects.count() == events_before
    assert JobRecord.objects.get(employee=a).manager is None

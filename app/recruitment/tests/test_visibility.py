from accounts.models import User

from recruitment.services import visibility

from .conftest import make_manager, make_vacancy


def test_hr_sees_all_manager_sees_only_own(actor: User, hr_user: User) -> None:
    user_a, emp_a = make_manager(actor, "mgr_a", "УБ10000001")
    user_b, emp_b = make_manager(actor, "mgr_b", "УБ10000002")
    va = make_vacancy("A", manager=emp_a)
    vb = make_vacancy("B", manager=emp_b)
    from recruitment.services import pipeline

    ca = pipeline.add_candidate(va, by=actor, surname="a", given_name="a")
    cb = pipeline.add_candidate(vb, by=actor, surname="b", given_name="b")

    assert set(visibility.visible_vacancies(hr_user)) == {va, vb}
    assert set(visibility.visible_candidates(hr_user)) == {ca, cb}
    assert set(visibility.visible_vacancies(user_a)) == {va}
    assert set(visibility.visible_candidates(user_a)) == {ca}
    assert set(visibility.visible_candidates(user_b)) == {cb}
    assert visibility.can_manage(hr_user)
    assert not visibility.can_manage(user_a)


def test_stranger_without_employee_sees_nothing(actor: User) -> None:
    make_vacancy("A")
    stranger = User.objects.create_user("stranger", password="x-long-pass-123")  # noqa: S106
    assert not visibility.visible_vacancies(stranger).exists()
    assert not visibility.visible_candidates(stranger).exists()
    assert not visibility.can_manage(stranger)


def test_superuser_sees_all(actor: User) -> None:
    make_vacancy("A")
    boss = User.objects.create_superuser("boss", password="x-long-pass-123")  # noqa: S106
    assert visibility.visible_vacancies(boss).count() == 1
    assert visibility.can_manage(boss)


def test_inactive_user_sees_nothing(actor: User, hr_user: User) -> None:
    user_a, emp_a = make_manager(actor, "mgr_a", "УБ10000001")
    make_vacancy("A", manager=emp_a)
    for user in (hr_user, user_a):
        user.is_active = False
        user.save()
        fresh = User.objects.get(pk=user.pk)
        assert not visibility.visible_vacancies(fresh).exists()
        assert not visibility.can_manage(fresh)


def test_sees_recruitment_is_one_query(actor: User) -> None:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    user_a, emp_a = make_manager(actor, "mgr_q", "УБ10000011")
    make_vacancy("A", manager=emp_a)
    fresh = User.objects.get(pk=user_a.pk)
    fresh.has_perm(visibility.PERMISSION)  # warm the permission cache
    with CaptureQueriesContext(connection) as ctx:
        assert visibility.sees_recruitment(fresh)
    assert len(ctx) == 1


def test_hiring_manager_who_has_left_loses_access(actor: User) -> None:
    from employees.models import JobRecord, JobStatus

    user_a, emp_a = make_manager(actor, "mgr_left", "УБ10000012")
    make_vacancy("A", manager=emp_a)
    assert visibility.sees_recruitment(User.objects.get(pk=user_a.pk))
    job = JobRecord.objects.filter(employee=emp_a).first()
    assert job is not None
    job.status = JobStatus.LEFT
    job.save()
    fresh = User.objects.get(pk=user_a.pk)
    assert not visibility.sees_recruitment(fresh)
    assert not visibility.visible_vacancies(fresh).exists()

"""Who sees which vacancy and candidate. Views must look every vacancy/candidate up through these."""

from accounts.models import User
from django.db.models import QuerySet
from django.utils import timezone
from employees.listing import still_working
from macs.models import Employee

from recruitment.models import Candidate, Vacancy

PERMISSION = "recruitment.manage_recruitment"


def can_manage(user: User) -> bool:
    return bool(user.is_active and (user.is_superuser or user.has_perm(PERMISSION)))


def visible_vacancies(user: User) -> QuerySet[Vacancy]:
    """All vacancies for managers of recruitment; otherwise the ones whose hiring manager is the user's own employee."""
    if not user.is_active:
        return Vacancy.objects.none()
    if can_manage(user):
        return Vacancy.objects.all()
    return _managed_by(user)


def _managed_by(user: User) -> QuerySet[Vacancy]:
    """Vacancies whose hiring manager is the user's own employee record, while that person still works here."""
    own = still_working(Employee.objects.filter(ext__user_id=user.pk), timezone.localdate())
    return Vacancy.objects.filter(hiring_manager__in=own)


def visible_candidates(user: User) -> QuerySet[Candidate]:
    return Candidate.objects.filter(vacancy__in=visible_vacancies(user))


def sees_recruitment(user: User) -> bool:
    """The menu and palette rule: the user manages recruitment or is the hiring manager of some vacancy.

    Costs one query for a user who does not manage, so callers keep the answer for the request (nav) or user (palette).
    """
    return can_manage(user) or (user.is_active and _managed_by(user).exists())

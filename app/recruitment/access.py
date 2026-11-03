"""Who may open what in recruitment. Every view looks objects up here, so each one goes through `visibility`.

An object the user may not see answers 404 (it never says the object exists). A visible object whose action needs the
right to manage recruitment answers 403 for a hiring manager, like the leave screens.
"""

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from recruitment.models import Candidate, CandidateFile, Vacancy
from recruitment.services import visibility


def user_of(request: HttpRequest) -> User:
    assert isinstance(request.user, User)  # noqa: S101
    return request.user


def require_manage(user: User) -> None:
    if not visibility.can_manage(user):
        raise PermissionDenied


def vacancy_or_404(user: User, pk: int) -> Vacancy:
    return get_object_or_404(
        visibility.visible_vacancies(user).select_related("position", "department", "branch"), pk=pk
    )


def candidate_or_404(user: User, pk: int) -> Candidate:
    return get_object_or_404(visibility.visible_candidates(user).select_related("vacancy"), pk=pk)


def file_or_404(user: User, pk: int) -> CandidateFile:
    return get_object_or_404(CandidateFile.objects.filter(candidate__in=visibility.visible_candidates(user)), pk=pk)

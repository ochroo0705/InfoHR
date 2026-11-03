"""Convert a candidate to an employee through the hire form: who may, and what the form is prefilled with.

The link itself (`pipeline.mark_hired`) runs after the hire has been saved; this module only decides which candidate
a posted `candidate` value may refer to and builds the prefill.
"""

from datetime import date

from accounts.models import User

from recruitment.models import Candidate, Stage, Vacancy, VacancyStatus
from recruitment.services import pipeline, visibility

NOT_CONVERTIBLE = "Энэ ажил хүсэгчийг ажилтан болгох боломжгүй."
VACANCY_NOT_OPEN = (
    "Энэ ажил хүсэгчийг ажилтан болгох боломжгүй: ажлын байр нээлттэй биш байна. Эхлээд ажлын байрыг дахин нээнэ үү."
)


def can_convert(candidate: Candidate) -> bool:
    """Open to conversion: still in the running (not rejected, withdrawn or hired), no employee linked yet, and its
    vacancy open (HR reopens a closed or filled vacancy to hire beyond its headcount)."""
    return (
        candidate.stage not in pipeline.CLOSED_STAGES
        and candidate.stage != Stage.HIRED
        and candidate.employee_id is None
        and candidate.vacancy.status == VacancyStatus.OPEN
    )


def refusal(candidate: Candidate) -> str:
    """Why `can_convert` is false, in words for the user."""
    only_vacancy = (
        candidate.stage not in pipeline.CLOSED_STAGES
        and candidate.stage != Stage.HIRED
        and candidate.employee_id is None
    )
    return VACANCY_NOT_OPEN if only_vacancy else NOT_CONVERTIBLE


def visible(user: User, raw: object) -> Candidate | None:
    """The candidate a hire-form `candidate` value names when the user may manage recruitment and see it (any state)."""
    if not visibility.can_manage(user) or not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        return None
    return visibility.visible_candidates(user).select_related("vacancy").filter(pk=int(raw)).first()


def convertible(user: User, raw: object) -> Candidate | None:
    """The candidate a hire-form `candidate` value names, or None for anything else (bad, foreign, closed, hired).

    The user must hold the right to manage recruitment and see the candidate; nothing is said about why it failed.
    """
    candidate = visible(user, raw)
    return candidate if candidate is not None and can_convert(candidate) else None


def lock_convertible(pk: int) -> Candidate | None:
    """Inside the hire transaction: lock the candidate row (and its vacancy) and answer it only while it can still
    be converted, so two posts of one hire form cannot both link it."""
    locked = Candidate.objects.select_for_update().filter(pk=pk).first()
    if locked is None:
        return None
    Vacancy.objects.select_for_update().filter(pk=locked.vacancy_id).first()
    locked = Candidate.objects.select_related("vacancy").get(pk=pk)
    return locked if can_convert(locked) else None


def prefill_params(candidate: Candidate, today: date) -> dict[str, str]:
    """Hire-form field names and values for `candidate` (the keys are the real field names of the hire forms)."""
    vacancy = candidate.vacancy
    start = vacancy.desired_start if vacancy.desired_start is not None and vacancy.desired_start > today else today
    params = {
        "family_name": candidate.surname,
        "given_name": candidate.given_name,
        "private_phone": candidate.phone,
        "email": candidate.email,
        "position": str(vacancy.position_id),
        "department": str(vacancy.department_id),
        "start": start.isoformat(),
        "candidate": str(candidate.pk),
    }
    if vacancy.branch_id is not None:
        params["branch"] = str(vacancy.branch_id)
    return {key: value for key, value in params.items() if value}

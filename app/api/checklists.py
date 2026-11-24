"""The checklist routes the React pages call besides the tick (which lives in api.me): untick, cancel, start offboarding
and «my tasks». They are added to `checklists_router` of api.me, so every checklist route sits on one router mounted at
/checklists. The rules are in checklists.services.actions and lifecycle; this module only maps their answers: a row the
user may not see or change is 404, a refused change 409, a bad input or a missing template 400."""

from accounts.models import User
from checklists.services import actions, lifecycle
from django.http import Http404, HttpRequest
from django.utils import timezone
from ninja import Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.errors import ApiError
from api.me import checklists_router

_NOT_FOUND = "Хуудас олдсонгүй"


class ChecklistStartIn(Schema):
    anchor_day: str  # the last working day, ISO (YYYY-MM-DD)


class ChecklistMineItemOut(Schema):
    id: int
    title: str
    employee: str
    kind_label: str
    due: str  # YYYY-MM-DD
    overdue: bool


class ChecklistMineOut(Schema):
    items: list[ChecklistMineItemOut]


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


# /mine is declared before the path routes; the GET is the only one on this router, so nothing takes it for a pk.
@checklists_router.get("/mine", auth=django_auth, response=ChecklistMineOut)
def checklist_mine(request: HttpRequest) -> dict[str, list[dict[str, object]]]:
    """«Миний даалгавар»: the signed-in user's own open tasks, earliest due first. Works without an employee record."""
    rows = actions.mine_rows(_user(request), timezone.localdate())
    return {
        "items": [
            {
                "id": row.task_id,
                "title": row.title,
                "employee": row.employee,
                "kind_label": row.kind_label,
                "due": row.due_on.isoformat(),
                "overdue": row.overdue,
            }
            for row in rows
        ]
    }


@checklists_router.post("/tasks/{pk}/untick", auth=django_auth, response={204: None})
def untick_task(request: HttpRequest, pk: int) -> tuple[int, None]:
    """«Буцаах»: undo the tick of a checklist task (404 without the manage right, 409 when refused)."""
    try:
        actions.untick_for(_user(request), pk, timezone.localdate())
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except lifecycle.ChecklistError as error:
        raise ApiError(409, [error.message]) from error
    return 204, None


@checklists_router.post("/{pk}/cancel", auth=django_auth, response={204: None})
def cancel_checklist(request: HttpRequest, pk: int) -> tuple[int, None]:
    """«Цуцлах»: cancel an open checklist (404 without the manage right, 409 when refused)."""
    try:
        actions.cancel_for(_user(request), pk, timezone.localdate())
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except lifecycle.ChecklistError as error:
        raise ApiError(409, [error.message]) from error
    return 204, None


@checklists_router.post("/employees/{employee_id}/start", auth=django_auth, response={204: None})
def start_offboarding(request: HttpRequest, employee_id: int, payload: ChecklistStartIn) -> tuple[int, None]:
    """«Ажлаас гарах жагсаалт эхлүүлэх» with the picked last day. 404 for a hidden employee or without the start right,
    400 for a bad date or when no template applies, 409 when refused."""
    try:
        actions.start_offboarding(_user(request), employee_id, payload.anchor_day)
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except actions.ActionError as error:
        raise ApiError(400, [error.message]) from error
    except lifecycle.ChecklistError as error:
        raise ApiError(409, [error.message]) from error
    return 204, None

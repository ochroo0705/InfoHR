"""GET /api/v1/meta: what the SPA needs before login (company, modules, CSRF token) and who is signed in."""

from accounts import modules
from accounts.models import User
from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token
from employees.models import CompanySettings
from ninja import Router, Schema

meta_router = Router(tags=["meta"])


class CompanyOut(Schema):
    name: str
    logo_url: str | None


class UserOut(Schema):
    id: int
    username: str
    full_name: str
    must_change_password: bool
    perms: list[str]


class MetaOut(Schema):
    backend_version: str
    api_version: int
    company: CompanyOut
    modules: dict[str, bool]
    csrf: str
    user: UserOut | None


def _company() -> dict[str, object]:
    # Read, never create: a site with no company row yet answers an empty name and no logo.
    row = CompanySettings.objects.filter(pk=1).first()
    if row is None:
        return {"name": "", "logo_url": None}
    return {"name": row.name, "logo_url": row.letterhead_logo.url if row.letterhead_logo else None}


def _user_out(user: User) -> dict[str, object]:
    # Rights of a module that is switched off are dropped here: get_all_permissions() does not ask modules.
    perms = sorted(p for p in user.get_all_permissions() if not modules.blocked_perm(p))
    return {
        "id": user.pk,
        "username": user.get_username(),
        "full_name": user.get_full_name(),
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "perms": perms,
    }


@meta_router.get("", auth=None, response=MetaOut)  # anonymous on purpose: the SPA reads it before login
def meta(request: HttpRequest) -> dict[str, object]:
    from api.main import API_VERSION  # local import: api.main imports this module

    user = getattr(request, "user", None)
    signed_in = user is not None and user.is_authenticated
    return {
        "backend_version": settings.HC_BACKEND_VERSION,
        "api_version": API_VERSION,
        "company": _company(),
        "modules": modules.state(),
        "csrf": get_token(request),
        "user": _user_out(user) if signed_in else None,
    }

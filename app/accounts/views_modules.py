"""The «Модулиуд» page: an admin switches the optional modules (accounts/modules.py) on or off for the organisation."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts import modules
from accounts.audit import Category, record_safe
from accounts.models import User
from accounts.roles import ADMIN


def may_manage_modules(user: User) -> bool:
    """Superusers and the Admin role (the same people who edit the company settings)."""
    return bool(user.is_active and (user.is_superuser or user.groups.filter(name=ADMIN).exists()))


@login_required
def modules_page(request: HttpRequest) -> HttpResponse:
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    if not may_manage_modules(user):
        raise PermissionDenied
    if request.method == "POST":
        before = modules.state()
        chosen = set(request.POST.getlist("on"))
        after = {m.key: m.key in chosen for m in modules.MODULES}
        modules.set_state(after)
        for key, now in after.items():
            if before[key] != now:
                label = modules.BY_KEY[key].label
                record_safe(
                    Category.ACCESS,
                    "module_switched",
                    actor=user,
                    message=f"{label}: {'асаасан' if now else 'унтраасан'}",
                    target_type="module",
                    target_label=label,
                )
        messages.success(request, "Модулийн тохиргоо хадгалагдлаа.")
        return redirect("modules")
    current = modules.state()
    rows = [{"module": m, "on": current[m.key]} for m in modules.MODULES]
    return render(request, "accounts/modules.html", {"rows": rows})

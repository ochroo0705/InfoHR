from typing import Any

from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from employees.models import EmployeeExt

from accounts import login_throttle
from accounts.audit import Category, record_safe
from accounts.forms import ChangePasswordForm, NewPasswordForm
from accounts.models import User


class ForcedPasswordChangeView(PasswordChangeView):
    """Change-password page. Also the place a temporary password is replaced (then no old password is asked)."""

    template_name = "registration/password_change.html"
    success_url = reverse_lazy("home")

    def get_form_class(self) -> Any:
        return NewPasswordForm if getattr(self.request.user, "must_change_password", False) else ChangePasswordForm

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:  # type: ignore[type-arg]
        response = super().form_valid(form)
        user = form.user
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        # No password text here: the entry only says that the user changed their own password.
        record_safe(Category.ACCESS, "password_changed", actor=user, target_type="user", target_label=user.username)
        return response


class ThrottledLoginView(LoginView):
    """The normal login page; when the IP or username is locked it says so instead of "wrong password"."""

    locked = False

    def form_invalid(self, form: Any) -> HttpResponse:
        self.locked = login_throttle.is_locked(self.request, str(form.data.get("username") or ""))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(locked=self.locked, lock_message=login_throttle.LOCK_MESSAGE)
        return context


def home(request: HttpRequest) -> HttpResponseRedirect:
    """Landing page. An Auditor (system log right, no employee right) goes to the system log. A user without the
    employee-list right who has an employee record of their own goes to My page; everyone else goes to Today."""
    user = request.user
    assert isinstance(user, User)
    has_employees = user.has_perm("macs.view_employees")
    if user.has_perm("accounts.view_audit") and not has_employees:
        return redirect("logs:system")
    if not has_employees and EmployeeExt.objects.filter(user_id=user.pk).exists():
        return redirect("me")
    return redirect("employees:today")

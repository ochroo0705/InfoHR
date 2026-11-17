from typing import Any

from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy

from accounts import login_throttle
from accounts.landing import landing_url
from accounts.models import User
from accounts.password_change import finish_password_change, form_class_for


class ForcedPasswordChangeView(PasswordChangeView):
    """Change-password page. Also the place a temporary password is replaced (then no old password is asked)."""

    template_name = "registration/password_change.html"
    success_url = reverse_lazy("home")

    def get_form_class(self) -> Any:
        return form_class_for(self.request.user)  # type: ignore[arg-type]

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:  # type: ignore[type-arg]
        form.save()
        finish_password_change(self.request, form.user)
        return HttpResponseRedirect(self.get_success_url())


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
    """Landing page: the rule lives in accounts/landing.py (also sent to the SPA as `landing` in /meta)."""
    user = request.user
    assert isinstance(user, User)
    return redirect(landing_url(user))

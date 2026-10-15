from typing import Any

from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import PasswordChangeView
from django.http import HttpResponse
from django.urls import reverse_lazy

from accounts.forms import ChangePasswordForm, NewPasswordForm


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
        return response

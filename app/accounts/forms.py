"""Password forms with short Mongolian labels and messages (Django's own are partly untranslated)."""

from typing import Any

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm

RULES_HINT = "Дор хаяж 8 тэмдэгт; том, жижиг үсэг, тоо тус бүр нэгээс доошгүй."

MESSAGES = {
    "password_too_short": "Хамгийн багадаа 8 тэмдэгт байна.",
    "password_mismatch": "Хоёр нууц үг таарахгүй байна.",
    "password_incorrect": "Хуучин нууц үг буруу байна.",
}


class _MongolianPasswordMixin(forms.Form):
    """New-password rule errors are shown once, under the new password; only a mismatch stays on the repeat."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Шинэ нууц үг"
        self.fields["new_password1"].help_text = RULES_HINT
        self.fields["new_password2"].label = "Шинэ нууц үг дахин"
        self.fields["new_password2"].help_text = ""
        if "old_password" in self.fields:
            self.fields["old_password"].label = "Хуучин нууц үг"

    def _post_clean(self) -> None:
        super()._post_clean()  # type: ignore[misc]
        errs = self.errors  # already filled: _post_clean runs inside full_clean
        for name in ("old_password", "new_password1", "new_password2"):
            if name not in errs:
                continue
            errors = errs.pop(name).as_data()
            for e in errors:
                target = name if name != "new_password2" or e.code == "password_mismatch" else "new_password1"
                text = MESSAGES.get(e.code or "", " ".join(e.messages))
                if text not in errs.get(target, []):
                    errs.setdefault(target, self.error_class(renderer=self.renderer)).append(text)
        for name in ("new_password1", "new_password2"):
            if name in errs:
                self.cleaned_data.pop(name, None)


class NewPasswordForm(_MongolianPasswordMixin, SetPasswordForm):  # type: ignore[type-arg]
    """Replacing a temporary password: the user just logged in with it, so it is not asked again."""


class ChangePasswordForm(_MongolianPasswordMixin, PasswordChangeForm):
    """A normal password change asks for the current password."""

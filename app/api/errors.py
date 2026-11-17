from typing import Any

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from ninja import Schema


class ErrorOut(Schema):
    field_errors: dict[str, list[str]] = {}
    form_errors: list[str] = []


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        form_errors: list[str],
        field_errors: dict[str, list[str]] | None = None,
        code: str = "",
    ) -> None:
        super().__init__(form_errors)
        self.status = status
        self.form_errors = form_errors
        self.field_errors = field_errors or {}
        self.code = code


def form_error_payload(form: forms.BaseForm) -> dict[str, Any]:
    field_errors: dict[str, list[str]] = {}
    form_errors: list[str] = []
    for name, messages in form.errors.items():
        if name == NON_FIELD_ERRORS:
            form_errors.extend(str(m) for m in messages)
        else:
            field_errors[name] = [str(m) for m in messages]
    return {"field_errors": field_errors, "form_errors": form_errors}

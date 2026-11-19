"""The shared pieces of the pop-up APIs (the employee writes, the event pop-ups, the order pop-ups): the field schemas
the pop-ups draw, the result shape of a save, the money kind of a MoneyField box, and the 404/403 mapping of a service.

The field schema lives here, not in employee_writes, so that the modules importing it do not form an import cycle with
employee_writes (which imports `money_kinds` from here). employee_writes re-exports the two field schemas under their
old names, so the OpenAPI names are unchanged.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from accounts.models import User
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied
from django.forms import BaseForm
from django.forms import Form as DjangoForm
from django.http import Http404, HttpRequest
from employees.money import MoneyField
from employees.services.form_schema import describe_form
from ninja import Schema
from ninja.errors import HttpError

from api.errors import ApiError

NOT_FOUND = "Хуудас олдсонгүй"
FORBIDDEN = "Хандах эрх байхгүй."


class EmployeeFormChoiceOut(Schema):
    value: str
    label: str


class EmployeeFormFieldOut(Schema):
    name: str  # the HTML name the browser posts (the salary fields carry the «si-» prefix)
    label: str
    required: bool
    kind: str  # checkbox | select | textarea | date | number | file | text | money
    value: str  # the stored value as the browser would post it
    checked: bool  # checkboxes only
    placeholder: str
    choice: str  # a select's shown label for the stored value, "" otherwise
    combo: bool  # the select is drawn as a typing box (select.js)
    choices: list[EmployeeFormChoiceOut]  # a select's options, blank entry included when the form has one
    help: str
    max_length: int | None
    errors: list[str]


# A pop-up's field, as every pop-up API describes it (one schema, the employees' form fields).
HrPopupFieldOut = EmployeeFormFieldOut


class HrPopupOut(Schema):
    title: str
    hint: str
    submit_label: str
    multipart: bool
    fields: list[EmployeeFormFieldOut]


class HrPopupResultOut(Schema):
    ok: bool
    field_errors: dict[str, list[str]]  # by HTML name
    form_errors: list[str]


def request_user(request: HttpRequest) -> User:
    """The signed-in user of a request (the routes say django_auth, so it is always a User here)."""
    assert isinstance(request.user, User)
    return request.user


def hr_popup_out(title: str, hint: str, submit_label: str, form: BaseForm, multipart: bool = False) -> dict[str, Any]:
    """A pop-up as the React page draws it: its title and hint, the button label, whether it posts a file, and its
    fields (money kinds applied)."""
    return {
        "title": title,
        "hint": hint,
        "submit_label": submit_label,
        "multipart": multipart,
        "fields": form_described(form),
    }


@contextmanager
def service_errors() -> Iterator[None]:
    """A pop-up's rights are 403 (code "forbidden"); an unknown or foreign object is 404 in the API's own shape (the
    rules raise Http404 or PermissionDenied)."""
    try:
        yield
    except Http404:
        raise HttpError(404, NOT_FOUND) from None
    except PermissionDenied:
        raise ApiError(403, [FORBIDDEN], code="forbidden") from None


def plain_amount(value: str) -> str:
    """A money value as the pop-up shows it: a whole amount without the ".00" tail ("2500000"), a real fraction kept
    as stored ("2500000.50"). Anything that is not a number is returned unchanged."""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return value
    if not amount.is_finite() or amount != amount.to_integral_value():
        return value
    return str(int(amount))


def money_kinds(form: BaseForm, fields: list[dict[str, Any]]) -> None:
    """A MoneyField's box takes the money kind, not a plain text box, and its value is the plain amount. Changes the
    described `fields` in place; a field that is not a MoneyField is left as described."""
    shown = cast(DjangoForm, form)  # a ModelForm is a BaseForm; the field lookup is the same
    by_name = {shown.add_prefix(name): field for name, field in shown.fields.items()}  # HTML name -> field
    for field in fields:
        if isinstance(by_name[str(field["name"])], MoneyField):
            field["kind"] = "money"
            field["value"] = plain_amount(str(field["value"]))


def form_described(form: BaseForm) -> list[dict[str, Any]]:
    """The form's visible fields as the pop-ups draw them, with the money kind applied."""
    fields = describe_form(cast(DjangoForm, form))
    money_kinds(form, fields)
    return fields


def errors_of(form: BaseForm | None) -> tuple[dict[str, list[str]], list[str]]:
    """A form's errors as (field errors by HTML name, form errors). An empty tuple for no form."""
    if form is None:
        return {}, []
    fields: dict[str, list[str]] = {}
    general: list[str] = []
    for name, messages in form.errors.items():
        if name == NON_FIELD_ERRORS:
            general.extend(str(message) for message in messages)
        else:
            fields[form.add_prefix(name)] = [str(message) for message in messages]
    return fields, general


def order_note(order_form: BaseForm) -> str:
    """The order block's note: the text after the heading's «· » in employees/_order_fields.html (the React block draws
    the heading word «Тушаал» itself). The number is required on a hire (and on a change that needs an order); a blank
    date means the effective date of the change."""
    number = "дугаар заавал" if order_form.fields["number"].required else "тушаал шаардлагатай өөрчлөлтөд дугаар заавал"
    note = number
    if not order_form.fields["date"].required:
        note += ", огноо хоосон бол өөрчлөлтийн огноо"
    return note

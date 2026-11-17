import json

import pytest
from accounts.models import User
from django import forms
from django.http import HttpResponse
from django.test import Client, RequestFactory
from ninja.errors import AuthenticationError, ValidationError

from api.errors import ApiError, form_error_payload
from api.main import api


class NameForm(forms.Form):
    name = forms.CharField()


def test_openapi_served(client: Client) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "MACS Human Capital API"


def test_docs_page_disabled(client: Client) -> None:
    assert client.get("/api/v1/docs").status_code == 404


def test_form_error_payload() -> None:
    form = NameForm(data={})
    form.is_valid()
    form.add_error(None, "Бүхэлдээ буруу")

    payload = form_error_payload(form)

    assert payload == {
        "field_errors": {"name": [str(m) for m in form.errors["name"]]},
        "form_errors": ["Бүхэлдээ буруу"],
    }


def test_api_error_handler() -> None:
    # The handler lookup is the one registered on api.main.api; no test route is added.
    request = RequestFactory().get("/api/v1/")

    response = api.on_exception(request, ApiError(409, ["Давхардсан"], code="dup"))

    assert isinstance(response, HttpResponse)
    assert response.status_code == 409
    assert json.loads(response.content) == {"field_errors": {}, "form_errors": ["Давхардсан"], "code": "dup"}


def test_api_error_without_code_omits_key() -> None:
    request = RequestFactory().get("/api/v1/")

    response = api.on_exception(request, ApiError(409, ["Давхардсан"]))

    assert response.status_code == 409
    assert json.loads(response.content) == {"field_errors": {}, "form_errors": ["Давхардсан"]}


def test_validation_error_maps_to_field_errors() -> None:
    request = RequestFactory().get("/api/v1/")
    exc = ValidationError([{"loc": ["body", "payload", "name"], "msg": "x", "type": "missing"}])

    response = api.on_exception(request, exc)

    assert response.status_code == 400
    assert json.loads(response.content) == {"field_errors": {"name": ["x"]}, "form_errors": []}


def test_authentication_error_maps_to_401() -> None:
    request = RequestFactory().get("/api/v1/")

    response = api.on_exception(request, AuthenticationError())

    assert response.status_code == 401
    assert json.loads(response.content) == {
        "field_errors": {},
        "form_errors": ["Нэвтрэх шаардлагатай."],
        "code": "not_authenticated",
    }


@pytest.mark.django_db
def test_csrf_failure_is_json_with_code() -> None:
    # ninja raises "CSRF check Failed" before the view runs; the handler turns it into the JSON shape with a code.
    user = User.objects.create_user("csrf-user", is_active=True)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        "/api/v1/attention/toggle", json.dumps({"keys": [], "action": "dismiss"}), content_type="application/json"
    )

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "field_errors": {},
        "form_errors": ["CSRF check Failed"],
        "code": "csrf_failed",
    }

"""The bulk cell edit endpoint reports:cells_bulk (decision D-080 phase 3)."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee

from reports import bulk_edit, cell_edit

pytestmark = pytest.mark.django_db

URL = "/reports/cells/"


def _post(client: Client, body: Any) -> Any:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(URL, data=payload, content_type="application/json")


def test_dry_run_answers_the_outcome_per_cell_and_writes_nothing(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    body = {
        "apply": False,
        "cells": [{"person": hired.pk, "field": "private_phone", "text": "99110001", "old": ""}],
    }
    response = _post(client, body)
    assert response.status_code == 200
    assert response.json() == {
        "cells": [{"person": hired.pk, "field": "private_phone", "ok": True, "text": "99110001", "error": ""}],
        "saved": 0,
    }
    hired.refresh_from_db()
    assert hired.private_phone != "99110001"


def test_apply_writes_and_counts_the_saved_cells(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    body = {
        "apply": True,
        "cells": [{"person": hired.pk, "field": "private_phone", "text": "99110001", "old": ""}],
    }
    response = _post(client, body)
    assert response.status_code == 200
    assert response.json()["saved"] == 1
    hired.refresh_from_db()
    assert hired.private_phone == "99110001"


def test_field_that_is_not_editable_is_a_refused_cell_not_a_400(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    body = {"apply": True, "cells": [{"person": hired.pk, "field": "salary", "text": "1", "old": ""}]}
    response = _post(client, body)
    assert response.status_code == 200
    assert response.json()["cells"][0]["error"] == bulk_edit.NOT_ALLOWED
    assert response.json()["saved"] == 0


def test_stale_old_text_is_refused_with_clash(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")
    body = {"apply": True, "cells": [{"person": hired.pk, "field": "private_phone", "text": "99110001", "old": ""}]}
    response = _post(client, body)
    assert response.json()["cells"][0]["error"] == cell_edit.CLASH
    hired.refresh_from_db()
    assert hired.private_phone == "99001122"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        {"cells": []},  # apply missing
        {"apply": "yes", "cells": []},  # apply not a bool
        {"apply": True, "cells": "x"},  # cells not a list
        {"apply": True, "cells": ["x"]},  # a cell that is not an object
        {"apply": True, "cells": [{"person": "5", "field": "email", "text": "", "old": ""}]},  # person not an int
        {"apply": True, "cells": [{"person": 1, "field": "email", "text": None, "old": ""}]},  # text not a string
    ],
)
def test_bad_body_is_400(client: Client, login_as: Callable[..., User], body: Any) -> None:
    login_as(client, "HR")
    assert _post(client, body).status_code == 400


def test_more_than_500_cells_is_400(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    cell = {"person": hired.pk, "field": "private_phone", "text": "1", "old": ""}
    response = _post(client, {"apply": False, "cells": [cell] * (bulk_edit.MAX_CELLS + 1)})
    assert response.status_code == 400
    assert response.json() == {"error": bulk_edit.TOO_MANY}


def test_anonymous_is_sent_to_login(client: Client, hired: Employee) -> None:
    body = {"apply": True, "cells": [{"person": hired.pk, "field": "private_phone", "text": "1", "old": ""}]}
    response = _post(client, body)
    assert response.status_code == 302
    hired.refresh_from_db()
    assert hired.private_phone != "1"


def test_get_is_not_allowed(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert client.get(URL).status_code == 405

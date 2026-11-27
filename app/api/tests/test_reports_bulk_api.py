# ruff: noqa: F811  (the test functions take the employee fixtures imported below, as the other test modules do)
"""The bulk cell edit route POST /api/v1/reports/cells (api/reports_edit.py). The rules are reports.bulk_edit's; these
tests pin the route: the login (401), the 400 body of the wrong shape (the same {"error": ...} as the Django view), a
dry run that writes nothing, an apply that saves the ok cells and counts them, a refused cell (200, never 400), the
stale check, the date reading, the correction key refused, the ambiguous label, and the no-store header."""

import json
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django import forms
from django.test import Client
from employees.models import Employee
from employees.tests.conftest import actor, hire_values, named  # noqa: F401 (fixtures the hired fixture needs)
from reports import bulk_edit, cell_edit

from api.tests.logs_support import job_values  # noqa: F401 (fixtures the hired fixture needs)
from api.tests.test_reports_edit_api import accountant, hired, hr  # noqa: F401 (fixtures)

pytestmark = pytest.mark.django_db

BULK = "/api/v1/reports/cells"
NOT_LOGGED_IN_BODY = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}


def _as(user: User | None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _post(client: Client, body: Any) -> Any:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(BULK, data=payload, content_type="application/json")


def _cell(person: int, field: str, text: str, old: str = "") -> dict[str, Any]:
    return {"person": person, "field": field, "text": text, "old": old}


def test_anonymous_is_401_with_the_login_body(hired: Employee) -> None:
    response = _post(_as(None), {"apply": True, "cells": [_cell(hired.pk, "private_phone", "99110001")]})
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN_BODY


def test_dry_run_writes_nothing_and_counts_no_save(hr: User, hired: Employee) -> None:
    before = Employee.objects.get(pk=hired.pk).private_phone
    response = _post(_as(hr), {"apply": False, "cells": [_cell(hired.pk, "private_phone", "99110001")]})
    assert response.status_code == 200
    assert response.json() == {
        "cells": [{"person": hired.pk, "field": "private_phone", "ok": True, "text": "99110001", "error": ""}],
        "saved": 0,
    }
    assert response["Cache-Control"] == "no-store"
    assert Employee.objects.get(pk=hired.pk).private_phone == before


def test_apply_saves_the_ok_cells_and_counts_them(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "private_phone", "99110001")]})
    assert response.status_code == 200
    assert response.json()["saved"] == 1
    assert Employee.objects.get(pk=hired.pk).private_phone == "99110001"


def test_a_salary_field_without_the_right_is_a_refused_cell_not_a_400(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "account_no", "5001")]})
    assert response.status_code == 200
    assert response.json()["cells"][0] == {
        "person": hired.pk,
        "field": "account_no",
        "ok": False,
        "text": "",
        "error": bulk_edit.NOT_ALLOWED,
    }
    assert response.json()["saved"] == 0


def test_a_governed_field_is_refused_as_a_cell(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "salary", "1")]})
    assert response.status_code == 200
    assert response.json()["cells"][0]["error"] == bulk_edit.NOT_ALLOWED


def test_a_correction_key_is_refused_as_a_cell(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "department", "Яам")]})
    assert response.status_code == 200
    assert response.json()["cells"][0]["error"] == bulk_edit.NOT_ALLOWED
    assert response.json()["saved"] == 0


def test_a_stale_old_text_gives_clash_and_writes_nothing(hr: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "private_phone", "99110001", old="")]})
    assert response.json()["cells"][0]["error"] == cell_edit.CLASH
    assert Employee.objects.get(pk=hired.pk).private_phone == "99001122"


def test_a_dotted_date_is_read_as_a_date(hr: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(birth_date=date(1999, 11, 22))
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "birth_date", "2001.02.03", old="1999-11-22")]})
    assert response.json()["cells"][0] == {
        "person": hired.pk,
        "field": "birth_date",
        "ok": True,
        "text": "2001-02-03",
        "error": "",
    }
    assert Employee.objects.get(pk=hired.pk).birth_date == date(2001, 2, 3)


def test_a_choice_label_shared_by_two_options_is_ambiguous(
    hr: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No employee field in the fixtures has two options with one label, so the editor form of the field is replaced
    # by one that does; the matching itself is the real bulk_edit.to_posted.
    class _TwoSame(forms.Form):
        gender = forms.ChoiceField(choices=[("a", "Нэг"), ("b", "нэг ")])

    monkeypatch.setattr(bulk_edit.cell_edit, "editor_form", lambda *args, **kwargs: _TwoSame())
    response = _post(_as(hr), {"apply": True, "cells": [_cell(hired.pk, "gender", "НЭГ", old="Эмэгтэй")]})
    assert response.json()["cells"][0]["error"] == bulk_edit.AMBIGUOUS.format("НЭГ")
    assert response.json()["saved"] == 0


@pytest.mark.parametrize(
    "body", [b"not json", {"cells": []}, {"apply": "yes", "cells": []}, {"apply": True, "cells": "x"}]
)
def test_a_bad_body_is_400_with_the_django_error(hr: User, body: Any) -> None:
    response = _post(_as(hr), body)
    assert response.status_code == 400
    assert response.json() == {"error": bulk_edit.BAD_REQUEST}
    assert response["Cache-Control"] == "no-store"


def test_more_than_500_cells_is_400_too_many(hr: User, hired: Employee) -> None:
    cell = _cell(hired.pk, "private_phone", "1")
    response = _post(_as(hr), {"apply": False, "cells": [cell] * (bulk_edit.MAX_CELLS + 1)})
    assert response.status_code == 400
    assert response.json() == {"error": bulk_edit.TOO_MANY}

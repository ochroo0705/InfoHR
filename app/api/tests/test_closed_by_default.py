import re

import pytest
from django.test import Client

from api.main import api

# The only operations that answer an anonymous caller. Each one says `auth=None` in its own code.
ALLOWED = {
    ("/api/v1/auth/csrf", "get"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/meta", "get"),
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
PATH_PARAM = re.compile(r"\{[^}]+\}")


def _operations() -> list[tuple[str, str]]:
    schema = api.get_openapi_schema()
    found: list[tuple[str, str]] = []
    for path, item in schema["paths"].items():
        for method in item:
            if method in HTTP_METHODS:
                found.append((path, method))  # schema paths already carry the /api/v1 prefix
    return found


def test_schema_has_operations() -> None:
    # Guards the walk below: an empty schema would make the closed-by-default test pass for nothing,
    # and an allow-list entry that no longer exists in the schema would be a stale rule.
    operations = set(_operations())
    assert ALLOWED <= operations
    assert len(operations) > len(ALLOWED)


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "method"), sorted(_operations()))
def test_anonymous_refused_unless_allowed(path: str, method: str) -> None:
    if PATH_PARAM.search(path):
        pytest.skip(f"{method.upper()} {path} has path parameters; add a concrete case when one exists")
    client = Client()  # default client: no CSRF enforcement, so a 401 can only come from auth

    response = client.generic(method.upper(), path, content_type="application/json")

    if (path, method) in ALLOWED:
        assert response.status_code != 401, f"{method.upper()} {path} must stay open to anonymous callers"
    else:
        message = f"{method.upper()} {path} answered {response.status_code} to an anonymous caller"
        assert response.status_code == 401, message

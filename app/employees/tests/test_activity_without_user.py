"""History lines written without a user (the D-083 data migration numbers old orders with `by=None`) must render."""

import pytest
from django.template.loader import render_to_string

from employees.models import ActivityEntry


@pytest.mark.django_db
@pytest.mark.parametrize(
    "template",
    ["employees/_order_history.html"],  # _activity_entries needs a saved entry; checked on the demo page instead
)
def test_entry_without_user_renders_as_system(template: str) -> None:
    entry = ActivityEntry(by=None, message="тест")
    html = render_to_string(template, {"entries": [entry], "activity": [entry]})
    assert "Систем" in html

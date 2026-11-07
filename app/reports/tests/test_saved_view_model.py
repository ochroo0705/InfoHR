import pytest

from reports.models import SavedView

pytestmark = pytest.mark.django_db


def test_new_saved_view_defaults_to_shared_and_not_default() -> None:
    view = SavedView.objects.create(report="staff-list", name="Жагсаалт")
    view.refresh_from_db()
    assert view.visibility == "shared"
    assert view.is_default is False


def test_long_query_of_3900_characters_saves_and_reloads_equal() -> None:
    query = "f=" + "a" * 3898
    assert len(query) == 3900
    view = SavedView.objects.create(report="staff-list", name="Урт", query=query)
    view.refresh_from_db()
    assert view.query == query


def test_visibility_choices_are_exactly_shared_and_private() -> None:
    field = SavedView._meta.get_field("visibility")
    assert field.choices is not None
    assert {value for value, _label in field.choices} == {"shared", "private"}


def test_query_max_length_is_4000() -> None:
    assert SavedView._meta.get_field("query").max_length == 4000

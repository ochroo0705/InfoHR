"""Order state chip (UI_RULES §8a): a signed order carries the red seal, every other state stays a quiet chip."""

from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.django_db


def _chip(state: str, label: str) -> str:
    order = SimpleNamespace(state=state, get_state_display=label)
    return render_to_string("employees/_order_state.html", {"order": order})


def test_signed_order_shows_the_seal() -> None:
    html = _chip("signed", "Гарын үсэгтэй")
    assert 'class="seal"' in html
    assert "Гарын үсэгтэй" in html


def test_other_states_have_no_seal() -> None:
    for state, label in (("pending", "Дугаар оруулаагүй"), ("registered", "Бүртгэсэн"), ("cancelled", "Цуцалсан")):
        assert "seal" not in _chip(state, label)


def test_legacy_row_has_no_seal() -> None:
    html = render_to_string("employees/_order_state.html", {"order": None, "legacy": True})
    assert "seal" not in html

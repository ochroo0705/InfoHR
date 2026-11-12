"""The `{{signature}}` placeholder: every starter template has its own signature line, and the filled order carries
the blank line (on paper) or the token (for the on-screen signing step) in that place."""

import io

import pytest
from accounts.models import User
from docx import Document

from employees.models import Employee, HrOrder, OrderType
from employees.services import order_docs

pytestmark = pytest.mark.django_db


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def paragraph_texts(data: bytes) -> list[str]:
    return [p.text for p in Document(io.BytesIO(data)).paragraphs]


@pytest.mark.parametrize("order_type", list(OrderType))
def test_every_starter_puts_the_signature_on_the_director_line(order_type: OrderType) -> None:
    """The marker sits in the director's line itself («<marker> /<director>/»), not in a line of its own, so the
    picture lands on that line."""
    texts = [p.text for p in Document(str(order_docs.starter_path(order_type))).paragraphs]
    marked = [text for text in texts if "{{signature}}" in text]
    assert marked == ["{{signature}} /{{ issued_by }}/"]
    assert "{{signature}}" not in texts  # no paragraph is the marker alone


def test_render_leaves_the_blank_line_on_the_director_line_by_default(hired: Employee, actor: User) -> None:
    text = paragraph_texts(order_docs.render_order(hire_order(hired), actor))
    line = [t for t in text if t.startswith(order_docs.BLANK_SIGNATURE + " /")]
    assert len(line) == 1 and line[0].endswith("/")
    assert not any("{{" in t or "[[" in t for t in text)  # no stray markers


def test_signature_is_in_the_placeholder_lists() -> None:
    assert "signature" in order_docs.PLACEHOLDERS
    assert "signature" in order_docs.COMMON_PLACEHOLDERS
    assert any(name == "signature" for _group, name, _text in order_docs.PLACEHOLDER_HELP)


def test_render_puts_the_token_on_the_director_line_when_asked(hired: Employee, actor: User) -> None:
    data = order_docs.render_order(hire_order(hired), actor, signature=order_docs.SIGNATURE_TOKEN)
    line = [t for t in paragraph_texts(data) if t.startswith(order_docs.SIGNATURE_TOKEN + " /")]
    assert len(line) == 1

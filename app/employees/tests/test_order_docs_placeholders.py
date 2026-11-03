"""The pop-up that explains the order template placeholders keeps in step with the placeholders themselves."""

import pytest
from django.test import Client
from django.urls import reverse

from employees.models import OrderTemplate, OrderType
from employees.services import order_docs

pytestmark = pytest.mark.django_db


def test_every_placeholder_has_a_meaning_and_no_extra() -> None:
    assert [name for _group, name, _text in order_docs.PLACEHOLDER_HELP] == list(order_docs.PLACEHOLDERS)
    assert all(text.strip() for _group, _name, text in order_docs.PLACEHOLDER_HELP)


def test_template_page_offers_the_explanation_pop_up(admin_client: Client) -> None:
    OrderTemplate.ensure_all()
    row = OrderTemplate.objects.first()
    assert row is not None
    html = admin_client.get(reverse("admin:employees_ordertemplate_change", args=[row.pk])).content.decode()
    assert "Талбаруудын тайлбар" in html
    assert "{{ employee_full_name }}" in html
    assert "css/admin_order_fields.css" in html


@pytest.mark.parametrize("order_type", list(OrderType))
def test_each_order_type_lists_only_what_its_starter_template_can_use(order_type: OrderType) -> None:
    from docxtpl import DocxTemplate

    listed = set(order_docs.placeholders_for(order_type))
    assert listed <= set(order_docs.PLACEHOLDERS)
    used = DocxTemplate(str(order_docs.starter_path(order_type))).get_undeclared_template_variables()
    assert set(used) <= listed  # the bundled template uses nothing the page does not list


def test_pop_up_shows_only_the_placeholders_of_its_order_type(admin_client: Client) -> None:
    OrderTemplate.ensure_all()
    hired = OrderTemplate.objects.get(order_type=OrderType.HIRED)
    fired = OrderTemplate.objects.get(order_type=OrderType.FIRED)
    page = lambda row: admin_client.get(reverse("admin:employees_ordertemplate_change", args=[row.pk])).content.decode()  # noqa: E731
    assert "{{ salary }}" in page(hired) and "{{ termination_reason }}" not in page(hired)
    assert "{{ termination_reason }}" in page(fired) and "{{ salary }}" not in page(fired)

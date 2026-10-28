"""Word documents of HR orders: Mongolian dates, the placeholder context, the download."""

import io
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from docx import Document

from employees.models import CompanySettings, Employee, HrOrder, OrderState, OrderType
from employees.services import order_docs, orders

from .conftest import link_login
from .helpers import sign_event
from .test_event_views import promote_data, url
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def text_of(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def test_day_endings_follow_the_last_digit() -> None:
    assert [order_docs.day_ending(d) for d in (1, 2, 3, 4, 9, 10, 11, 20, 21, 30, 31)] == [
        "ний", "ны", "ны", "ний", "ний", "ны", "ний", "ны", "ний", "ны", "ний",
    ]  # fmt: skip


def test_mn_date_carries_its_own_ending() -> None:
    assert order_docs.mn_date(date(2026, 11, 1)) == "2026 оны нэгдүгээр сарын 1-ний".replace(
        "нэгдүгээр", "арван нэгдүгээр"
    )
    assert order_docs.mn_date(date(2026, 3, 22)) == "2026 оны гуравдугаар сарын 22-ны"
    assert order_docs.mn_date(None) == order_docs.BLANK_DATE


def test_hire_context_of_a_pending_order(hired: Employee, actor: User) -> None:
    ctx = order_docs.build_context(hire_order(hired), actor)
    assert ctx["position"] == "Нягтлан" and ctx["department"] == "Санхүү"
    assert ctx["effective_date"] == "2026 оны нэгдүгээр сарын 5-ны"
    assert ctx["order_number"] == order_docs.BLANK_NUMBER and ctx["order_date"].startswith(order_docs.BLANK_DATE)
    assert ctx["order_summary"] == "Ажилд томилох тухай"
    assert ctx["salary"] == ""  # this user may not see salary


def test_salary_is_filled_only_for_a_user_who_may_see_it(hired: Employee, actor: User) -> None:
    actor.user_permissions.add(Permission.objects.get(codename="view_salary"))
    actor = User.objects.get(pk=actor.pk)
    assert order_docs.build_context(hire_order(hired), actor)["salary"] == "2,500,000₮"


def test_registered_order_uses_its_own_number_date_and_issuer(hired: Employee, actor: User) -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={"name": "Инфо ХХК", "director_name": "Б. Дорж"})
    order = orders.register(
        hire_order(hired), number="12", date=date(2026, 1, 5), summary="Томилов", issued_by="", by=actor
    )
    ctx = order_docs.build_context(order, actor)
    assert (ctx["order_number"], ctx["order_summary"], ctx["issued_by"]) == ("12", "Томилов", "Б. Дорж")
    assert ctx["order_date"] == "2026 оны нэгдүгээр сарын 5-ны өдөр" and ctx["company_name"] == "Инфо ХХК"


def test_position_change_context_has_old_and_new(hr: Client, hired: Employee, actor: User) -> None:
    assert hr.post(url(hired, "promotion"), promote_data(hired)).status_code == 204
    sign_event(hired.events.get(), by=actor)  # the old and new positions are read from the applied rows
    order = HrOrder.objects.get(employee=hired, event__isnull=False)
    ctx = order_docs.build_context(order, actor)
    assert order.order_type == OrderType.POSITION
    assert (ctx["old_position"], ctx["new_position"]) == ("Нягтлан", "Ахлах нягтлан")
    assert ctx["department"] == "Санхүү"


def test_download_is_a_filled_word_file(hr: Client, hired: Employee, actor: User) -> None:
    order = orders.register(hire_order(hired), number="А/12", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    response = hr.get(f"/employees/{hired.pk}/order/{order.pk}/document/")
    assert response.status_code == 200 and response["Content-Type"] == order_docs.DOCX_TYPE
    assert "attachment" in response["Content-Disposition"] and ".docx" in response["Content-Disposition"]
    body = text_of(b"".join(response.streaming_content))  # type: ignore[attr-defined]
    assert hired.full_name in body and "Санхүү хэлтсийн" in body and "№ А/12" in body
    assert "{{" not in body and "{%" not in body


def test_download_rules(
    client: Client, hr: Client, hired: Employee, actor: User, settings: Any, tmp_path: Path
) -> None:
    order = hire_order(hired)
    doc_url = f"/employees/{hired.pk}/order/{order.pk}/document/"
    settings.ORDER_TEMPLATES_DIR = tmp_path  # no templates there
    assert hr.get(doc_url).status_code == 404
    settings.ORDER_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "order_templates"
    assert hr.get(doc_url).status_code == 200
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    assert hr.get(doc_url).status_code == 404


def test_viewer_cannot_download_and_anonymous_is_sent_to_login(client: Client, hired: Employee) -> None:
    order = hire_order(hired)
    doc_url = f"/employees/{hired.pk}/order/{order.pk}/document/"
    assert client.get(doc_url).status_code == 302
    link_login(hired, login_as(client, "Employee", "me"))  # sees only their own record, may not manage
    assert client.get(doc_url).status_code == 403


def test_order_pop_up_offers_the_word_file(hr: Client, hired: Employee) -> None:
    body = hr.get(f"/employees/{hired.pk}/order/{hire_order(hired).pk}/detail/").content.decode()
    assert f"/employees/{hired.pk}/order/{hire_order(hired).pk}/document/" in body and "Word татах" in body


@pytest.mark.parametrize("order_type", list(OrderType))
def test_every_order_type_renders_without_leftover_tags(hired: Employee, actor: User, order_type: OrderType) -> None:
    order = hire_order(hired)
    order.order_type = order_type.value  # the template is chosen by type alone
    text = text_of(order_docs.render_order(order, actor))
    assert hired.full_name in text and "{{" not in text and "{%" not in text
    assert "өдрөөс" in text or "өдөр" in text


def _need_pdf_font() -> None:
    try:
        order_docs._pdf_fonts()
    except order_docs.OrderDocError:
        pytest.skip("no Cyrillic font on this machine")


@pytest.mark.parametrize("order_type", list(OrderType))
def test_every_order_type_makes_a_pdf(hired: Employee, actor: User, order_type: OrderType) -> None:
    _need_pdf_font()
    order = hire_order(hired)
    order.order_type = order_type.value
    data = order_docs.render_pdf(order, actor)
    assert data.startswith(b"%PDF-") and len(data) > 3000


def test_pdf_download_and_its_rules(hr: Client, client: Client, hired: Employee, settings: Any) -> None:
    _need_pdf_font()
    order = hire_order(hired)
    pdf_url = f"/employees/{hired.pk}/order/{order.pk}/document/pdf/"
    response = hr.get(pdf_url)
    assert response.status_code == 200 and response["Content-Type"] == order_docs.PDF_TYPE
    assert 'filename="tushaal-id' in response["Content-Disposition"] and ".pdf" in response["Content-Disposition"]
    assert b"".join(response.streaming_content).startswith(b"%PDF-")  # type: ignore[attr-defined]
    fonts = settings.ORDER_PDF_FONT_SETS
    settings.ORDER_PDF_FONT_SETS = []  # no usable font
    assert hr.get(pdf_url).status_code == 404
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    settings.ORDER_PDF_FONT_SETS = fonts
    assert hr.get(pdf_url).status_code == 404


def test_pdf_needs_the_manage_right(client: Client, hired: Employee) -> None:
    pdf_url = f"/employees/{hired.pk}/order/{hire_order(hired).pk}/document/pdf/"
    assert client.get(pdf_url).status_code == 302
    link_login(hired, login_as(client, "Employee", "me"))
    assert client.get(pdf_url).status_code == 403

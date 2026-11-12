"""Contact actions on a card: an e-mail or phone column's value becomes a mailto: or tel: link above the card's title
overlay, only for text that passes the pattern, and never for a column the viewer may not see."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.template.loader import get_template
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

TODAY = date(2026, 11, 7)
KEY = "card-actions-test"
PAGE = f"/reports/{KEY}/"
PERSONAL = "macs.view_personal"
LINK_CLASS = 'class="relative z-10 text-violet-700 hover:underline"'

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text", href=lambda r: "/employees/7/")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
EMAIL = Column(key="email", label="И-мэйл", value=lambda r: r.email, kind="text", action="mailto")
WORK = Column(key="work", label="Ажлын утас", value=lambda r: r.work, kind="text", action="tel")
PRIVATE = Column(
    key="private", label="Хувийн утас", value=lambda r: r.private, kind="text", action="tel", needs=PERSONAL
)
ROOM = Column(key="room", label="Өрөө", value=lambda r: r.room, kind="text")
COLUMNS = [NAME, DEPT, EMAIL, WORK]


def _row(
    email: object = "a@b.mn",
    work: object = "+976 9911-2233",
    private: object = "+976 8800-1122",
    room: str = "A1",
) -> Any:
    return SimpleNamespace(name="Бат", dept="Санхүү", email=email, work=work, private=private, room=room)


def _report(rows: list[Any], columns: tuple[Column, ...] = (NAME, DEPT, EMAIL, WORK, PRIVATE, ROOM)) -> Report:
    return Report(
        key=KEY,
        title="Card actions",
        filters=(),
        columns=columns,
        default_columns=tuple(c.key for c in columns),
        rows=lambda user, filters: rows,
        group_options=("dept",),
        layouts=("board", "cards"),
    )


def _table(rows: list[Any], columns: list[Column]) -> Table:
    spec = LayoutSpec(layout="board", by=None, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1))
    return Table(columns=columns, groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _links(email: object, work: object) -> tuple[str, ...]:
    """The links of one card whose extras are the e-mail and the work phone (four extras are allowed)."""
    rows = [_row(email=email, work=work)]
    items = layouts_mod.make_items(_table(rows, COLUMNS), rows, (), TODAY, extras=4)
    return items[0].links


@pytest.mark.django_db
def test_email_becomes_a_mailto_link(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _links("a@b.mn", "") == ("mailto:a@b.mn", "")
    monkeypatch.setitem(REPORTS, KEY, _report([_row(email="a@b.mn", work="")]))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "email", "work"]}).content.decode()
    assert f'<a href="mailto:a@b.mn" {LINK_CLASS}>a@b.mn</a>' in page


@pytest.mark.django_db
def test_phone_becomes_a_tel_link(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _links("", "+976 9911-2233") == ("", "tel:+97699112233")
    monkeypatch.setitem(REPORTS, KEY, _report([_row(email="", work="+976 9911-2233")]))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "email", "work"]}).content.decode()
    assert f'<a href="tel:+97699112233" {LINK_CLASS}>+976 9911-2233</a>' in page


def test_blank_value_gets_no_link() -> None:
    assert _links("", "") == ("", "")
    assert _links("   ", "   ") == ("", "")
    assert _links(None, None) == ("", "")


@pytest.mark.django_db
def test_odd_characters_get_no_link(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _links('a@b.com"><script>', "9911 22 <b>") == ("", "")
    assert _links("javascript:alert(1)", "") == ("", "")
    assert _links("a b@c.mn", "") == ("", "")  # a space inside an e-mail is not an address
    assert _links("a%3Fcc2@b.com", "") == ("", "")  # a percent-encoded header character is not allowed
    assert _links("", "+--") == ("", "")  # no digits, so no number to dial
    assert _links("", "- - -") == ("", "")
    assert _links("", "()()()") == ("", "")
    monkeypatch.setitem(REPORTS, KEY, _report([_row(email='a@b.com"><script>', work="9911 22 <b>")]))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "email", "work"]}).content.decode()
    assert 'href="mailto:' not in page
    assert 'href="tel:' not in page
    assert "a@b.com&quot;&gt;&lt;script&gt;" in page  # the value is shown as escaped text, not as markup


@pytest.mark.django_db
def test_private_phone_hidden_without_personal_permission(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, _report([_row()]))
    cols = ["name", "dept", "email", "work", "private"]
    login_as(client, "HR", name="hr-viewer")
    shown = client.get(PAGE, {"layout": "cards", "cols": cols}).content.decode()  # positive control
    assert "Хувийн утас" in shown
    assert 'href="tel:+97688001122"' in shown
    client.logout()
    login_as(client, "Accountant", name="accountant-viewer")  # no macs.view_personal
    page = client.get(PAGE, {"layout": "cards", "cols": cols}).content.decode()
    assert "Хувийн утас" not in page
    assert "8800" not in page
    assert 'href="tel:+97688001122"' not in page
    assert 'href="tel:+97699112233"' in page  # the work phone stays a link


@pytest.mark.django_db
def test_card_title_link_still_opens_the_employee(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, _report([_row()]))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "email", "work"]}).content.decode()
    overlay = "after:absolute after:inset-0 after:content-['']"
    assert f'<a href="/employees/7/" class="text-violet-700 hover:underline {overlay}">Бат</a>' in page


@pytest.mark.django_db
def test_extras_without_actions_unchanged(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, _report([_row()]))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "room"]}).content.decode()
    assert '<p class="text-slate-700"><span class="text-slate-500">Өрөө:</span> A1</p>' in page
    assert "mailto:" not in page
    assert "tel:" not in page


def test_linked_extra_renders_its_link_in_the_partial() -> None:
    items = [
        layouts_mod.Item(
            title="Бат",
            subtitle="Санхүү",
            href="",
            mark="",
            extras=(("И-мэйл", "a@b.mn", False),),
            links=("mailto:a@b.mn",),
        )
    ]
    rendered = get_template("reports/layouts/_cards_batch.html").render(
        {"cards_items": items, "cards_next_query": None}
    )
    link = f'<a href="mailto:a@b.mn" {LINK_CLASS}>a@b.mn</a>'
    assert f'<span class="text-slate-500">И-мэйл:</span> {link}</p>' in rendered

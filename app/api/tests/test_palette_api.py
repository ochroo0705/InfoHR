"""GET /api/v1/palette: the Ctrl+K palette's groups as the React palette reads them. The rows, the rights and the order
come from employees.services.palette_answer and employees.services.palette_rows; these tests pin the API's shape, its
query handling (the length cut, bad remembered items), its «show all» cap and fallback, its no-store header, its rights
and the sign-in rule. The parity tests compare the API with the Django fragment that employees:palette renders for the
same user and parameters: the same groups, in the same order, with the same rows."""

from datetime import date
from html.parser import HTMLParser
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import ensure_ext
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/palette"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
EMPTY_TEXT = "Юу ч олдсонгүй"
FALLBACK_HEADING = "Эсвэл нээх:"
YEAR = timezone.localdate().year
HIRED_FROM = date(YEAR - 1, 1, 5)  # counted on every day of this year, so the tests do not depend on the date
FAMILY = "Батын"  # the family name of the employee fixture (hire_values gives the given name Сараа)
ORDER_NUMBER = "77"  # the employee fixture's order: orders are found by their number


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _with_perms(name: str, perms: list[tuple[str, str]]) -> User:
    """A user whose only rights are the given (app label, codename) permissions."""
    user = User.objects.create_user(name, password=PASSWORD)
    group = Group.objects.create(name=f"palette_api_rights_{name}")
    group.permissions.set([Permission.objects.get(content_type__app_label=app, codename=code) for app, code in perms])
    user.groups.add(group)
    return User.objects.get(pk=user.pk)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _get(user: User, params: dict[str, str] | None = None) -> Any:
    return _client(user).get(URL, params or {})


def _titles(group: dict[str, Any]) -> list[str]:
    return ["".join(piece["text"] for piece in row["title"]) for row in group["rows"]]


def _group(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(g for g in body["groups"] if g["key"] == key)


def _api_groups(body: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """(title, count text, row titles) per group, as the fragment's headers and rows show them."""
    out = []
    for group in body["groups"]:
        count = str(group["count"]) + (f" / {group['total']}" if group["total"] else "")
        out.append((group["title"], count, _titles(group)))
    return out


class _Fragment(HTMLParser):
    """The groups of a rendered palette fragment: each header's title and count text, and the title of every row under
    it. A row is an anchor with data-palette-item; its title is its first truncated span (the name, the screen's title,
    the order's number line). Rows before the first header are not in a group and are left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.groups: list[tuple[str, str, list[str]]] = []
        self._sink: list[str] | None = None  # the text being collected
        self._header: list[list[str]] | None = None  # the spans of a group header
        self._row_open = False
        self._row_title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "p" and "sticky" in classes:
            self._header = []
        elif tag == "span" and self._header is not None:
            self._header.append([])
            self._sink = self._header[-1]
        elif tag == "a" and "data-palette-item" in values:
            self._row_open = True
            self._row_title = None
        elif tag == "span" and self._row_open and self._row_title is None and "truncate" in classes:
            self._row_title = []
            self._sink = self._row_title

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._sink = None
        elif tag == "p" and self._header is not None:
            spans = ["".join(span) for span in self._header]
            self.groups.append((spans[0], spans[1], []))
            self._header = None
        elif tag == "a" and self._row_open:
            self._row_open = False
            if self._row_title is not None and self.groups:
                self.groups[-1][2].append("".join(self._row_title))

    def handle_data(self, data: str) -> None:
        if self._sink is not None:
            self._sink.append(data)


def _html_groups(content: bytes) -> list[tuple[str, str, list[str]]]:
    parser = _Fragment()
    parser.feed(content.decode())
    return parser.groups


def _html_empty(content: bytes) -> bool:
    return b"data-palette-empty" in content


@pytest.fixture
def hr() -> User:
    return _user("palette_api_hr", roles.HR)


@pytest.fixture
def admin() -> User:
    return _user("palette_api_admin", roles.ADMIN)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("palette_api_actor", password=PASSWORD)


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _hire(actor: User, job_values: dict[str, Any], register_no: str, family: str, given: str) -> Any:
    values = {**hire_values(register_no), "family_name": family, "given_name": given}
    emp = history.hire(values, {}, start=HIRED_FROM, job=job_values, salary=None, by=actor, with_order=False)
    ensure_ext(emp)  # the palette finds only people HR has touched
    return emp


@pytest.fixture
def employee(actor: User, job_values: dict[str, Any]) -> Any:
    values = {**hire_values("УБ99112233"), "family_name": FAMILY, "given_name": "Сараа"}
    emp = history.hire(
        values,
        {},
        start=HIRED_FROM,
        job=job_values,
        salary=None,
        by=actor,
        order_number=ORDER_NUMBER,
        order_date=HIRED_FROM,
    )
    ensure_ext(emp)
    return emp


def test_requires_login(employee: Any) -> None:
    response = Client().get(URL)

    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_empty_box_returns_screens_actions_and_recent(hr: User, employee: Any) -> None:
    response = _get(hr)

    assert response.status_code == 200
    body = response.json()
    keys = [g["key"] for g in body["groups"]]
    assert "screens" in keys
    assert "actions" in keys
    assert "people" not in keys
    assert body["empty"] is False
    assert body["fallback"] == []
    assert "Асуух" not in response.content.decode()  # the assistant row is not part of this answer


def test_recent_rows_come_first_in_the_empty_box(hr: User, employee: Any) -> None:
    body = _get(hr, {"recent": f"p:{employee.pk}"}).json()

    first = body["groups"][0]
    assert first["key"] == "recent"
    assert first["rows"][0]["kind"] == "person"
    assert _titles(first) == [employee.full_name]


def test_typed_query_returns_people_with_highlight_pieces(hr: User, employee: Any) -> None:
    body = _get(hr, {"q": FAMILY}).json()

    people = _group(body, "people")
    row = people["rows"][0]
    assert people["count"] == 1
    assert row["kind"] == "person"
    assert row["ref"] == f"p:{employee.pk}"
    assert row["open"] == {
        "kind": "page",
        "path": reverse("employees:detail", args=[employee.pk]),
        "popup": None,
        "employee": None,
        "order": None,
        "event_type": None,
        "year": None,
    }
    assert "".join(piece["text"] for piece in row["title"]) == employee.full_name
    assert any(piece["hit"] for piece in row["title"])


def test_show_all_adds_the_people_past_the_first_eight(hr: User, actor: User, job_values: dict[str, Any]) -> None:
    for i in range(10):
        _hire(actor, job_values, f"УБ9921{i:04d}", "Олонтой", f"Нэр{i}")

    first = _get(hr, {"q": "Олонтой"}).json()
    people = _group(first, "people")
    assert people["count"] == 8
    assert people["total"] == 10
    assert people["rows"][-1]["kind"] == "more"
    assert people["rows"][-1]["open"] is None
    assert len(people["rows"]) == 9  # the eight people and the «show all» row

    more = _get(hr, {"q": "Олонтой", "more": "1"}).json()
    all_people = _group(more, "people")
    assert all_people["count"] == 10
    assert all_people["total"] is None
    assert all(row["kind"] == "person" for row in all_people["rows"])


def test_show_all_is_capped_at_fifty_people(hr: User, actor: User, job_values: dict[str, Any]) -> None:
    for i in range(51):
        _hire(actor, job_values, f"УБ9922{i:04d}", "Тоологдох", f"Нэр{i}")

    body = _get(hr, {"q": "Тоологдох", "more": "1"}).json()

    people = _group(body, "people")
    assert people["count"] == 50  # the cap: the 51st person is counted but not listed
    assert people["total"] == 51
    assert len(people["rows"]) == 50
    assert people["note"].startswith("Эхний 50 хүн")


def test_modal_rows_carry_open_target(admin: User) -> None:
    body = _get(admin, {"q": "Чөлөө бүртгэх"}).json()

    row = _group(body, "actions")["rows"][0]
    assert row["kind"] == "action"
    assert row["open"]["kind"] == "legacy"  # the leave pop-up is not ported yet: it opens its list page
    assert row["open"]["path"] == reverse("leave:list")

    slot = _get(admin, {"q": "Орон тоо нэмэх"}).json()
    slot_row = _group(slot, "actions")["rows"][0]
    assert slot_row["open"]["kind"] == "popup"
    assert slot_row["open"]["popup"] == "slot_add"
    assert slot_row["open"]["path"] == reverse("employees:slot_add")
    # The quick action has no ?year=: the pop-up opens with this year, so the React side has a number to open with.
    assert slot_row["open"] == {
        "kind": "popup",
        "path": reverse("employees:slot_add"),
        "popup": "slot_add",
        "employee": None,
        "order": None,
        "event_type": None,
        "year": YEAR,
    }


def test_slot_add_action_is_hidden_without_manage_position_slots(admin: User) -> None:
    user = _with_perms("palette_api_no_slot", [("macs", "view_employees")])
    query = {"q": "Орон тоо нэмэх"}

    admin_titles = _titles(_group(_get(admin, query).json(), "actions"))
    assert "Орон тоо нэмэх" in admin_titles  # the same query shows the row to an admin

    user_body = _get(user, query).json()
    user_actions = [g for g in user_body["groups"] if g["key"] == "actions"]
    user_titles = _titles(user_actions[0]) if user_actions else []
    assert "Орон тоо нэмэх" not in user_titles


def test_empty_answer_has_fallback_rows(admin: User) -> None:
    body = _get(admin, {"q": "zzqx"}).json()

    assert body["groups"] == []
    assert body["empty"] is True
    assert body["empty_text"] == EMPTY_TEXT
    assert body["fallback_heading"] == FALLBACK_HEADING
    titles = [row["title"][0]["text"] for row in body["fallback"]]
    assert "Ажилтнууд" in titles
    assert "Ажилтан нэмэх" in titles


def test_answer_with_results_has_no_fallback(hr: User, employee: Any) -> None:
    body = _get(hr, {"q": FAMILY}).json()

    assert body["empty"] is False
    assert body["fallback"] == []


def test_response_is_no_store(hr: User, employee: Any) -> None:
    assert _get(hr).headers["Cache-Control"] == "no-store"
    assert _get(hr, {"q": FAMILY}).headers["Cache-Control"] == "no-store"
    assert _get(hr, {"q": "zzqx"}).headers["Cache-Control"] == "no-store"


def test_bad_recent_values_are_ignored(hr: User, employee: Any) -> None:
    response = _get(hr, {"recent": "garbage,p:abc,s:notapath,p:99999999"})

    assert response.status_code == 200
    assert "recent" not in [g["key"] for g in response.json()["groups"]]


def test_recent_beyond_400_characters_is_not_read(hr: User, employee: Any) -> None:
    # Ten-odd dummy references fill the first 400 characters; the real one comes after them and must not be read.
    raw = "p:99999999," * 40 + f"p:{employee.pk}"
    assert raw.index(f"p:{employee.pk}") > 400

    response = _get(hr, {"recent": raw})

    assert response.status_code == 200
    assert "recent" not in [g["key"] for g in response.json()["groups"]]


def test_from_opens_the_current_person_actions_on_their_record(hr: User, employee: Any) -> None:
    path = reverse("employees:detail", args=[employee.pk])

    body = _get(hr, {"from": path}).json()

    current = _group(body, "current_actions")
    assert current["title"] == f"Үйлдэл · {employee.full_name}"
    assert current["rows"]


def test_overlong_query_is_read_as_the_view_reads_it(hr: User, employee: Any) -> None:
    long_query = FAMILY + " " * 146 + "zzqx" + " " * 45  # 200 characters; the second word is past the service's cut

    response = _get(hr, {"q": long_query})

    assert response.status_code == 200
    assert _group(response.json(), "people")["count"] == 1


# --- Parity with the Django fragment (employees:palette) for the same user and parameters ---


def _assert_parity(user: User, params: dict[str, str]) -> None:
    api_body = _get(user, params).json()
    html_response = _client(user).get(reverse("employees:palette"), params)

    assert _api_groups(api_body) == _html_groups(html_response.content)
    assert api_body["empty"] == _html_empty(html_response.content)


def test_parity_people_orders_and_screens_rows(hr: User, employee: Any) -> None:
    _assert_parity(hr, {"q": FAMILY})
    _assert_parity(hr, {"q": ORDER_NUMBER})  # orders: the register's number
    _assert_parity(hr, {"q": "Ажилтан"})  # quick actions and screens


def test_parity_empty_box_with_recent_and_current_person(hr: User, employee: Any) -> None:
    _assert_parity(hr, {})
    _assert_parity(hr, {"recent": f"p:{employee.pk}"})
    _assert_parity(hr, {"from": reverse("employees:detail", args=[employee.pk])})


def test_parity_nothing_found(hr: User, employee: Any) -> None:
    _assert_parity(hr, {"q": "zzqx"})


def test_parity_overlong_queries_answer_as_the_view_does(hr: User, employee: Any) -> None:
    _assert_parity(hr, {"q": " " * 100 + FAMILY})  # the first 100 characters hold no word
    _assert_parity(hr, {"q": "Ажилтан" + " " * 120 + "zzqx"})  # the second word is past the cut


def test_parity_show_all(hr: User, actor: User, job_values: dict[str, Any]) -> None:
    for i in range(10):
        _hire(actor, job_values, f"УБ9923{i:04d}", "Паритет", f"Нэр{i}")

    _assert_parity(hr, {"q": "Паритет"})
    _assert_parity(hr, {"q": "Паритет", "more": "1"})


# --- Rights: what the user may not see is left out of the answer and the fallback ---


def test_user_without_employee_view_gets_no_people_and_no_orders(employee: Any) -> None:
    user = _with_perms(
        "palette_api_no_view",
        [("macs", "manage_employees"), ("reports", "view_reports")],
    )

    people = _get(user, {"q": FAMILY}).json()
    orders = _get(user, {"q": ORDER_NUMBER}).json()

    assert "people" not in [g["key"] for g in people["groups"]]
    assert "orders" not in [g["key"] for g in orders["groups"]]


def test_fallback_without_employee_view_has_no_list_row() -> None:
    user = _with_perms("palette_api_fb_view", [("macs", "manage_employees"), ("reports", "view_reports")])

    body = _get(user, {"q": "zzqx"}).json()

    titles = [row["title"][0]["text"] for row in body["fallback"]]
    assert "Ажилтнууд" not in titles
    assert "Ажилтан нэмэх" in titles


def test_fallback_without_reports_has_no_list_row() -> None:
    user = _with_perms("palette_api_fb_reports", [("macs", "view_employees"), ("macs", "manage_employees")])

    body = _get(user, {"q": "zzqx"}).json()

    titles = [row["title"][0]["text"] for row in body["fallback"]]
    assert "Ажилтнууд" not in titles
    assert "Ажилтан нэмэх" in titles


def test_fallback_without_manage_employees_has_no_add_row() -> None:
    user = _with_perms("palette_api_fb_manage", [("macs", "view_employees"), ("reports", "view_reports")])

    body = _get(user, {"q": "zzqx"}).json()

    titles = [row["title"][0]["text"] for row in body["fallback"]]
    assert "Ажилтнууд" in titles
    assert "Ажилтан нэмэх" not in titles

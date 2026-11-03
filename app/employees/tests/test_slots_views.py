"""The position-slot screen «Орон тооны төлөвлөгөө» (position-slots plan, Task 3)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from macs.models import Branch, NazgRow, Position

from employees import palette, views_slots
from employees.models import CompanySettings, Employee
from employees.services import history, slots

from .conftest import hire_values
from .test_views import login_as

pytestmark = pytest.mark.django_db

YEAR = date.today().year
START = date(YEAR, 1, 5)


@pytest.fixture
def position(job_values: dict[str, Any]) -> Position:
    return job_values["position"]  # type: ignore[no-any-return]


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def hr(client: Client) -> User:
    return login_as(client, "HR", "slot_hr")


def _row(position: Position, branch: Branch, qty: int, *, kind: str = "Main", year: int = YEAR) -> NazgRow:
    return NazgRow.objects.create(kind=kind, qty=qty, year=year, position=position, branch=branch)


def _hire(
    actor: User, job_values: dict[str, Any], branch: Branch, n: int, *, contract: bool = False, start: date = START
) -> Employee:
    values = {**hire_values(f"УБ9922{n:04d}"), "branch": branch}
    job = {**job_values, **({"emptype": 5} if contract else {})}
    return history.hire(values, {}, start=start, job=job, salary=Decimal("1"), by=actor)


def _form(pos: Position, br: Branch, /, **extra: Any) -> dict[str, Any]:
    return {"position": pos.pk, "branch": br.pk, "kind": "Main", "year": YEAR, "qty": 2, **extra}


def _logged(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action, category="hr"))


# ---- list ----


def test_list_shows_posts_used_and_free_per_row_and_totals(
    client: Client, hr: User, position: Position, branch: Branch, job_values: dict[str, Any]
) -> None:
    _row(position, branch, 3)
    other = Position.objects.create(name="Инженер")
    _row(other, branch, 2, kind="Temporary")
    _hire(hr, job_values, branch, 1)
    page = client.get(reverse("employees:slots")).content.decode()
    assert "Орон тооны төлөвлөгөө" in page
    assert position.name in page and "Инженер" in page and branch.name in page
    assert "Үндсэн" in page and "Түр" in page
    context = client.get(reverse("employees:slots")).context
    rows = {r["row"].position.name: r for r in context["rows"]}
    assert (rows[position.name]["posts"], rows[position.name]["used"], rows[position.name]["free"]) == (3, 1, 2)
    assert (rows["Инженер"]["posts"], rows["Инженер"]["used"], rows["Инженер"]["free"]) == (2, 0, 2)
    assert context["totals"] == {"posts": 5, "used": 1, "free": 4}


def test_batch_used_matches_the_gate_counting(
    client: Client,
    hr: User,
    position: Position,
    branch: Branch,
    job_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    on = date(YEAR, 6, 15)  # one fixed day inside YEAR for the screen and the gate, whatever today is
    monkeypatch.setattr(views_slots, "_used_on", lambda year: on)
    _row(position, branch, 5)
    _row(position, branch, 4, kind="Temporary")
    _hire(hr, job_values, branch, 1)
    _hire(hr, job_values, branch, 2)
    _hire(hr, job_values, branch, 3, contract=True)
    _hire(hr, job_values, branch, 4, start=date(YEAR, 12, 30))  # starts later in the year: counts
    other = Branch.objects.create(name="Хөдөө салбар")
    _hire(hr, job_values, other, 5)  # another branch: not counted
    for r in client.get(reverse("employees:slots")).context["rows"]:
        expected = slots.check(position, branch, kind=r["row"].kind, on=on)
        assert (r["posts"], r["used"], r["free"]) == (expected.posts, expected.used, expected.free)
    kinds = {r["row"].kind: r["used"] for r in client.get(reverse("employees:slots")).context["rows"]}
    assert kinds == {"Main": 3, "Temporary": 1}


def test_list_uses_a_fixed_number_of_queries(
    client: Client, hr: User, position: Position, branch: Branch, django_assert_max_num_queries: Any
) -> None:
    client.get(reverse("employees:slots"))  # first request of the day runs the daily sync
    for i in range(12):
        _row(Position.objects.create(name=f"Албан тушаал {i}"), branch, 1)
    with django_assert_max_num_queries(25):
        client.get(reverse("employees:slots"))


def test_year_filter_and_bad_year(client: Client, hr: User, position: Position, branch: Branch) -> None:
    _row(position, branch, 3, year=YEAR)
    _row(position, branch, 7, year=YEAR + 1)
    default = client.get(reverse("employees:slots")).context
    assert default["year"] == YEAR and [r["posts"] for r in default["rows"]] == [3]
    nxt = client.get(reverse("employees:slots"), {"year": YEAR + 1}).context
    assert nxt["year"] == YEAR + 1 and [r["posts"] for r in nxt["rows"]] == [7]
    for bad in ("x", "-5", "99999999999999999999", "²", ""):
        response = client.get(reverse("employees:slots"), {"year": bad})
        assert response.status_code == 200 and response.context["year"] == YEAR


def test_empty_year_says_so(client: Client, hr: User) -> None:
    page = client.get(reverse("employees:slots"), {"year": YEAR + 3}).content.decode()
    assert "бүртгэгдээгүй" in page


def test_long_list_is_paged(client: Client, hr: User, branch: Branch, monkeypatch: pytest.MonkeyPatch) -> None:
    from config import batching

    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    for i in range(5):
        _row(Position.objects.create(name=f"Тушаал {i}"), branch, 1)
    first = client.get(reverse("employees:slots"))
    assert len(first.context["rows"]) == 2 and first.context["next_query"]
    assert first.context["totals"]["posts"] == 5  # totals cover every row, not the shown page
    more = client.get(reverse("employees:slots") + "?" + first.context["next_query"], headers={"HX-Request": "true"})
    assert more.status_code == 200 and len(more.context["rows"]) == 2


def test_screen_shows_the_switch_state_and_links_to_settings(client: Client, hr: User) -> None:
    link = reverse("admin:employees_companysettings_changelist")
    page = client.get(reverse("employees:slots")).content.decode()
    assert "Орон тоогоор хязгаарлах" in page and "Унтраалттай" in page and link in page
    row = CompanySettings.get()
    row.enforce_position_slots = True
    row.save()
    assert "Асаалттай" in client.get(reverse("employees:slots")).content.decode()


# ---- add / edit / delete ----


def test_add_opens_a_modal_and_creates_the_row(client: Client, hr: User, position: Position, branch: Branch) -> None:
    modal = client.get(reverse("employees:slot_add"))
    assert modal.status_code == 200 and "fixed inset-0" in modal.content.decode()
    response = client.post(reverse("employees:slot_add"), _form(position, branch))
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    row = NazgRow.objects.get()
    assert (row.position_id, row.branch_id, row.kind, row.year, row.qty) == (position.pk, branch.pk, "Main", YEAR, 2)
    entry = _logged("position_slot_added")
    assert len(entry) == 1 and entry[0].actor == hr and position.name in entry[0].message


def test_add_needs_position_branch_and_valid_values(
    client: Client, hr: User, position: Position, branch: Branch
) -> None:
    for bad in (
        {"position": ""},
        {"branch": ""},
        {"kind": "Other"},
        {"year": "abc"},
        {"year": "1500"},
        {"qty": "-1"},
        {"qty": ""},
    ):
        response = client.post(reverse("employees:slot_add"), _form(position, branch, **bad))
        assert response.status_code == 200, bad  # the modal again, with the error
    assert not NazgRow.objects.exists()
    assert not _logged("position_slot_added")


def test_zero_posts_is_allowed(client: Client, hr: User, position: Position, branch: Branch) -> None:
    assert client.post(reverse("employees:slot_add"), _form(position, branch, qty=0)).status_code == 204
    assert NazgRow.objects.get().qty == 0


def test_adding_an_existing_key_is_refused_and_points_to_edit(
    client: Client, hr: User, position: Position, branch: Branch
) -> None:
    _row(position, branch, 3)
    response = client.post(reverse("employees:slot_add"), _form(position, branch, qty=9))
    assert response.status_code == 200
    assert "засна уу" in response.content.decode() and position.name in response.content.decode()
    row = NazgRow.objects.get()  # still one row, unchanged
    assert row.qty == 3
    assert not _logged("position_slot_added")


def test_the_same_key_in_another_kind_or_year_is_a_new_row(
    client: Client, hr: User, position: Position, branch: Branch
) -> None:
    _row(position, branch, 3)
    assert client.post(reverse("employees:slot_add"), _form(position, branch, kind="Temporary")).status_code == 204
    assert client.post(reverse("employees:slot_add"), _form(position, branch, year=YEAR + 1)).status_code == 204
    assert NazgRow.objects.count() == 3


def test_service_refuses_a_duplicate_key(position: Position, branch: Branch, hr: User) -> None:
    _row(position, branch, 3)
    with pytest.raises(slots.SlotRowExists):
        slots.save_row(position=position, branch=branch, kind="Main", year=YEAR, qty=1, by=hr)
    assert NazgRow.objects.count() == 1


def test_edit_changes_the_row_and_logs(client: Client, hr: User, position: Position, branch: Branch) -> None:
    row = _row(position, branch, 3)
    url = reverse("employees:slot_edit", args=[row.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, _form(position, branch, qty=6))
    assert response.status_code == 204
    row.refresh_from_db()
    assert row.qty == 6
    entry = _logged("position_slot_changed")
    assert len(entry) == 1 and "3" in entry[0].message and "6" in entry[0].message


def test_edit_into_another_existing_key_is_refused(
    client: Client, hr: User, position: Position, branch: Branch
) -> None:
    _row(position, branch, 3)
    second = _row(position, branch, 1, kind="Temporary")
    response = client.post(reverse("employees:slot_edit", args=[second.pk]), _form(position, branch, kind="Main"))
    assert response.status_code == 200
    second.refresh_from_db()
    assert second.kind == "Temporary"


def test_edit_keeping_its_own_key_is_not_a_duplicate(
    client: Client, hr: User, position: Position, branch: Branch
) -> None:
    row = _row(position, branch, 3)
    assert client.post(reverse("employees:slot_edit", args=[row.pk]), _form(position, branch, qty=3)).status_code == 204


def test_edit_and_delete_of_a_missing_row_are_404(client: Client, hr: User) -> None:
    assert client.get(reverse("employees:slot_edit", args=[999999])).status_code == 404
    assert client.post(reverse("employees:slot_delete", args=[999999])).status_code == 404


def test_delete_removes_the_row_and_logs(client: Client, hr: User, position: Position, branch: Branch) -> None:
    row = _row(position, branch, 3)
    url = reverse("employees:slot_delete", args=[row.pk])
    assert client.get(url).status_code == 302  # delete is POST only; a GET goes back to the list
    assert NazgRow.objects.exists()
    response = client.post(url)
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert not NazgRow.objects.exists()
    assert len(_logged("position_slot_deleted")) == 1


def test_a_missing_database_grant_shows_a_message_not_a_500(
    client: Client, hr: User, position: Position, branch: Branch, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db.utils import ProgrammingError

    from employees.services import macs_writes

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ProgrammingError("permission denied for table nazg")

    row = _row(position, branch, 3)
    monkeypatch.setattr(macs_writes, "delete_slot_row", refuse)
    monkeypatch.setattr(macs_writes, "save_slot_row", refuse)
    deleted = client.post(reverse("employees:slot_delete", args=[row.pk]))
    assert deleted.status_code == 200 and "Өгөгдлийн сангийн эрх дутуу" in deleted.content.decode()
    added = client.post(reverse("employees:slot_add"), _form(position, branch, kind="Temporary"))
    assert added.status_code == 200 and "Өгөгдлийн сангийн эрх дутуу" in added.content.decode()
    edited = client.post(reverse("employees:slot_edit", args=[row.pk]), _form(position, branch, qty=9))
    assert edited.status_code == 200 and "Өгөгдлийн сангийн эрх дутуу" in edited.content.decode()
    assert NazgRow.objects.get().qty == 3
    assert not _logged("position_slot_deleted") and not _logged("position_slot_changed")


def test_edit_modal_has_a_confirmed_delete_button(client: Client, hr: User, position: Position, branch: Branch) -> None:
    row = _row(position, branch, 3)
    body = client.get(reverse("employees:slot_edit", args=[row.pk])).content.decode()
    assert reverse("employees:slot_delete", args=[row.pk]) in body and "hx-confirm" in body
    assert "hx-confirm" not in client.get(reverse("employees:slot_add")).content.decode()


# ---- permission ----


def test_others_get_403_and_nothing_changes(client: Client, position: Position, branch: Branch) -> None:
    row = _row(position, branch, 3)
    login_as(client, "Employee", "slot_plain")
    for name, args in (("slots", []), ("slot_add", []), ("slot_edit", [row.pk]), ("slot_delete", [row.pk])):
        url = reverse(f"employees:{name}", args=args)
        assert client.get(url).status_code == 403, name
        assert client.post(url, _form(position, branch, qty=99)).status_code == 403, name
    row.refresh_from_db()
    assert row.qty == 3 and NazgRow.objects.count() == 1


def test_anonymous_is_sent_to_login(client: Client) -> None:
    assert client.get(reverse("employees:slots")).status_code == 302


def test_the_right_alone_opens_the_screen(client: Client) -> None:
    from django.contrib.auth.models import Permission

    user = User.objects.create_user("slot_perm", password="x-long-pass-123")  # noqa: S106
    user.groups.clear()
    user.user_permissions.add(Permission.objects.get(codename="manage_position_slots"))
    client.force_login(user)
    assert client.get(reverse("employees:slots")).status_code == 200


# ---- nav and palette ----


def _settings_labels(user: User) -> list[str]:
    from accounts.nav import top_nav
    from django.test import RequestFactory
    from django.urls import resolve

    request = RequestFactory().get("/employees/")
    request.user = User.objects.get(pk=user.pk)
    request.resolver_match = resolve("/employees/")
    groups = {g.key: g for g in top_nav(request, False, {"show": False, "count": 0})}
    return [item.label for item in groups["settings"].items] if "settings" in groups else []


def test_nav_entry_only_with_the_permission(hr: User) -> None:
    assert "Орон тооны төлөвлөгөө" in _settings_labels(hr)
    plain = User.objects.create_user("slot_nav_plain", password="x-long-pass-123")  # noqa: S106
    plain.groups.set([Group.objects.get(name="Employee")])
    assert "Орон тооны төлөвлөгөө" not in _settings_labels(plain)


def test_palette_entry_only_with_the_permission(hr: User) -> None:
    titles = [s.title for s in palette.screens(User.objects.get(pk=hr.pk), "орон")]
    assert "Орон тооны төлөвлөгөө" in titles
    plain = User.objects.create_user("slot_pal_plain", password="x-long-pass-123")  # noqa: S106
    plain.groups.set([Group.objects.get(name="Employee")])
    assert "Орон тооны төлөвлөгөө" not in [s.title for s in palette.screens(User.objects.get(pk=plain.pk), "орон")]

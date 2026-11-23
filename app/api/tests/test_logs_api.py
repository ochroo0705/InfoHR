"""GET /api/v1/logs/employee: the employee log's batch as the React page reads it.

The rows, the filters, the paging and the rights come from logs.employee_query and logs.page_rules; these tests pin the
API's shape, its rights (403 without macs.view_employees, 401 without a login), the cleaned filters it echoes, and the
rule that a person the user may not see is dropped from the address and the chip.
"""

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
from accounts import roles
from accounts.audit import ACTIONS
from accounts.models import User
from config import batching
from django.test import Client
from django.utils import timezone
from employees.models import ActivityKind, Employee, HrOrder, OrderState, OrderType

from api.tests.logs_support import (  # noqa: F401
    FORBIDDEN,
    NOT_LOGGED_IN,
    _client,
    _entry,
    _system_entry,
    _user,
    admin,
    auditor,
    hr,
    job_values,
    other,
    own,
    scoped,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/logs/employee"
NO_NAME = "Систем"
KIND_NOTE_CLASS = "whitespace-nowrap rounded px-1.5 py-0.5 text-xs bg-sky-50 text-sky-700"
KIND_CHANGED_CLASS = "whitespace-nowrap rounded px-1.5 py-0.5 text-xs bg-slate-100 text-slate-600"


def _get(client: Client, *, url: str = URL, **params: Any) -> Any:
    response = client.get(url, params)
    assert response.status_code == 200, response.content.decode()
    return response.json()


def test_employee_log_row_shape(hr: User, own: Employee, other: Employee) -> None:  # noqa: F811
    changed = _entry(
        own,
        "Хаяг өөрчлөгдсөн",
        by=hr,
        changes=[
            {"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"},
            {"field": "Утас", "old": "", "new": ""},
        ],
    )
    note = _entry(own, "Эхний мөр\nХоёр мөр", kind=ActivityKind.NOTE, by=hr)
    by_system = _entry(own, "Системээс бичсэн", by=None)

    rows = {row["id"]: row for row in _get(_client(hr))["rows"]}

    local = timezone.localtime(changed.at)
    assert rows[changed.pk] == {
        "id": changed.pk,
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M"),
        "employee_id": own.pk,
        "employee_name": "Батын Сараа",
        "employee_code": own.code,
        "by_name": "Хүний Оюун",
        "kind": "changed",
        "kind_label": "Өөрчилсөн",
        "kind_class": KIND_CHANGED_CLASS,
        "is_note": False,
        "is_correction": False,
        "message": "Хаяг өөрчлөгдсөн",
        "changes": [
            {"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"},
            {"field": "Утас", "old": "", "new": "(хоосон)"},
        ],
        "order_id": None,
    }
    assert rows[note.pk]["is_note"] is True
    assert rows[note.pk]["kind_label"] == "Тэмдэглэл"
    assert rows[note.pk]["kind_class"] == KIND_NOTE_CLASS
    assert rows[note.pk]["message"] == "Эхний мөр\nХоёр мөр"
    assert rows[note.pk]["changes"] == []
    assert rows[by_system.pk]["by_name"] == NO_NAME


def test_employee_log_hides_entries_outside_scope(hr: User, scoped: tuple[Employee, Employee, User]) -> None:  # noqa: F811
    inside, outside, limited = scoped
    _entry(inside, "Дотны бичлэг", by=hr)
    _entry(outside, "Гадны бичлэг", by=hr)

    everyone = _get(_client(hr))
    assert "Гадна Мөнх" in [r["employee_name"] for r in everyone["rows"]]  # control

    body = _get(_client(limited))
    messages = [r["message"] for r in body["rows"]]
    assert "Дотны бичлэг" in messages
    assert "Гадны бичлэг" not in messages
    assert all("Гадна" not in r["employee_name"] for r in body["rows"])


def test_employee_log_hidden_person_chip_is_dropped(scoped: tuple[Employee, Employee, User]) -> None:  # noqa: F811
    inside, outside, limited = scoped

    control = _get(_client(limited), employee=str(inside.pk))
    assert control["chip"] == {"id": inside.pk, "name": "Дотно Оюун"}
    assert control["query"]["employee"] == inside.pk

    response = _client(limited).get(URL, {"employee": str(outside.pk)})
    assert response.status_code == 200
    assert "Гадна" not in response.content.decode()
    body = response.json()
    assert body["chip"] is None
    assert body["query"]["employee"] is None
    assert body["address"] == ""
    assert "Гадна Мөнх" not in [r["employee_name"] for r in body["rows"]]


def test_employee_log_echoes_clean_filters_and_drops_junk(hr: User, own: Employee) -> None:  # noqa: F811
    # Junk and duplicates count toward the 10-item cap, as in parse_filter: the list is cut to its first 10 before
    # it is cleaned, so the trailing "correction" is dropped and the repeated "note" is kept once.
    body = _get(
        _client(hr),
        kind=[
            "zzz",
            "note",
            "note",
            "changed",
            "history",
            "bogus",
            "created",
            "added",
            "deleted",
            "cancelled",
            "correction",
        ],
        area="bogus",
        field="",
        **{"from": "zzz"},
    )
    query = body["query"]
    assert query["kinds"] == ["note", "changed", "history", "created", "added", "deleted", "cancelled"]
    assert query["area"] == ""
    assert query["date_from"] == ""
    assert query["system"] is False
    assert query["oldest"] is False
    assert "zzz" not in body["address"]
    assert "bogus" not in body["address"]
    assert body["address"] == "kind=note&kind=changed&kind=history&kind=created&kind=added&kind=deleted&kind=cancelled"
    assert {o["value"] for o in body["options"]["kinds"]} == {kind.value for kind in ActivityKind}
    assert [o["value"] for o in body["options"]["areas"]] == ["salary", "personal", "orders", "notes"]
    assert body["tabs"]["employee"] is True
    assert body["tabs"]["system"] is False


def test_employee_log_from_and_to_filter_by_day(hr: User, own: Employee) -> None:  # noqa: F811
    # The URL names are "from" and "to": a valid pair echoes as ISO dates and keeps only the entries inside the range.
    dated = {
        "Диапазон өмнө": datetime(2026, 1, 3, 12, 0),
        "Диапазон эхлэл": datetime(2026, 1, 5, 12, 0),
        "Диапазон дунд": datetime(2026, 1, 7, 12, 0),
        "Диапазон хойно": datetime(2026, 1, 9, 12, 0),
    }
    for message, when in dated.items():
        # ActivityEntry is append-only, so the time is set at creation: auto_now_add reads timezone.now() then.
        with patch("django.utils.timezone.now", return_value=timezone.make_aware(when)):
            _entry(own, message, by=hr)

    body = _get(_client(hr), q="Диапазон", **{"from": "2026-01-05", "to": "2026-01-07"})

    assert body["query"]["date_from"] == "2026-01-05"
    assert body["query"]["date_to"] == "2026-01-07"
    messages = [r["message"] for r in body["rows"]]
    assert messages == ["Диапазон дунд", "Диапазон эхлэл"]  # newest first; the two outside the range are absent
    assert "Диапазон өмнө" not in messages
    assert "Диапазон хойно" not in messages


def test_employee_log_next_offset_none_on_last_batch_and_set_when_more(
    monkeypatch: pytest.MonkeyPatch,
    hr: User,  # noqa: F811
    own: Employee,  # noqa: F811
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    for i in range(8):
        _entry(own, f"Запис {i}")
    client = _client(hr)

    first = _get(client, q="Запис")
    assert len(first["rows"]) == 3
    assert first["next_offset"] == 3

    second = _get(client, q="Запис", offset="3")
    assert len(second["rows"]) == 3
    assert second["next_offset"] == 6

    last = _get(client, q="Запис", offset="6")
    assert len(last["rows"]) == 2
    assert last["next_offset"] is None


def test_employee_log_oldest_first_and_system_only(hr: User, own: Employee) -> None:  # noqa: F811
    _entry(own, "Эхний бичлэг", by=hr)
    _entry(own, "Сүүлийн бичлэг", by=None)
    client = _client(hr)

    newest = [r["message"] for r in _get(client, q="бичлэг")["rows"]]
    assert newest.index("Сүүлийн бичлэг") < newest.index("Эхний бичлэг")
    oldest_body = _get(client, q="бичлэг", oldest="1")
    oldest = [r["message"] for r in oldest_body["rows"]]
    assert oldest.index("Эхний бичлэг") < oldest.index("Сүүлийн бичлэг")
    assert oldest_body["query"]["oldest"] is True

    system_body = _get(client, q="бичлэг", system="1")
    assert [r["message"] for r in system_body["rows"]] == ["Сүүлийн бичлэг"]
    assert system_body["query"]["system"] is True
    assert system_body["rows"][0]["by_name"] == NO_NAME


def test_employee_log_order_id_set_only_for_order_entries(hr: User, own: Employee) -> None:  # noqa: F811
    order = HrOrder.objects.create(employee=own, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING)
    with_order = _entry(own, "Тушаалтай бичлэг", order=order)
    plain = _entry(own, "Энгийн бичлэг")

    rows = {row["id"]: row for row in _get(_client(hr), q="бичлэг")["rows"]}
    assert rows[with_order.pk]["order_id"] == order.pk
    assert rows[plain.pk]["order_id"] is None


def test_employee_log_response_is_not_cached(hr: User, own: Employee) -> None:  # noqa: F811
    response = _client(hr).get(URL)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


def test_employee_log_html_in_message_is_returned_as_text(hr: User, own: Employee) -> None:  # noqa: F811
    raw = '<script>alert(1)</script> & "quoted"'
    entry = _entry(own, raw)
    rows = {row["id"]: row for row in _get(_client(hr), q="alert")["rows"]}
    assert rows[entry.pk]["message"] == raw


SYSTEM_URL = "/api/v1/logs/system"
BOTH_URLS = pytest.mark.parametrize("url", [URL, SYSTEM_URL], ids=["employee", "system"])


@BOTH_URLS
def test_log_requires_login(db: None, url: str) -> None:
    response = Client().get(url)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


@BOTH_URLS
def test_log_403_without_perm(db: None, url: str) -> None:
    response = _client(_user("logs_api_nobody", None)).get(url)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


@BOTH_URLS
@pytest.mark.parametrize("bad", ["-5", "\u00b2", "9" * 20, "9" * 18, "123456789012345", "2147483648"])
def test_bad_or_huge_offset_starts_at_first_batch(url: str, bad: str, hr: User, own: Employee, auditor: User) -> None:  # noqa: F811
    for i in range(3):
        _entry(own, f"Офсет {i}")
        _system_entry(f"Офсет {i}")
    client = _client(_user("logs_api_both", roles.ADMIN))  # sees both logs
    first = _get(client, url=url, q="Офсет")
    assert len(first["rows"]) == 3

    response = client.get(url, {"q": "Офсет", "offset": bad})
    assert response.status_code == 200, bad
    assert response.json()["rows"] == first["rows"], bad
    assert response.json()["next_offset"] == first["next_offset"], bad


def test_system_log_response_is_not_cached(admin: User) -> None:  # noqa: F811
    response = _client(admin).get(SYSTEM_URL)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


def test_system_log_auditor_without_view_employees_gets_rows_and_tabs_system_only(auditor: User) -> None:  # noqa: F811
    _system_entry("Аудиторын бичлэг", ip="10.0.0.7")
    body = _get(_client(auditor), url=SYSTEM_URL, q="Аудиторын")
    assert [r["message"] for r in body["rows"]] == ["Аудиторын бичлэг"]
    assert body["tabs"] == {"employee": False, "system": True, "export": False}
    assert body["next_offset"] is None


def test_system_log_row_shape_and_unknown_codes_show_as_stored(auditor: User) -> None:  # noqa: F811
    known = _system_entry(
        "Шинэ бичлэг нэг",
        actor_name="logs_api_hr",
        category="hr",
        action="login",
        target_type="Ажилтан",
        target_label="Батын Сараа",
        changes=[
            {"field": "Цалин", "old": "100", "new": ""},
            {"field": "Хаяг", "old": "", "new": "Баянзүрх"},
        ],
        ip="10.0.0.7",
    )
    unknown = _system_entry("Шинэ бичлэг хоёр", category="zzz", action="unknown_code", actor_name="")

    rows = {row["id"]: row for row in _get(_client(auditor), url=SYSTEM_URL, q="Шинэ бичлэг")["rows"]}

    local = timezone.localtime(known.at)
    assert rows[known.pk] == {
        "id": known.pk,
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M"),
        "actor_name": "logs_api_hr",
        "category_label": "Ажилтан, HR",
        "action_label": "Нэвтэрсэн",
        "target_type": "Ажилтан",
        "target_label": "Батын Сараа",
        "message": "Шинэ бичлэг нэг",
        "changes": [
            {"field": "Цалин", "old": "100", "new": "(хоосон)"},
            {"field": "Хаяг", "old": "", "new": "Баянзүрх"},
        ],
        "ip": "10.0.0.7",
    }
    assert rows[unknown.pk]["actor_name"] == NO_NAME
    assert rows[unknown.pk]["category_label"] == "zzz"
    assert rows[unknown.pk]["action_label"] == "unknown_code"
    assert rows[unknown.pk]["ip"] == ""


def test_system_log_actor_name_survives_deleted_user(auditor: User) -> None:  # noqa: F811
    gone = _user("logs_api_gone", roles.HR)
    _system_entry("Устсан хэрэглэгчийн бичлэг", actor=gone, actor_name=gone.username)
    client = _client(auditor)
    gone.delete()

    body = _get(client, url=SYSTEM_URL, q="Устсан хэрэглэгчийн")
    assert [r["actor_name"] for r in body["rows"]] == ["logs_api_gone"]


def test_system_log_echoes_clean_filters(auditor: User) -> None:  # noqa: F811
    # Junk counts toward the 10-item cap of categories, as in parse_system_filter; a junk ip is dropped whole.
    body = _get(
        _client(auditor),
        url=SYSTEM_URL,
        category=["zzz", "hr", "hr", "access", "bogus", "settings"],
        action="bogus",
        ip="10.0.x",
        **{"from": "zzz"},
    )
    query = body["query"]
    assert query["categories"] == ["hr", "access", "settings"]
    assert query["action"] == ""
    assert query["ip"] == ""
    assert query["date_from"] == ""
    assert query["oldest"] is False
    assert body["address"] == "category=hr&category=access&category=settings"
    assert [o["value"] for o in body["options"]["categories"]] == ["access", "settings", "import", "export", "hr"]
    assert [(o["value"], o["label"]) for o in body["options"]["actions"]] == list(ACTIONS.items())


def test_system_log_paging(monkeypatch: pytest.MonkeyPatch, auditor: User) -> None:  # noqa: F811
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    for i in range(8):
        _system_entry(f"Систем журнал {i}")
    client = _client(auditor)

    first = _get(client, url=SYSTEM_URL, q="журнал")
    assert len(first["rows"]) == 3
    assert first["next_offset"] == 3
    second = _get(client, url=SYSTEM_URL, q="журнал", offset="3")
    assert len(second["rows"]) == 3
    assert second["next_offset"] == 6
    last = _get(client, url=SYSTEM_URL, q="журнал", offset="6")
    assert len(last["rows"]) == 2
    assert last["next_offset"] is None


def test_system_log_ip_prefix_and_exact_match(auditor: User) -> None:  # noqa: F811
    _system_entry("Ip нэг", ip="10.0.0.7")
    _system_entry("Ip хоёр", ip="10.0.0.70")
    _system_entry("Ip гурав", ip="10.1.2.3")
    _system_entry("Ip дөрөв", ip="192.168.1.5")
    client = _client(auditor)

    exact = {r["message"] for r in _get(client, url=SYSTEM_URL, q="Ip", ip="10.0.0.7")["rows"]}
    assert exact == {"Ip нэг"}  # a full address matches exactly, not as a prefix of 10.0.0.70

    prefix = {r["message"] for r in _get(client, url=SYSTEM_URL, q="Ip", ip="10.")["rows"]}
    assert prefix == {"Ip нэг", "Ip хоёр", "Ip гурав"}

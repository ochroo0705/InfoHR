import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from pytest_django.fixtures import SettingsWrapper

from welcome import service
from welcome.models import DemoRequest

pytestmark = pytest.mark.django_db

PATH = "/api/v1/welcome/demo-requests"
RATE_LIMITED = "Хэт олон хүсэлт илгээлээ. Түр хүлээгээд дахин оролдоно уу."
BAD_CHARS = "Хүчингүй тэмдэгт байна."
SERVER_ERROR = "Алдаа гарлаа. Дахин оролдоно уу."
TOO_LARGE = "Хүсэлт хэт том байна."
PUBLIC_IP = "8.8.8.8"  # globally routable (203.0.113.x is a documentation range that Python calls private)
PRIVATE_IP = "10.0.0.1"


def _body(**overrides: str) -> dict[str, str]:
    body = {
        "name": "Б. Саруул",
        "email": "visitor@example.mn",
        "organisation": "Тест ХХК",
        "phone": "99112233",
        "size_band": "11-50",
        "note": "Сонирхож байна",
        "contact_ref": "",
    }
    body.update(overrides)
    return body


def _post(client: Client, body: dict[str, Any], ip: str = PRIVATE_IP) -> Any:
    return client.post(PATH, data=json.dumps(body), content_type="application/json", REMOTE_ADDR=ip)


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def mail_off(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = ""
    settings.DEMO_REQUEST_NOTIFY = []


def test_valid_post_saves_trimmed_values(client: Client, mail_off: None) -> None:
    response = _post(client, _body(name="  Б. Саруул  ", organisation=" Тест ХХК "))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    row = DemoRequest.objects.get()
    assert row.name == "Б. Саруул"
    assert row.organisation == "Тест ХХК"
    assert row.ip == PRIVATE_IP


def test_honeypot_filled_answers_ok_and_saves_nothing(client: Client, mail_off: None) -> None:
    response = _post(client, _body(contact_ref="http://spam.example"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert DemoRequest.objects.count() == 0


def test_honeypot_hits_do_not_consume_the_per_ip_limit(client: Client, mail_off: None) -> None:
    for _ in range(15):
        assert _post(client, _body(contact_ref="http://spam.example"), ip=PUBLIC_IP).status_code == 200

    response = _post(client, _body(), ip=PUBLIC_IP)

    assert response.status_code == 200
    assert DemoRequest.objects.count() == 1


def test_blank_name_is_refused(client: Client, mail_off: None) -> None:
    response = _post(client, _body(name="   "))

    assert response.status_code == 400
    assert response.json()["field_errors"]["name"] == ["Заавал бөглөнө үү."]
    assert DemoRequest.objects.count() == 0


def test_missing_name_key_is_a_field_error(client: Client, mail_off: None) -> None:
    body = _body()
    del body["name"]

    response = _post(client, body)

    assert response.status_code == 400
    assert response.json()["field_errors"]["name"] == ["Заавал бөглөнө үү."]


def test_invalid_email_is_refused_and_saves_no_row(client: Client, mail_off: None) -> None:
    response = _post(client, _body(email="nope"))

    assert response.status_code == 400
    assert response.json()["field_errors"]["email"] == ["Имэйл хаяг буруу байна."]
    assert DemoRequest.objects.count() == 0


def test_note_over_2000_characters_is_refused(client: Client, mail_off: None) -> None:
    response = _post(client, _body(note="а" * 2001))

    assert response.status_code == 400
    assert response.json()["field_errors"]["note"] == ["Хэт урт байна."]


def test_note_of_2000_characters_is_accepted(client: Client, mail_off: None) -> None:
    response = _post(client, _body(note="а" * 2000))

    assert response.status_code == 200


def test_name_over_120_characters_is_refused(client: Client, mail_off: None) -> None:
    response = _post(client, _body(name="а" * 121))

    assert response.status_code == 400
    assert response.json()["field_errors"]["name"] == ["Хэт урт байна."]


def test_phone_over_40_characters_is_refused(client: Client, mail_off: None) -> None:
    response = _post(client, _body(phone="1" * 41))

    assert response.status_code == 400
    assert response.json()["field_errors"]["phone"] == ["Хэт урт байна."]


def test_unknown_size_band_is_refused(client: Client, mail_off: None) -> None:
    response = _post(client, _body(size_band="999"))

    assert response.status_code == 400
    assert response.json()["field_errors"]["size_band"] == ["Сонголт буруу байна."]


def test_organisation_keeps_unicode_and_emoji(client: Client, mail_off: None) -> None:
    organisation = "Өндөр Ү ХХК 🚀"

    response = _post(client, _body(organisation=organisation))

    assert response.status_code == 200
    assert DemoRequest.objects.get().organisation == organisation


def test_unicode_and_emoji_in_name_round_trip(client: Client, mail_off: None) -> None:
    name = "Өлзий Ү 🙂"

    response = _post(client, _body(name=name))

    assert response.status_code == 200
    assert DemoRequest.objects.get().name == name


def test_nul_character_in_name_is_a_field_error(client: Client, mail_off: None) -> None:
    response = _post(client, _body(name="Б\x00. Саруул"))

    assert response.status_code == 400
    assert response.json()["field_errors"]["name"] == [BAD_CHARS]
    assert DemoRequest.objects.count() == 0


def test_lone_surrogate_in_note_is_a_field_error(client: Client, mail_off: None) -> None:
    response = _post(client, _body(note="\ud800"))

    assert response.status_code == 400
    assert response.json()["field_errors"]["note"] == [BAD_CHARS]
    assert DemoRequest.objects.count() == 0


def test_per_ip_limit_applies_to_a_public_address(client: Client, mail_off: None) -> None:
    for _ in range(10):
        assert _post(client, _body(), ip=PUBLIC_IP).status_code == 200

    response = _post(client, _body(), ip=PUBLIC_IP)

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "rate_limited"
    assert body["form_errors"] == [RATE_LIMITED]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "100.64.1.2", ""])
def test_non_public_addresses_are_not_per_ip_throttled(client: Client, mail_off: None, ip: str) -> None:
    for _ in range(12):
        assert _post(client, _body(), ip=ip).status_code == 200


def test_invalid_posts_from_loopback_never_lock_out_a_visitor(client: Client, mail_off: None) -> None:
    for _ in range(10):
        assert _post(client, _body(email="nope"), ip="127.0.0.1").status_code == 400

    assert _post(client, _body(), ip="127.0.0.1").status_code == 200


def test_store_cap_answers_429_and_invalid_posts_do_not_use_it(
    client: Client, mail_off: None, settings: SettingsWrapper
) -> None:
    settings.WELCOME_STORE_CAP = 3
    for index in range(5):
        assert _post(client, _body(email="nope"), ip=f"10.2.0.{index + 1}").status_code == 400
    for index in range(3):
        assert _post(client, _body(), ip=f"10.3.0.{index + 1}").status_code == 200

    response = _post(client, _body(), ip="10.4.0.1")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert DemoRequest.objects.count() == 3


def test_mail_budget_stores_but_does_not_mail_when_used_up(client: Client, settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]
    settings.WELCOME_MAIL_BUDGET = 2

    statuses = [_post(client, _body(), ip=f"10.5.0.{index + 1}").status_code for index in range(3)]

    assert statuses == [200, 200, 200]
    assert len(mail.outbox) == 2
    last = DemoRequest.objects.order_by("-pk").first()
    assert last is not None
    assert last.mail_status == "failed"
    assert last.mail_error == "mail budget used"


def test_mail_failure_keeps_ok_answer(
    client: Client, settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(service, "send_mail", boom)

    response = _post(client, _body())

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert DemoRequest.objects.get().mail_status == "failed"


def test_unexpected_store_failure_answers_generic_500(
    client: Client, mail_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret stack detail")

    monkeypatch.setattr(service, "create_request", boom)

    response = _post(client, _body())

    assert response.status_code == 500
    assert response.json() == {"field_errors": {}, "form_errors": [SERVER_ERROR], "code": "server_error"}
    assert b"secret" not in response.content


def test_oversized_body_is_refused_and_uses_no_bucket(
    client: Client, mail_off: None, settings: SettingsWrapper
) -> None:
    settings.WELCOME_STORE_CAP = 1
    response = _post(client, _body(note="а" * 20000), ip=PUBLIC_IP)

    assert response.status_code == 413
    assert response.json() == {"field_errors": {}, "form_errors": [TOO_LARGE], "code": "too_large"}
    assert DemoRequest.objects.count() == 0
    assert _post(client, _body(), ip=PUBLIC_IP).status_code == 200


def test_anonymous_post_needs_no_login_and_no_csrf_token(mail_off: None) -> None:
    client = Client(enforce_csrf_checks=True)

    response = _post(client, _body())

    assert response.status_code == 200

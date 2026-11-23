"""POST /api/v1/welcome/demo-requests: the demo-request form on the public welcome page (app/welcome).

Anonymous on purpose (auth=None). Checks run in this order:
1. body over BODY_MAX bytes -> 413, nothing counted;
2. a filled honeypot (contact_ref) answers ok and stores nothing;
3. the per-IP throttle, only for a publicly routable address (behind the front server every visitor may show the same
   address, so private, loopback, CGNAT and missing addresses are not throttled per IP);
4. field checks (a refused request never uses the store cap or the mail budget);
5. the store cap: at most WELCOME_STORE_CAP stored requests per window, shared by everyone;
6. the mail budget: at most WELCOME_MAIL_BUDGET mails per window; beyond it the request is still stored, not mailed;
then service.create_request. Any failure while storing answers a generic 500 without detail.

Mounted only when the welcome app is installed (api/main.py).
"""

import ipaddress
import logging

from accounts.middleware import client_ip
from api.errors import ApiError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.http import HttpRequest
from employees.selfform import throttle
from ninja import Router, Schema

from welcome import service
from welcome.models import SIZE_BAND_CHOICES

logger = logging.getLogger(__name__)

welcome_router = Router(tags=["welcome"])

WINDOW_SECONDS = 3600
BODY_MAX = 16_000  # bytes of request body; a demo request is a few kilobytes at most
NAME_MAX = 120
ORGANISATION_MAX = 200
PHONE_MAX = 40
NOTE_MAX = 2000
EMAIL_MAX = 254  # the DemoRequest.email column length

THROTTLE_BUCKET = "demo-request"
STORE_BUCKET = "demo-request-global"
MAIL_BUCKET = "demo-request-mail"

RATE_LIMITED = "Хэт олон хүсэлт илгээлээ. Түр хүлээгээд дахин оролдоно уу."
REQUIRED = "Заавал бөглөнө үү."
INVALID_EMAIL = "Имэйл хаяг буруу байна."
TOO_LONG = "Хэт урт байна."
BAD_CHOICE = "Сонголт буруу байна."
BAD_CHARS = "Хүчингүй тэмдэгт байна."
SERVER_ERROR = "Алдаа гарлаа. Дахин оролдоно уу."
TOO_LARGE = "Хүсэлт хэт том байна."

TEXT_FIELDS = ("name", "email", "organisation", "phone", "size_band", "note")

SIZE_BAND_VALUES = {value for value, _label in SIZE_BAND_CHOICES}


class DemoRequestIn(Schema):
    name: str = ""  # a missing key gets the same field message as a blank one
    email: str = ""
    organisation: str = ""
    phone: str = ""
    size_band: str = ""
    note: str = ""
    contact_ref: str = ""  # honeypot: real visitors never see or fill it


class DemoRequestOut(Schema):
    ok: bool


def _per_ip_applies(ip: str | None) -> bool:
    """Only a publicly routable address identifies a visitor; loopback, private, CGNAT and missing ones do not."""
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _clean_text(value: str) -> bool:
    """False for a NUL character or text that cannot be encoded as UTF-8 (a lone surrogate)."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _field_errors(payload: DemoRequestIn) -> dict[str, list[str]]:
    bad = [field for field in TEXT_FIELDS if not _clean_text(getattr(payload, field))]
    if bad:
        return {field: [BAD_CHARS] for field in bad}

    errors: dict[str, list[str]] = {}

    def add(field: str, message: str) -> None:
        errors.setdefault(field, []).append(message)

    name = payload.name.strip()
    organisation = payload.organisation.strip()
    email = payload.email.strip()
    phone = payload.phone.strip()
    note = payload.note.strip()
    size_band = payload.size_band.strip()

    for field, value in (("name", name), ("organisation", organisation), ("email", email)):
        if not value:
            add(field, REQUIRED)
    if len(name) > NAME_MAX:
        add("name", TOO_LONG)
    if len(organisation) > ORGANISATION_MAX:
        add("organisation", TOO_LONG)
    if email:
        if len(email) > EMAIL_MAX:
            add("email", TOO_LONG)
        else:
            try:
                validate_email(email)
            except DjangoValidationError:
                add("email", INVALID_EMAIL)
    if len(phone) > PHONE_MAX:
        add("phone", TOO_LONG)
    if len(note) > NOTE_MAX:
        add("note", TOO_LONG)
    if size_band and size_band not in SIZE_BAND_VALUES:
        add("size_band", BAD_CHOICE)
    return errors


@welcome_router.post("/demo-requests", auth=None, response=DemoRequestOut)
def create_demo_request(request: HttpRequest, payload: DemoRequestIn) -> dict[str, bool]:
    if len(request.body) > BODY_MAX:
        raise ApiError(413, [TOO_LARGE], code="too_large")

    if payload.contact_ref.strip():
        return {"ok": True}  # a bot filled the honeypot: pretend success, store nothing

    ip = client_ip(request)
    if _per_ip_applies(ip) and not throttle.allow(
        ip, THROTTLE_BUCKET, limit=settings.WELCOME_PER_IP_LIMIT, window_seconds=WINDOW_SECONDS
    ):
        raise ApiError(429, [RATE_LIMITED], code="rate_limited")

    errors = _field_errors(payload)
    if errors:
        raise ApiError(400, [], errors)

    # Counted last: refused requests never use up the store cap that every visitor shares.
    if not throttle.allow(None, STORE_BUCKET, limit=settings.WELCOME_STORE_CAP, window_seconds=WINDOW_SECONDS):
        raise ApiError(429, [RATE_LIMITED], code="rate_limited")

    notify = throttle.allow(None, MAIL_BUCKET, limit=settings.WELCOME_MAIL_BUDGET, window_seconds=WINDOW_SECONDS)
    try:
        service.create_request(
            name=payload.name,
            email=payload.email,
            organisation=payload.organisation,
            phone=payload.phone,
            size_band=payload.size_band,
            note=payload.note,
            ip=ip,
            notify=notify,
        )
    except Exception:
        # No detail in the response or the log: the exception text may hold visitor data.
        logger.error("welcome demo request could not be stored")
        raise ApiError(500, [SERVER_ERROR], code="server_error") from None
    return {"ok": True}

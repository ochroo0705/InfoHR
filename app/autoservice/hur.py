"""HUR: the MACS state vehicle registry, asked for a plate (Улсын дугаараар машины мэдээлэл татах).

Same protocol as the carcare.mn client (lib/hur_service.ts): POST `login` {username, password} -> a bearer token,
POST `getVehicleInfo` {code, number} with it -> {return: {response, resultCode, resultMessage}}.
Settings: HUR_URL, HUR_USERNAME, HUR_PASSWORD, HUR_CODE (config/settings.py, from .env). The token is kept in memory
until a minute before it expires, and renewed once if HUR answers 401.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from django.conf import settings

TIMEOUT = 10  # HUR can hang: never wait without a limit
_lock = threading.Lock()
_token: tuple[str, float] | None = None  # (token, expires at)


class HurError(Exception):
    """HUR could not answer; the message is for the user. `status` is the HTTP status the API should give."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(settings.HUR_USERNAME and settings.HUR_PASSWORD and settings.HUR_CODE)


def _post(path: str, payload: dict[str, Any], token: str = "") -> Any:
    request = urllib.request.Request(  # noqa: S310 - the URL is the HUR setting, https
        urljoin(settings.HUR_URL, path),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        raise HurError(f"ХУР {path} алдаа: {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise HurError("ХУР-тай холбогдож чадсангүй. Дараа дахин оролдоно уу.") from e


def _login(force: bool = False) -> str:
    global _token
    with _lock:
        if not force and _token and _token[1] - time.time() > 60:
            return _token[0]
        data = _post("login", {"username": settings.HUR_USERNAME, "password": settings.HUR_PASSWORD})
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise HurError("ХУР нэвтрэх токен буцаасангүй.")
        expires_in = data.get("expiresIn")
        _token = (token, time.time() + (expires_in if isinstance(expires_in, (int, float)) else 3600))
        return str(token)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and "NO ACCESS" not in value else None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value) if isinstance(value, str) and value.strip() else None
    except ValueError:
        return None


def parse(raw: Any, plate: str) -> dict[str, Any]:
    """HUR's answer as the fields the screen wants. Owner data is None when HUR hides it."""
    if not isinstance(raw, dict):
        raise HurError("ХУР-аас буруу хариу ирлээ.")
    block = raw.get("return", raw)
    if not isinstance(block, dict):
        raise HurError("ХУР-аас буруу хариу ирлээ.")
    code = block.get("resultCode")
    if isinstance(code, (int, float)) and code != 0:
        message = str(block.get("resultMessage") or "ХУР алдаа")
        raise HurError(message.replace("төв -с", "төвөөс"), status=404)
    r = block.get("response") or raw
    if not isinstance(r, dict):
        raise HurError("ХУР-аас буруу хариу ирлээ.")
    raw_address = r.get("ownerAddress")
    address: dict[str, Any] = raw_address if isinstance(raw_address, dict) else {}
    owner = {
        "first_name": _text(r.get("ownerFirstname")),
        "last_name": _text(r.get("ownerLastname")),
        "phone": _text(r.get("ownerHandphone")),
        "register": _text(r.get("ownerRegnum")),
        "type": _text(r.get("ownerType")),
        "address": ", ".join(x for x in (_text(address.get("state")), _text(address.get("soum"))) if x) or None,
    }
    year = _number(r.get("buildYear"))
    return {
        "plate": _text(r.get("plateNumber")) or plate,
        "make": _text(r.get("markName")),
        "model": _text(r.get("modelName")),
        "year": int(year) if year else None,
        "vin": _text(r.get("cabinNumber")),
        "color": _text(r.get("colorName")),
        "country": _text(r.get("countryName")),
        "fuel_type": _text(r.get("fueltype")),
        "capacity": _number(r.get("capacity")),
        "class_name": _text(r.get("className")),
        "purpose": _text(r.get("purpose")),
        "owner": owner if any(owner.values()) else None,
    }


def vehicle(plate: str) -> dict[str, Any]:
    """The registry's record of a plate. Raises HurError (status 404 = HUR does not know it, 503 = lookup is off)."""
    number = plate.strip().upper()
    if not number:
        raise HurError("Улсын дугаар хоосон байна.", status=400)
    if not configured():
        raise HurError("ХУР-ын лавлагаа тохируулаагүй байна (HUR_USERNAME, HUR_PASSWORD, HUR_CODE).", status=503)
    payload = {"code": settings.HUR_CODE, "number": number}
    try:
        raw = _post("getVehicleInfo", payload, _login())
    except HurError as e:
        if "401" not in str(e):
            raise
        raw = _post("getVehicleInfo", payload, _login(force=True))  # the token may have expired: once more
    return parse(raw, number)

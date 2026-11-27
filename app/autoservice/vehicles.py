# ruff: noqa: S608 - SQL pieces are constants or ints; every user value goes in as a parameter
"""Vehicle owners (Автомашин эзэмшигчид): CARS, one row per plate.

CARS.CAR_IDENT is the mark (CAR_REF, required), REQCUST_IDENT an optional organisation (CUSTOMER), REQCUST_NAME and
REQCUST_PHONE the person. CAR_NO is unique. Quotes and repair cards point at CARS through CAROWNER_IDENT; the quote
link is ON DELETE CASCADE, so a car with quotes or cards is never deleted here (it would take the quotes with it).
"""

from typing import Any

from django.db import connection

from autoservice.views import clean

# column length limits of CARS
LIMITS = {
    "plate": 32,
    "body_no": 60,
    "motor_type": 40,
    "color": 240,
    "vin": 120,
    "engine": 120,
    "phone": 120,
    "tx_cert": 120,
    "license_no": 120,
    "purpose": 120,
    "owner": 320,
}
LABELS = {
    "plate": "Улсын дугаар",
    "body_no": "Кузовын дугаар",
    "motor_type": "Моторын төрөл",
    "color": "Өнгө",
    "vin": "Арлын дугаар",
    "engine": "Хөдөлгүүрийн дугаар",
    "phone": "Холбоо барих",
    "tx_cert": "ТХ гэрчилгээ",
    "license_no": "Жолооны үнэмлэх",
    "purpose": "Зориулалт",
    "owner": "Эзэмшигчийн нэр",
}
COLUMN = {
    "plate": "CAR_NO",
    "body_no": "KUZOV_NO",
    "motor_type": "ENGINE_TYPE",
    "color": "CAR_COLOR",
    "vin": "VIN_NUMBER",
    "engine": "ENGINE_NUMBER",
    "phone": "REQCUST_PHONE",
    "tx_cert": "CERTIFICATE",
    "license_no": "DRIVER_NO",
    "purpose": "SPECIFICATION",
    "owner": "REQCUST_NAME",
}


class VehicleError(ValueError):
    """The request cannot be saved; the message is shown to the user."""


class VehicleInUse(VehicleError):
    """The vehicle has quotes or repair cards."""


def parse(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, limit in LIMITS.items():
        value = str(body.get(key) or "").strip()
        if len(value) > limit:
            raise VehicleError(f"{LABELS[key]} хэт урт байна ({limit} тэмдэгтээс ихгүй).")
        out[key] = value
    out["plate"] = out["plate"].upper()
    if not out["plate"]:
        raise VehicleError("Улсын дугаар заавал бөглөнө.")
    try:
        out["mark_id"] = int(body.get("mark_id") or 0)
        out["org_id"] = int(body.get("org_id") or 0) or None
        year = body.get("year")
        out["year"] = int(year) if year else None
    except (TypeError, ValueError):
        raise VehicleError("Марк, байгууллага, он тоон утгатай байх ёстой.") from None
    # A mark the registry (ХУР) named that our list does not have yet: created on save (see resolve_mark).
    raw = body.get("new_mark")
    new_mark = raw if isinstance(raw, dict) else {}
    out["new_mark"] = {k: str(new_mark.get(k) or "").strip() for k in ("make", "model", "class_name")}
    if out["mark_id"] <= 0 and not (out["new_mark"]["model"] or out["new_mark"]["make"]):
        raise VehicleError("Марк сонгоно уу.")
    if out["year"] is not None and not 1900 <= out["year"] <= 2100:
        raise VehicleError("Үйлдвэрлэсэн он буруу байна.")
    return out


MARK_LIMIT = 120  # CAR_REF.DESCRIPTION and MANUF_REF.DESCRIPTION


def _car_type(c: Any, hint: str) -> int:
    """CAR_TYPE for a registry class / purpose text: cargo, jeep, else passenger (the desktop's three types)."""
    c.execute("SELECT CARTYPE_ID, DESCRIPTION FROM CAR_TYPE ORDER BY CARTYPE_ID")
    types = [(r[0], (clean(r[1]) or "").lower()) for r in c.fetchall()]
    if not types:
        raise VehicleError("Машины төрөл (CAR_TYPE) бүртгэлгүй байна.")
    text = hint.lower()
    for words, stem in ((("ачаа", "тээвэр"), "ачаа"), (("жип", "джип", "jeep"), "жип")):
        if any(w in text for w in words):
            for type_id, name in types:
                if stem in name:
                    return int(type_id)
    for type_id, name in types:
        if "суудл" in name:
            return int(type_id)
    return int(types[0][0])


def _manufacturer(c: Any, make: str) -> int:
    """MANUF_REF id of a make (case-insensitive); created when we do not have it."""
    c.execute("SELECT MANUF_ID FROM MANUF_REF WHERE UPPER(TRIM(DESCRIPTION)) = %s", [make.upper()])
    row = c.fetchone()
    if row:
        return int(row[0])
    name = make.capitalize() if make.isupper() and len(make) > 3 else make  # "TOYOTA" -> "Toyota", "BMW" stays
    c.execute("SELECT GEN_ID(GEN_MANUF_REF_ID, 1) FROM RDB$DATABASE")
    pk = int(c.fetchone()[0])
    c.execute("INSERT INTO MANUF_REF (MANUF_ID, DESCRIPTION) VALUES (%s, %s)", [pk, name])
    return pk


def resolve_mark(c: Any, d: dict[str, Any]) -> None:
    """Sets d["mark_id"]. A mark the registry named that CAR_REF lacks is created (with its manufacturer if needed).

    d["mark_created"] tells the caller whether a row was added. Nothing happens when a mark was picked from the list.
    """
    d["mark_created"] = False
    if d["mark_id"] > 0:
        return
    make, model = d["new_mark"]["make"], d["new_mark"]["model"]
    name = (model or make)[:MARK_LIMIT]
    c.execute("SELECT CAR_ID FROM CAR_REF WHERE UPPER(TRIM(DESCRIPTION)) = %s", [name.upper()])
    row = c.fetchone()  # the name is unique in CAR_REF: reuse it
    if row:
        d["mark_id"] = int(row[0])
        return
    if len(make) > MARK_LIMIT:
        raise VehicleError(f"Үйлдвэрлэгчийн нэр хэт урт байна ({MARK_LIMIT} тэмдэгтээс ихгүй).")
    manufacturer = _manufacturer(c, make or name)
    car_type = _car_type(c, d["new_mark"]["class_name"])
    c.execute("SELECT GEN_ID(GEN_CAR_REF_ID, 1) FROM RDB$DATABASE")
    pk = int(c.fetchone()[0])
    c.execute(
        "INSERT INTO CAR_REF (CAR_ID, DESCRIPTION, MANUF_IDENT, CARTYPE_IDENT) VALUES (%s, %s, %s, %s)",
        [pk, name, manufacturer, car_type],
    )
    d["mark_id"] = pk
    d["mark_created"] = True


SELECT = (
    "c.CARS_ID, c.CAR_NO, c.CAR_IDENT, r.DESCRIPTION, t.DESCRIPTION, c.ENGINE_TYPE, c.CAR_COLOR, c.VIN_NUMBER, "
    "c.KUZOV_NO, c.ENGINE_NUMBER, c.MAKE_YEAR, c.CERTIFICATE, c.DRIVER_NO, c.SPECIFICATION, c.REQCUST_NAME, "
    "c.REQCUST_PHONE, c.REQCUST_IDENT, u.DESCRIPTION"
)
FROM = (
    "FROM CARS c LEFT JOIN CAR_REF r ON r.CAR_ID = c.CAR_IDENT LEFT JOIN CAR_TYPE t ON t.CARTYPE_ID = r.CARTYPE_IDENT "
    "LEFT JOIN CUSTOMER u ON u.CUST_ID = c.REQCUST_IDENT"
)
KEYS = (
    "id plate mark_id mark kind motor_type color vin body_no engine year tx_cert license_no purpose owner phone "
    "org_id org"
).split()


def _row(r: tuple[Any, ...]) -> dict[str, Any]:
    d = {k: clean(v) for k, v in zip(KEYS, r, strict=True)}
    return {k: ("" if v is None and k not in ("id", "mark_id", "org_id", "year") else v) for k, v in d.items()}


def listing(q: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, params = "", []
    if q:
        where = (
            "WHERE UPPER(c.CAR_NO) LIKE %s OR UPPER(c.REQCUST_NAME) LIKE %s OR UPPER(c.VIN_NUMBER) LIKE %s "
            "OR c.REQCUST_PHONE LIKE %s OR UPPER(u.DESCRIPTION) LIKE %s"
        )
        like = f"%{q.upper()}%"
        params = [like, like, like, f"%{q}%", like]
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) {FROM} {where}", params)
        total = c.fetchone()[0]
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {SELECT} {FROM} {where} ORDER BY c.CAR_NO",
            params,
        )
        return [_row(r) for r in c.fetchall()], total


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(f"SELECT {SELECT} {FROM} WHERE c.CARS_ID = %s", [pk])
        row = c.fetchone()
    return None if row is None else _row(row)


def _values(d: dict[str, Any]) -> list[Any]:
    return [
        d["plate"], d["mark_id"], d["motor_type"] or None, d["color"] or None, d["vin"] or None, d["body_no"] or None,
        d["engine"] or None, d["year"], d["tx_cert"] or None, d["license_no"] or None, d["purpose"] or None,
        d["owner"] or None, d["phone"], d["org_id"],
    ]  # fmt: skip


def _check_plate(c: Any, plate: str, own: int | None) -> None:
    c.execute("SELECT CARS_ID FROM CARS WHERE UPPER(CAR_NO) = %s", [plate])
    other = c.fetchone()
    if other and other[0] != own:
        raise VehicleError("Энэ улсын дугаартай машин бүртгэлтэй байна.")


def create(d: dict[str, Any]) -> int:
    with connection.cursor() as c:
        _check_plate(c, d["plate"], None)
        resolve_mark(c, d)
        c.execute("SELECT GEN_ID(GEN_CARS_ID, 1) FROM RDB$DATABASE")
        pk = int(c.fetchone()[0])
        c.execute(
            "INSERT INTO CARS (CARS_ID, CAR_NO, CAR_IDENT, ENGINE_TYPE, CAR_COLOR, VIN_NUMBER, KUZOV_NO, "
            "ENGINE_NUMBER, MAKE_YEAR, CERTIFICATE, DRIVER_NO, SPECIFICATION, REQCUST_NAME, REQCUST_PHONE, "
            "REQCUST_IDENT, CARS_TYPE) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            [pk, *_values(d)],
        )
    return pk


def replace(pk: int, d: dict[str, Any]) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM CARS WHERE CARS_ID = %s", [pk])
        if c.fetchone() is None:
            return False
        _check_plate(c, d["plate"], pk)
        resolve_mark(c, d)
        c.execute(
            "UPDATE CARS SET CAR_NO = %s, CAR_IDENT = %s, ENGINE_TYPE = %s, CAR_COLOR = %s, VIN_NUMBER = %s, "
            "KUZOV_NO = %s, ENGINE_NUMBER = %s, MAKE_YEAR = %s, CERTIFICATE = %s, DRIVER_NO = %s, SPECIFICATION = %s, "
            "REQCUST_NAME = %s, REQCUST_PHONE = %s, REQCUST_IDENT = %s WHERE CARS_ID = %s",
            [*_values(d), pk],
        )
    return True


def delete(pk: int) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM PRICE_VOTE WHERE CAROWNER_IDENT = %s", [pk])
        quotes = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM SERVCARDS WHERE CAROWNER_IDENT = %s", [pk])
        cards = c.fetchone()[0]
        if quotes or cards:
            raise VehicleInUse(
                f"Энэ машинд {quotes} үнийн санал, {cards} засварын карт холбогдсон тул устгах боломжгүй."
            )
        c.execute("DELETE FROM CARS WHERE CARS_ID = %s", [pk])
        return bool(c.rowcount)


def find_by_plate(plate: str) -> int | None:
    """The id of the vehicle already registered under this plate, if any."""
    with connection.cursor() as c:
        c.execute("SELECT CARS_ID FROM CARS WHERE UPPER(CAR_NO) = %s", [plate.strip().upper()])
        row = c.fetchone()
    return int(row[0]) if row else None


def match_hur(info: dict[str, Any]) -> dict[str, Any]:
    """What a registry answer means for our lists: the CAR_REF mark and CUSTOMER organisation it most likely names."""
    out: dict[str, Any] = {"mark": None, "new_mark": None, "org": None}
    names = [n for n in (info.get("model"), f"{info.get('make') or ''} {info.get('model') or ''}".strip()) if n]
    with connection.cursor() as c:
        for name in names:
            c.execute("SELECT CAR_ID, DESCRIPTION FROM CAR_REF WHERE UPPER(TRIM(DESCRIPTION)) = %s", [name.upper()])
            row = c.fetchone()
            if row:
                out["mark"] = {"id": row[0], "name": clean(row[1])}
                break
        if out["mark"] is None and (info.get("model") or info.get("make")):
            # Not in our list: the screen sends this back on save and the mark is created then (resolve_mark).
            out["new_mark"] = {
                "make": info.get("make") or "",
                "model": info.get("model") or "",
                "class_name": info.get("class_name") or info.get("purpose") or "",
                "name": info.get("model") or info.get("make"),
            }
        register = (info.get("owner") or {}).get("register")
        if register and register.isdigit():  # 7 digits: an organisation (carcare.mn ownerKindFromRegnum)
            c.execute("SELECT FIRST 1 CUST_ID, DESCRIPTION FROM CUSTOMER WHERE REGISTER = %s", [register])
            row = c.fetchone()
            if row:
                out["org"] = {"id": row[0], "name": clean(row[1])}
    return out

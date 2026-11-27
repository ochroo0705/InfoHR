"""Quotes (үнийн санал) in MACS: PRICE_VOTE (header) with PRICEVOTEJOB (works) and PRICEVOTEITEM (parts).

Read and written with plain SQL like the rest of this app. The database does little for us: triggers only fill
the id from a generator when it is NULL and, on delete, remove the lines. Totals, VAT and numbering are ours
(see pricing.py). Every string is cut to its column length, because MACS columns are short (CAR_NO is 8).
"""

from datetime import date, datetime, timedelta
from typing import Any

from django.db import connection

from autoservice import pricing

HEADER_FROM = """
FROM PRICE_VOTE v
LEFT JOIN BRANCH b ON b.BRANCH_ID = v.BRANCH_IDENT
LEFT JOIN CAR_REF r ON r.CAR_ID = v.CAR_IDENT
LEFT JOIN CUSTOMER cu ON cu.CUST_ID = v.REQCUST_IDENT
"""
HEADER_COLUMNS = (
    ("id", "v.PRICEVOTE_ID"),
    ("doc_no", "v.DOC_NO"),
    ("last_no", "v.LAST_NO"),
    ("date", "v.VOTE_DATE"),
    ("branch_id", "v.BRANCH_IDENT"),
    ("branch", "b.DESCRIPTION"),
    ("vehicle_id", "v.CAROWNER_IDENT"),
    ("car_id", "v.CAR_IDENT"),
    ("mark", "r.DESCRIPTION"),
    ("plate", "v.CAR_NO"),
    ("customer", "v.REQCUST_NAME"),
    ("customer_id", "v.REQCUST_IDENT"),
    ("org", "cu.DESCRIPTION"),
    ("phone", "v.REQCUST_PHONE"),
    ("vin", "v.VIN_NUMBER"),
    ("body_no", "v.KUZOV_NO"),
    ("engine_type", "v.ENGINE_TYPE"),
    ("engine_no", "v.ENGINE_NUMBER"),
    ("color", "v.CAR_COLOR"),
    ("certificate", "v.CERTIFICATE"),
    ("driver_no", "v.DRIVER_NO"),
    ("year", "v.MAKE_YEAR"),
    ("odometer", "v.SPEEDOMETER_REF"),
    ("notes", "v.NOTE"),
    ("user", "v.REG_USER"),
    ("vat_percent", "v.VAT_PERCENT"),
)
HEADER_SELECT = ", ".join(sql for _, sql in HEADER_COLUMNS)

# What the customer pays per kind of line: TOTAL (after discount, without VAT) + VAT_AMOUNT.
WORKS_SUM = (
    "(SELECT SUM(j.TOTAL + COALESCE(j.VAT_AMOUNT, 0)) FROM PRICEVOTEJOB j WHERE j.PRICEVOTE_IDENT = v.PRICEVOTE_ID)"
)
PARTS_SUM = (
    "(SELECT SUM(i.TOTAL + COALESCE(i.VAT_AMOUNT, 0)) FROM PRICEVOTEITEM i WHERE i.PRICEVOTE_IDENT = v.PRICEVOTE_ID)"
)

LIMITS = {
    "doc_no": 12,
    "customer": 80,
    "phone": 30,
    "plate": 8,
    "body_no": 15,
    "engine_type": 10,
    "notes": 100,
    "user": 12,
    "vin": 30,
    "color": 60,
    "engine_no": 30,
    "certificate": 30,
    "driver_no": 30,
    "spec": 30,
}


class QuoteError(Exception):
    """A request the data does not allow (the message is shown to the user)."""


def cut(value: Any, key: str) -> str:
    return str(value or "").strip()[: LIMITS[key]]


def _text(v: Any) -> Any:
    return v.rstrip() if isinstance(v, str) else v


def _header(keys_values: tuple[Any, ...]) -> dict[str, Any]:
    h = {key: _text(value) for (key, _), value in zip(HEADER_COLUMNS, keys_values, strict=True)}
    h["no"] = int(h["last_no"] or 0) or (int(h["doc_no"]) if str(h["doc_no"] or "").isdigit() else h["id"])
    h["vat_on"] = float(h["vat_percent"] or 0) > 0
    return h


def _lines(sql: str, pk: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with connection.cursor() as c:
        c.execute(sql, [pk])
        for ref, code, label, barcode, *rest in c.fetchall():
            qty, price, disc, card, vat_amount, price_nt, base, rate, *extra = rest
            line = pricing.line_from_db(qty, price, disc, card, vat_amount, price_nt, base, rate)
            line.update(ref=ref, code=_text(code) or "", name=_text(label) or _text(barcode) or "")
            if extra:
                line["stock"] = float(extra[0]) if extra[0] is not None else None
            out.append(line)
    return out


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(f"SELECT {HEADER_SELECT} {HEADER_FROM} WHERE v.PRICEVOTE_ID = %s", [pk])  # noqa: S608 - constants
        row = c.fetchone()
    if row is None:
        return None
    q = _header(row)
    q["works"] = _lines(
        "SELECT j.WORK_IDENT, w.CODE, w.DESCRIPTION, w.SHORTNAME, j.QUANTITY, j.PRICE, j.DISCOUNT, j.CARD_PERCENT, "
        "j.VAT_AMOUNT, j.PRICE_NT, j.BASEPRICE, j.PROC_N FROM PRICEVOTEJOB j "
        "JOIN WORKS w ON w.WORK_ID = j.WORK_IDENT WHERE j.PRICEVOTE_IDENT = %s ORDER BY j.PRICEVOTEJOB_ID",
        pk,
    )
    q["parts"] = _lines(
        "SELECT i.ITEM_IDENT, t.ITEMCODE, t.DESCRIPTION, t.BARCODE, i.QUANTITY, i.PRICE, i.DISCOUNT, i.CARD_PERCENT, "
        "i.VAT_AMOUNT, i.PRICE_NT, i.BASEPRICE, i.PROC_N, i.BAL_QTY FROM PRICEVOTEITEM i "
        "JOIN ITEM t ON t.ITEM_ID = i.ITEM_IDENT WHERE i.PRICEVOTE_IDENT = %s ORDER BY i.PRICEVOTEITEM_ID",
        pk,
    )
    return q


def _day_start(s: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(s[:10]), datetime.min.time())
    except ValueError as e:
        raise QuoteError("Огнооны хэлбэр буруу байна (YYYY-MM-DD).") from e


def listing(filters: dict[str, str], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Quotes newest first, each with the works / parts / total amounts the customer pays."""
    where: list[str] = []
    params: list[Any] = []
    if filters.get("branch_id"):
        where.append("v.BRANCH_IDENT = %s")
        params.append(int(filters["branch_id"]))
    if filters.get("plate"):
        where.append("UPPER(v.CAR_NO) LIKE UPPER(%s)")
        params.append(f"%{filters['plate']}%")
    if filters.get("org"):
        where.append("UPPER(cu.DESCRIPTION) LIKE UPPER(%s)")
        params.append(f"%{filters['org']}%")
    if filters.get("from"):
        where.append("v.VOTE_DATE >= %s")
        params.append(_day_start(filters["from"]))
    if filters.get("to"):
        where.append("v.VOTE_DATE < %s")
        params.append(_day_start(filters["to"]) + timedelta(days=1))
    if filters.get("q"):
        like = f"%{filters['q']}%"
        where.append(
            "(v.DOC_NO LIKE %s OR UPPER(v.CAR_NO) LIKE UPPER(%s) OR UPPER(v.REQCUST_NAME) LIKE UPPER(%s) "
            "OR UPPER(cu.DESCRIPTION) LIKE UPPER(%s))"
        )
        params += [like] * 4
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) {HEADER_FROM}{clause}", params)  # noqa: S608 - constants + parameters
        total = int(c.fetchone()[0])
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {HEADER_SELECT}, {WORKS_SUM}, {PARTS_SUM} "  # noqa: S608
            f"{HEADER_FROM}{clause} ORDER BY v.VOTE_DATE DESC, v.PRICEVOTE_ID DESC",
            params,
        )
        rows = c.fetchall()
    out = []
    for row in rows:
        q = _header(row[: len(HEADER_COLUMNS)])
        works, parts = float(row[-2] or 0), float(row[-1] or 0)
        q.update(works_total=round(works, 2), parts_total=round(parts, 2), total=round(works + parts, 2))
        out.append(q)
    return out, total


def vehicle(vehicle_id: int) -> dict[str, Any] | None:
    """The CARS row a quote is for; its details are copied onto the quote (MACS keeps that snapshot)."""
    with connection.cursor() as c:
        c.execute(
            "SELECT CARS_ID, CAR_IDENT, CAR_NO, KUZOV_NO, ENGINE_TYPE, VIN_NUMBER, CAR_COLOR, ENGINE_NUMBER, "
            "CERTIFICATE, DRIVER_NO, MAKED_DATE, SPECIFICATION, MAKE_YEAR, REQCUST_NAME, REQCUST_PHONE "
            "FROM CARS WHERE CARS_ID = %s",
            [vehicle_id],
        )
        r = c.fetchone()
    if r is None:
        return None
    keys = (
        "id",
        "car_id",
        "plate",
        "body_no",
        "engine_type",
        "vin",
        "color",
        "engine_no",
        "certificate",
        "driver_no",
        "maked",
        "spec",
        "year",
        "owner",
        "phone",
    )
    return {k: _text(v) for k, v in zip(keys, r, strict=True)}


def _number(body: dict[str, Any], key: str, low: float, high: float, label: str) -> float:
    try:
        v = float(body.get(key, 0) or 0)
    except (TypeError, ValueError) as e:
        raise QuoteError(f"{label}: тоо оруулна уу.") from e
    if not low <= v <= high:
        raise QuoteError(f"{label}: {low:g}–{high:g} хооронд байх ёстой.")
    return v


def _clean_lines(raw: Any, ref_key: str, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise QuoteError(f"{label}: жагсаалт байх ёстой.")
    out = []
    for n, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise QuoteError(f"{label} №{n}: буруу мөр.")
        try:
            ref = int(item.get("ref") or item.get(ref_key) or 0)
        except (TypeError, ValueError):
            ref = 0
        if ref <= 0:
            raise QuoteError(f"{label} №{n}: бүртгэлтэй {'ажил' if ref_key == 'work_id' else 'бараа'} сонгоно уу.")
        line: dict[str, Any] = {
            "ref": ref,
            "qty": _number(item, "qty", 0.000001, 1_000_000, f"{label} №{n} тоо"),
            "price": _number(item, "price", 0, 1_000_000_000, f"{label} №{n} үнэ"),
            "disc": _number(item, "disc", 0, 100, f"{label} №{n} хөнгөлөлт"),
            "card": _number(item, "card", 0, 100, f"{label} №{n} картын хувь"),
            "vat": bool(item.get("vat", True)),
            "stock": item.get("stock"),
        }
        if line["disc"] + line["card"] > 100:
            raise QuoteError(f"{label} №{n}: хөнгөлөлт ба картын хувийн нийлбэр 100-аас хэтэрсэн.")
        out.append(line)
    return out


def _optional_id(value: Any, label: str) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise QuoteError(f"{label}: буруу дугаар.") from e


def parse(body: dict[str, Any]) -> dict[str, Any]:
    """Check a request body and turn it into what is stored. Raises QuoteError with a message for the user."""
    try:
        vehicle_id = int(body.get("vehicle_id") or 0)
    except (TypeError, ValueError):
        vehicle_id = 0
    if vehicle_id <= 0:
        raise QuoteError("Автомашин сонгоно уу (vehicle_id).")
    car = vehicle(vehicle_id)
    if car is None:
        raise QuoteError("Автомашин олдсонгүй.")
    if not car["car_id"]:
        raise QuoteError("Автомашины марк бүртгэгдээгүй тул үнийн санал үүсгэх боломжгүй.")
    customer = cut(body.get("customer") or car["owner"], "customer")
    if not customer:
        raise QuoteError("Үйлчлүүлэгчийн нэрийг бөглөнө үү.")
    when = datetime.now().replace(microsecond=0)
    if body.get("date"):
        try:
            when = datetime.fromisoformat(str(body["date"])).replace(tzinfo=None)
        except ValueError as e:
            raise QuoteError("Огнооны хэлбэр буруу байна.") from e
    works = _clean_lines(body.get("works"), "work_id", "Ажил")
    parts = _clean_lines(body.get("parts"), "item_id", "Сэлбэг")
    if not works and not parts:
        raise QuoteError("Ажил эсвэл сэлбэгийн мөр нэмнэ үү.")
    odometer = body.get("odometer")
    return {
        "car": car,
        "customer": customer,
        "customer_id": _optional_id(body.get("customer_id"), "Харилцагч"),
        "branch_id": _optional_id(body.get("branch_id"), "Салбар"),
        "phone": cut(body.get("phone") or car["phone"], "phone"),
        "date": when,
        "vat_on": bool(body.get("vat_on", True)),
        "odometer": int(str(odometer).strip()) if str(odometer or "").strip().isdigit() else None,
        "notes": cut(body.get("notes"), "notes"),
        "works": works,
        "parts": parts,
    }


def _next_id(c: Any, generator: str) -> int:
    c.execute(f"SELECT GEN_ID({generator}, 1) FROM RDB$DATABASE")  # noqa: S608 - constant generator name
    return int(c.fetchone()[0])


def _insert(c: Any, table: str, values: dict[str, Any]) -> None:
    cols = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))  # noqa: S608 - constants


def _write_lines(c: Any, pk: int, data: dict[str, Any]) -> None:
    for line in data["works"]:
        values = {
            "PRICEVOTEJOB_ID": _next_id(c, "GEN_PRICEVOTEJOB_ID"),
            "PRICEVOTE_IDENT": pk,
            "WORK_IDENT": line["ref"],
        }
        _insert(c, "PRICEVOTEJOB", values | pricing.line_to_db(line, data["vat_on"]))
    for line in data["parts"]:
        values = {
            "PRICEVOTEITEM_ID": _next_id(c, "GEN_PRICEVOTEITEM_ID"),
            "PRICEVOTE_IDENT": pk,
            "ITEM_IDENT": line["ref"],
        }
        stock = line["stock"]
        extra = {"BAL_QTY": float(stock)} if isinstance(stock, int | float) else {}
        _insert(c, "PRICEVOTEITEM", values | pricing.line_to_db(line, data["vat_on"]) | extra)


def _header_values(data: dict[str, Any], user: str) -> dict[str, Any]:
    car = data["car"]
    return {
        "REQCUST_NAME": data["customer"],
        "REQCUST_IDENT": data["customer_id"],
        "REQCUST_PHONE": data["phone"],
        "CAR_NO": cut(car["plate"], "plate"),
        "CAROWNER_IDENT": car["id"],
        "CAR_IDENT": car["car_id"],
        "KUZOV_NO": cut(car["body_no"], "body_no"),
        "ENGINE_TYPE": cut(car["engine_type"], "engine_type"),
        "VOTE_DATE": data["date"],
        "SPEEDOMETER_REF": data["odometer"],
        "NOTE": data["notes"],
        "REG_USER": cut(user, "user"),
        "VIN_NUMBER": cut(car["vin"], "vin"),
        "CAR_COLOR": cut(car["color"], "color"),
        "ENGINE_NUMBER": cut(car["engine_no"], "engine_no"),
        "CERTIFICATE": cut(car["certificate"], "certificate"),
        "DRIVER_NO": cut(car["driver_no"], "driver_no"),
        "MAKED_DATE": car["maked"],
        "SPECIFICATION": cut(car["spec"], "spec"),
        "MAKE_YEAR": car["year"],
        "BRANCH_IDENT": data["branch_id"],
        "VAT_PERCENT": pricing.VAT_RATE if data["vat_on"] else 0.0,
    }


def create(data: dict[str, Any], user: str) -> int:
    """Insert a quote with its lines (call inside a transaction). The next number is last number + 1."""
    with connection.cursor() as c:
        c.execute("SELECT COALESCE(MAX(LAST_NO), 0) FROM PRICE_VOTE")
        number = int(c.fetchone()[0]) + 1
        pk = _next_id(c, "GEN_PRICEVOTE_ID")
        values = {"PRICEVOTE_ID": pk, "DOC_NO": cut(number, "doc_no"), "LAST_NO": number} | _header_values(data, user)
        _insert(c, "PRICE_VOTE", values)
        _write_lines(c, pk, data)
    return pk


def replace(pk: int, data: dict[str, Any], user: str) -> bool:
    """Rewrite a quote (header and all lines). The number is kept. False when there is no such quote."""
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM PRICE_VOTE WHERE PRICEVOTE_ID = %s", [pk])
        if c.fetchone() is None:
            return False
        header = _header_values(data, user)
        header.pop("REG_USER")  # the person who registered it stays
        sets = ", ".join(f"{col} = %s" for col in header)
        c.execute(f"UPDATE PRICE_VOTE SET {sets} WHERE PRICEVOTE_ID = %s", [*header.values(), pk])  # noqa: S608
        c.execute("DELETE FROM PRICEVOTEJOB WHERE PRICEVOTE_IDENT = %s", [pk])
        c.execute("DELETE FROM PRICEVOTEITEM WHERE PRICEVOTE_IDENT = %s", [pk])
        _write_lines(c, pk, data)
    return True


class QuoteInUse(QuoteError):
    """A service card was made from this quote."""


def delete(pk: int) -> bool:
    """Delete a quote (the database removes its lines). Refused while a service card points to it: the
    SERVCARDS foreign key is ON DELETE SET NULL, so the database itself would silently cut that link."""
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM SERVCARDS WHERE PRICEVOTE_IDENT = %s", [pk])
        if int(c.fetchone()[0]):
            raise QuoteInUse("Үйлчилгээний картад холбогдсон тул устгах боломжгүй.")
        c.execute("DELETE FROM PRICE_VOTE WHERE PRICEVOTE_ID = %s", [pk])
        return bool(c.rowcount)

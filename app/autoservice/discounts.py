# ruff: noqa: S608 - SQL pieces are constants or ints; every user value goes in as a parameter
"""Discount settings (Хямдралын тохиргоо): DISCOUNT_HEADER with its DISCOUNT_ITEMS.

How the desktop uses them (GETDISCOUNT_INFO_V2): a header is live while STARTDATE <= day < ENDDATE, INACTIV = 'no' and
DCODE > 0 (DCODE is what a DIS_CARD points at). With ALL_ITEMS = 1 it covers every item, narrowed by ASSET_ACCS and
ICLASS (an "id;id;" list); with ALL_ITEMS = 0 only the DISCOUNT_ITEMS rows count. DISCOUNT_ITEMS.ITEM_IDENT is an
ITEM.ITEMNAME_IDENT (one name, many ITEM rows - one per asset account), and its DISCOUNT overrides the header percent.
"""

from datetime import date, datetime
from typing import Any

from django.db import connection

from autoservice.views import clean

# Types known from the desktop's data: both are percent discounts (GETDISCOUNT_INFO_V2: 1, 2, 6, 8, 9 = percent).
TYPES = {
    9: "Холбогдсон картанд X хувь хөнгөлнө",
    1: "X хувь хөнгөлнө",
}
LIMITS = {"name": 200, "note": 200, "asset_accounts": 800, "classes": 800}


class DiscountError(ValueError):
    """The request cannot be saved; the message is shown to the user."""


def _day(value: Any, label: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise DiscountError(f"{label} огноо буруу байна.") from None


def _num(value: Any, label: str) -> float:
    try:
        n = float(value if value not in (None, "") else 0)
    except (TypeError, ValueError):
        raise DiscountError(f"{label} тоо байх ёстой.") from None
    if n < 0:
        raise DiscountError(f"{label} сөрөг байж болохгүй.")
    return n


def _text(value: Any, label: str, field: str, required: bool = False) -> str:
    s = str(value or "").strip()
    if required and not s:
        raise DiscountError(f"{label} оруулна уу.")
    if len(s) > LIMITS[field]:
        raise DiscountError(f"{label} хэт урт байна ({LIMITS[field]} тэмдэгтээс ихгүй).")
    return s


def parse(body: dict[str, Any]) -> dict[str, Any]:
    """The screen's fields, checked and in column form."""
    kind = int(body.get("type") or 0)
    all_items = bool(body.get("all_items"))
    start, end = _day(body.get("start"), "Эхлэх"), _day(body.get("end"), "Дуусах")
    if start and end and end <= start:
        raise DiscountError("Дуусах огноо эхлэх огнооноос хойш байх ёстой.")
    percent = _num(body.get("percent"), "Хувь")
    if percent > 100:
        raise DiscountError("Хувь 100-аас ихгүй байх ёстой.")
    items = []
    seen: set[int] = set()
    for row in body.get("items") or []:
        ref = int(row.get("ref") or 0)
        if ref <= 0 or ref in seen:
            continue
        seen.add(ref)
        pct = row.get("percent")
        items.append({"ref": ref, "percent": None if pct in (None, "") else min(_num(pct, "Барааны хөнгөлөлт"), 100)})
    return {
        "name": _text(body.get("name"), "Хямдралын нэр", "name", required=True),
        "note": _text(body.get("note"), "Тайлбар", "note"),
        "code": int(body.get("code") or 0),
        "active": bool(body.get("active", True)),
        "type": kind if kind in TYPES else 1,
        "percent": percent,
        "all_items": all_items,
        "start": start,
        "end": end,
        "asset_accounts": _text(body.get("asset_accounts"), "Хөрөнгийн дансууд", "asset_accounts"),
        "classes": _text(body.get("classes"), "Ангилал", "classes"),
        "max_percent": _num(body.get("max_percent"), "Үнийн дундын хувь"),
        "max_price": _num(body.get("max_price"), "Хязгаарлах дүн"),
        "items": [] if all_items else items,
    }


HEADER = (
    "DISCOUNT_ID, DESCRIPTION, REASON, STARTDATE, ENDDATE, INACTIV, DISCOUNTTYPE, AMT_PERC, DCODE, "
    "ASSET_ACCS, ALL_ITEMS, ICLASS, USE_MAXPERCENT, ALLOW_MAXPRICE"
)


def _header(row: tuple[Any, ...]) -> dict[str, Any]:
    r = [clean(v) for v in row]
    return {
        "id": r[0],
        "name": r[1],
        "note": r[2] or "",
        "start": (r[3] or "")[:10],
        "end": (r[4] or "")[:10],
        "active": r[5] != "yes",
        "type": r[6],
        "percent": r[7] or 0,
        "code": r[8],
        "asset_accounts": r[9] or "",
        "all_items": bool(r[10]),
        "classes": r[11] or "",
        "max_percent": r[12] or 0,
        "max_price": r[13] or 0,
    }


def listing(q: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, params = "", []
    if q:
        where, params = "WHERE UPPER(DESCRIPTION) LIKE %s", [f"%{q.upper()}%"]
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) FROM DISCOUNT_HEADER {where}", params)  # noqa: S608
        total = c.fetchone()[0]
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {HEADER} FROM DISCOUNT_HEADER {where} "  # noqa: S608
            "ORDER BY STARTDATE DESC, DISCOUNT_ID DESC",
            params,
        )
        rows = [_header(r) for r in c.fetchall()]
        if rows:
            ids = ",".join(str(int(r["id"])) for r in rows)  # ids read from the table just above
            c.execute(
                f"SELECT DISCOUNT_IDENT, COUNT(*) FROM DISCOUNT_ITEMS WHERE DISCOUNT_IDENT IN ({ids}) GROUP BY 1"  # noqa: S608
            )
            counts = dict(c.fetchall())
            for r in rows:
                r["item_count"] = counts.get(r["id"], 0)
    return rows, total


ITEM_NAME = "(SELECT FIRST 1 i.DESCRIPTION FROM ITEM i WHERE i.ITEMNAME_IDENT = d.ITEM_IDENT)"
ITEM_BARCODE = "(SELECT FIRST 1 i.BARCODE FROM ITEM i WHERE i.ITEMNAME_IDENT = d.ITEM_IDENT)"
ITEM_CLASS = (
    "(SELECT FIRST 1 k.NAME FROM ITEM i JOIN ITEMCLASS k ON k.ITEMCLASS_ID = i.ITEMCLASS "
    "WHERE i.ITEMNAME_IDENT = d.ITEM_IDENT)"
)


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(f"SELECT {HEADER} FROM DISCOUNT_HEADER WHERE DISCOUNT_ID = %s", [pk])  # noqa: S608
        row = c.fetchone()
        if row is None:
            return None
        out = _header(row)
        c.execute(
            f"SELECT d.ITEM_IDENT, {ITEM_NAME}, {ITEM_BARCODE}, {ITEM_CLASS}, d.DISCOUNT "  # noqa: S608
            "FROM DISCOUNT_ITEMS d WHERE d.DISCOUNT_IDENT = %s ORDER BY 2",
            [pk],
        )
        out["items"] = [
            {
                "ref": r[0],
                "name": clean(r[1]) or "",
                "barcode": clean(r[2]) or "",
                "class": clean(r[3]) or "",
                "percent": clean(r[4]),
            }
            for r in c.fetchall()
        ]
    return out


def _write_items(c: Any, pk: int, items: list[dict[str, Any]]) -> None:
    now = datetime.now()
    c.execute("DELETE FROM DISCOUNT_ITEMS WHERE DISCOUNT_IDENT = %s", [pk])
    for it in items:
        c.execute(
            "INSERT INTO DISCOUNT_ITEMS "
            "(DISCOUNT_IDENT, ITEM_IDENT, DISCOUNT, ITEM_PRICE, DISCOUNT_PRICE, MODIFIED_DATE) "
            "VALUES (%s, %s, %s, 0, 0, %s)",
            [pk, it["ref"], it["percent"], now],
        )


def _columns(d: dict[str, Any]) -> list[Any]:
    return [
        d["name"], d["note"] or None, d["start"], d["end"], "no" if d["active"] else "yes", d["type"], d["percent"],
        d["code"], d["asset_accounts"] or None, 1 if d["all_items"] else 0, d["classes"] or None,
        d["max_percent"], d["max_price"], datetime.now(),
    ]  # fmt: skip


def _next_code() -> int:
    with connection.cursor() as c:
        c.execute("SELECT COALESCE(MAX(DCODE), 0) + 1 FROM DISCOUNT_HEADER")
        return int(c.fetchone()[0])


def _check_code(c: Any, code: int, own: int | None) -> None:
    if code <= 0:
        raise DiscountError("Код 0-ээс их бүхэл тоо байх ёстой.")
    c.execute("SELECT DISCOUNT_ID FROM DISCOUNT_HEADER WHERE DCODE = %s", [code])
    other = c.fetchone()
    if other and other[0] != own:
        raise DiscountError(f"{code} код өөр хямдралд ашиглагдаж байна.")


COLS = (
    "DESCRIPTION = %s, REASON = %s, STARTDATE = %s, ENDDATE = %s, INACTIV = %s, DISCOUNTTYPE = %s, AMT_PERC = %s, "
    "DCODE = %s, ASSET_ACCS = %s, ALL_ITEMS = %s, ICLASS = %s, USE_MAXPERCENT = %s, ALLOW_MAXPRICE = %s, "
    "MODIFIED_DATE = %s"
)


def create(d: dict[str, Any]) -> int:
    if not d["code"]:
        d["code"] = _next_code()
    with connection.cursor() as c:
        _check_code(c, d["code"], None)
        c.execute("SELECT GEN_ID(GEN_DISCOUNTID, 1) FROM RDB$DATABASE")
        pk = int(c.fetchone()[0])
        c.execute(
            "INSERT INTO DISCOUNT_HEADER (DISCOUNT_ID, DESCRIPTION, REASON, STARTDATE, ENDDATE, INACTIV, DISCOUNTTYPE, "
            "AMT_PERC, DCODE, ASSET_ACCS, ALL_ITEMS, ICLASS, USE_MAXPERCENT, ALLOW_MAXPRICE, MODIFIED_DATE) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [pk, *_columns(d)],
        )
        _write_items(c, pk, d["items"])
    return pk


def replace(pk: int, d: dict[str, Any]) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT DCODE FROM DISCOUNT_HEADER WHERE DISCOUNT_ID = %s", [pk])
        row = c.fetchone()
        if row is None:
            return False
        if not d["code"]:
            d["code"] = int(row[0] or 0) or _next_code()  # left empty: keep the code cards already point at
        _check_code(c, d["code"], pk)
        c.execute(f"UPDATE DISCOUNT_HEADER SET {COLS} WHERE DISCOUNT_ID = %s", [*_columns(d), pk])  # noqa: S608
        _write_items(c, pk, d["items"])
    return True


def delete(pk: int) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT DCODE FROM DISCOUNT_HEADER WHERE DISCOUNT_ID = %s", [pk])
        row = c.fetchone()
        if row is None:
            return False
        c.execute("DELETE FROM DISCOUNT_ITEMS WHERE DISCOUNT_IDENT = %s", [pk])
        c.execute("DELETE FROM DISCOUNT_HEADER WHERE DISCOUNT_ID = %s", [pk])
    return True


def lookups() -> dict[str, Any]:
    with connection.cursor() as c:
        c.execute(
            "SELECT DISTINCT i.ASSET_ACC, a.DESCRIPTION FROM ITEM i LEFT JOIN ACCOUNT a ON a.ACCNO = i.ASSET_ACC "
            "WHERE i.ASSET_ACC IS NOT NULL ORDER BY 1"
        )
        accounts = [{"id": clean(r[0]), "name": clean(r[1]) or ""} for r in c.fetchall()]
        c.execute("SELECT ITEMCLASS_ID, NAME FROM ITEMCLASS ORDER BY NAME")
        classes = [{"id": r[0], "name": clean(r[1]) or ""} for r in c.fetchall()]
    return {
        "types": [{"id": k, "name": v} for k, v in TYPES.items()],
        "asset_accounts": accounts,
        "classes": classes,
        "next_code": _next_code(),
    }


def search_items(q: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Item names (one row per ITEMNAME_IDENT, however many asset accounts carry it)."""
    where, params = "WHERE i.ITEMNAME_IDENT IS NOT NULL", []
    if q:
        where += " AND (UPPER(i.DESCRIPTION) LIKE %s OR i.BARCODE LIKE %s)"
        params = [f"%{q.upper()}%", f"%{q}%"]
    base = (
        "FROM ITEM i LEFT JOIN ITEMCLASS k ON k.ITEMCLASS_ID = i.ITEMCLASS "
        # `where` is built from constants above; the values go in as parameters
        f"{where} AND i.ITEM_ID = (SELECT MIN(j.ITEM_ID) FROM ITEM j WHERE j.ITEMNAME_IDENT = i.ITEMNAME_IDENT)"  # noqa: S608
    )
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) {base}", params)  # noqa: S608
        total = c.fetchone()[0]
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} i.ITEMNAME_IDENT, i.DESCRIPTION, i.BARCODE, k.NAME "  # noqa: S608
            f"{base} ORDER BY i.DESCRIPTION",
            params,
        )
        rows = [
            {"ref": r[0], "name": clean(r[1]) or "", "barcode": clean(r[2]) or "", "class": clean(r[3]) or ""}
            for r in c.fetchall()
        ]
    return rows, total

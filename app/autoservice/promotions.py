# ruff: noqa: S608 - SQL pieces are constants or ints; every user value goes in as a parameter
"""Promotions (Урамшууллын ажил үйлчилгээ): DISCOUNTWORK_HEADER with its DISCOUNT_WORKS.

A promotion is live between STARTDATE and ENDDATE while INACTIV = 'no'. Each line says: for goods of this class
(ITEMCLASS_IDENT) the accompanying work (WORK_IDENT) is discounted by DISC_PERCENT. Deleting a header removes its lines
(trigger DISCOUNTWORK_HEADER_BD0), which `delete` leaves to the database.
"""

from datetime import date, datetime
from typing import Any

from django.db import connection

from autoservice.views import clean

NAME_LIMIT = 200
ACCOUNT_LIMIT = 12


class PromotionError(ValueError):
    """The request cannot be saved; the message is shown to the user."""


def _day(value: Any, label: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise PromotionError(f"{label} огноо буруу байна.") from None


def parse(body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise PromotionError("Урамшууллын нэр заавал бөглөнө.")
    if len(name) > NAME_LIMIT:
        raise PromotionError(f"Урамшууллын нэр хэт урт байна ({NAME_LIMIT} тэмдэгтээс ихгүй).")
    start, end = _day(body.get("start"), "Эхлэх"), _day(body.get("end"), "Дуусах")
    if start and end and end < start:
        raise PromotionError("Дуусах огноо эхлэх огнооноос өмнө байж болохгүй.")
    account = str(body.get("account") or "").strip()
    if len(account) > ACCOUNT_LIMIT:
        raise PromotionError(f"Хөнгөлөлтийн данс хэт урт байна ({ACCOUNT_LIMIT} тэмдэгтээс ихгүй).")
    lines: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for row in body.get("lines") or []:
        try:
            key = (int(row.get("class_id") or 0), int(row.get("work_id") or 0))
            percent = float(row.get("percent") if row.get("percent") not in (None, "") else 0)
        except (TypeError, ValueError):
            raise PromotionError("Мөрийн утга буруу байна.") from None
        if key[0] <= 0 or key[1] <= 0:
            raise PromotionError("Мөр бүрт барааны ангилал болон ажлыг сонгоно уу.")
        if not 0 <= percent <= 100:
            raise PromotionError("Хөнгөлөлтийн хувь 0-100 хооронд байх ёстой.")
        if key not in seen:
            seen.add(key)
            lines.append({"class_id": key[0], "work_id": key[1], "percent": percent})
    return {
        "name": name,
        "start": start,
        "end": end,
        "active": bool(body.get("active", True)),
        "account": account,
        "lines": lines,
    }


def _header(r: tuple[Any, ...]) -> dict[str, Any]:
    v = [clean(x) for x in r]
    return {
        "id": v[0],
        "name": v[1],
        "start": (v[2] or "")[:10],
        "end": (v[3] or "")[:10],
        "active": v[4] != "yes",
        "account": v[5] or "",
    }


HEADER = "DISCOUNTWORK_ID, DESCRIPTION, STARTDATE, ENDDATE, INACTIV, DISC_ACC"


def listing(q: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, params = "", []
    if q:
        where, params = "WHERE UPPER(DESCRIPTION) LIKE %s", [f"%{q.upper()}%"]
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) FROM DISCOUNTWORK_HEADER {where}", params)
        total = c.fetchone()[0]
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {HEADER} FROM DISCOUNTWORK_HEADER {where} "
            "ORDER BY STARTDATE DESC, DISCOUNTWORK_ID DESC",
            params,
        )
        return [_header(r) for r in c.fetchall()], total


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(f"SELECT {HEADER} FROM DISCOUNTWORK_HEADER WHERE DISCOUNTWORK_ID = %s", [pk])
        row = c.fetchone()
        if row is None:
            return None
        out = _header(row)
        c.execute(
            "SELECT d.ITEMCLASS_IDENT, k.NAME, k.CODE, d.WORK_IDENT, w.DESCRIPTION, w.CODE, d.DISC_PERCENT "
            "FROM DISCOUNT_WORKS d LEFT JOIN ITEMCLASS k ON k.ITEMCLASS_ID = d.ITEMCLASS_IDENT "
            "LEFT JOIN WORKS w ON w.WORK_ID = d.WORK_IDENT WHERE d.DISCOUNTWORK_IDENT = %s ORDER BY 2, 5",
            [pk],
        )
        out["lines"] = [
            {
                "class_id": r[0],
                "class": clean(r[1]) or "",
                "class_code": clean(r[2]) or "",
                "work_id": r[3],
                "work": clean(r[4]) or "",
                "work_code": clean(r[5]) or "",
                "percent": clean(r[6]) or 0,
            }
            for r in c.fetchall()
        ]
    return out


def _columns(d: dict[str, Any]) -> list[Any]:
    return [d["name"], d["start"], d["end"], "no" if d["active"] else "yes", d["account"] or None, datetime.now()]


def _write_lines(c: Any, pk: int, lines: list[dict[str, Any]]) -> None:
    c.execute("DELETE FROM DISCOUNT_WORKS WHERE DISCOUNTWORK_IDENT = %s", [pk])
    for ln in lines:
        c.execute(
            "INSERT INTO DISCOUNT_WORKS (DISCOUNTWORK_IDENT, ITEMCLASS_IDENT, WORK_IDENT, DISC_PERCENT) "
            "VALUES (%s, %s, %s, %s)",
            [pk, ln["class_id"], ln["work_id"], ln["percent"]],
        )


def create(d: dict[str, Any]) -> int:
    with connection.cursor() as c:
        c.execute("SELECT GEN_ID(GEN_DISCOUNTWORK_HEADER_ID, 1) FROM RDB$DATABASE")
        pk = int(c.fetchone()[0])
        c.execute(
            "INSERT INTO DISCOUNTWORK_HEADER (DISCOUNTWORK_ID, DESCRIPTION, STARTDATE, ENDDATE, INACTIV, DISC_ACC, "
            "MODIFIED_DATE) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [pk, *_columns(d)],
        )
        _write_lines(c, pk, d["lines"])
    return pk


def replace(pk: int, d: dict[str, Any]) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM DISCOUNTWORK_HEADER WHERE DISCOUNTWORK_ID = %s", [pk])
        if c.fetchone() is None:
            return False
        c.execute(
            "UPDATE DISCOUNTWORK_HEADER SET DESCRIPTION = %s, STARTDATE = %s, ENDDATE = %s, INACTIV = %s, "
            "DISC_ACC = %s, MODIFIED_DATE = %s WHERE DISCOUNTWORK_ID = %s",
            [*_columns(d), pk],
        )
        _write_lines(c, pk, d["lines"])
    return True


def delete(pk: int) -> bool:
    with connection.cursor() as c:
        c.execute("DELETE FROM DISCOUNTWORK_HEADER WHERE DISCOUNTWORK_ID = %s", [pk])
        return bool(c.rowcount)

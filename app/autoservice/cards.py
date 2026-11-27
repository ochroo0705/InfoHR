"""Discount cards (Хөнгөлөлт карт): DIS_CARD, its usage log DISCOUNT_TRANS and the bonus intervals DISCOUNT_PERCENT.

The card type lives in DIS_CARD.DCODE (see GET_BONUSINFO): -1 bonus collecting, -2 stepped (tiered) percent, -3 and -4
bonus balance cards (money-amount and voucher); a positive code is a DISCOUNT_HEADER (its name is the card type).
The bonus balance is whatever GET_BONUSINFO says, so the desktop and the web always agree.
The security code (SECURITY_CODE) is not sent: it is a PIN and nothing on the web screens needs it.
"""

from typing import Any

from django.db import connection

from autoservice.views import clean

# The -3 / -4 order follows the desktop menu (Мөнгөн дүнгээр, Ваучер); the data only says both keep a bonus balance.
TYPES = {
    -1: "Бонус цуглуулах карт",
    -2: "Шатлалаар өсөж буурах хөнгөлөх карт",
    -3: "Мөнгөн дүнгээр хөнгөлөх карт",
    -4: "Ваучер карт",
}

COLUMNS = (
    "c.DISCOUNT_CARD, c.CARDNO, c.OWNERNAME, c.WITHOWNER, c.REGISTERNO, c.PHONENUMBER, c.CAR_NO, c.VALID_SINCE, "
    "c.VALID_DAYS, c.EXPIRE_DATE, c.CUST_C1, c.CUST_C2, c.DCODE, c.DISCOUNT_PERCENT, c.CUST_IDENT, h.DESCRIPTION"
)
FROM = "FROM DIS_CARD c LEFT JOIN DISCOUNT_HEADER h ON h.DCODE = c.DCODE AND c.DCODE > 0"


def _bonus(c: Any, card_id: int, dcode: int) -> float:
    """BC2 of GET_BONUSINFO: the card's bonus balance (0 for cards that are not bonus cards)."""
    if dcode >= 0:
        return 0.0
    c.execute("SELECT BC2 FROM GET_BONUSINFO(%s, 0, %s)", [card_id, dcode])
    row = c.fetchone()
    return float(row[0] or 0) if row else 0.0


def _card(c: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    r = [clean(v) for v in row]
    dcode = int(r[12] or 0)
    return {
        "id": r[0],
        "card_no": r[1],
        "owner": r[2] or "",
        "partner": r[3] or "",
        "register": r[4] or "",
        "phone": r[5] or "",
        "plate": r[6] or "",
        "issued": (r[7] or "")[:10],
        "valid_days": r[8],
        "expires": (r[9] or "")[:10],
        "opening": r[10] or 0,
        "opening_bonus": r[11] or 0,
        "bonus": _bonus(c, int(r[0]), dcode),
        "dcode": dcode,
        "percent": r[13] or 0,
        "customer_id": r[14],
        "type": TYPES.get(dcode) or r[15] or "Хөнгөлөлтийн карт",
    }


def listing(q: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, params = "", []
    if q:
        where = "WHERE c.CARDNO LIKE %s OR UPPER(c.OWNERNAME) LIKE %s OR UPPER(c.CAR_NO) LIKE %s"
        params = [f"%{q}%", f"%{q.upper()}%", f"%{q.upper()}%"]
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) FROM DIS_CARD c {where}", params)  # noqa: S608
        total = c.fetchone()[0]
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {COLUMNS} {FROM} {where} ORDER BY c.CARDNO",  # noqa: S608
            params,
        )
        rows = [_card(c, r) for r in c.fetchall()]
    return rows, total


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(f"SELECT {COLUMNS} {FROM} WHERE c.DISCOUNT_CARD = %s", [pk])  # noqa: S608
        row = c.fetchone()
        return None if row is None else _card(c, row)


def statement(pk: int, start: str, end: str) -> list[dict[str, Any]]:
    """The card's usage log: what each sheet bought, the percent given, bonus added (NB) and used (HB)."""
    where = ["t.DISCOUNT_CARD = %s"]
    params: list[Any] = [pk]
    if start:
        where.append("t.DDATE >= %s")
        params.append(start)
    if end:
        where.append("t.DDATE < DATEADD(1 DAY TO CAST(%s AS DATE))")
        params.append(end)
    with connection.cursor() as c:
        c.execute(
            "SELECT t.DTRANS_ID, t.DDATE, t.HAD, t.DPERCENT, t.NB, t.HB, t.POSID, t.SHOPID, "  # noqa: S608
            "s.SERVCARD_ID, s.DOC_NO, s.CAR_NO "
            "FROM DISCOUNT_TRANS t LEFT JOIN SERVCARDS s ON s.SERVCARD_ID = t.SERVCARD_IDENT "
            f"WHERE {' AND '.join(where)} ORDER BY t.DDATE, t.DTRANS_ID",
            params,
        )
        out = []
        for r in c.fetchall():
            v = [clean(x) for x in r]
            out.append(
                {
                    "id": v[0],
                    "date": v[1],
                    "amount": v[2] or 0,
                    "percent": v[3] or 0,
                    "added": v[4] or 0,
                    "used": v[5] or 0,
                    "pos_id": v[6],
                    "shop_id": v[7],
                    "sheet_id": v[8],
                    "doc_no": v[9] or "",
                    "plate": v[10] or "",
                }  # fmt: skip
            )
    return out


def intervals() -> list[dict[str, Any]]:
    """DISCOUNT_PERCENT: purchase-amount ranges and the percent each gives (the bonus collecting interval)."""
    with connection.cursor() as c:
        c.execute(
            "SELECT DISC_PERCENT_ID, MINVALUE, MAXVALUE, DPERCENT, DORDER FROM DISCOUNT_PERCENT ORDER BY MINVALUE"
        )
        return [
            {"id": r[0], "min": clean(r[1]) or 0, "max": clean(r[2]) or 0, "percent": clean(r[3]) or 0, "order": r[4]}
            for r in c.fetchall()
        ]

"""Aggregate repair sheets (агрегат засвар) in MACS: SERVCARDS (SERVCARD_TYPE = 1) with SERVJOBS (works), EMP_WORKS
(the mechanic of each work), SERV_TRANS (parts) and JOURNAL (payments).

Most of the accounting is done by the database itself, so this module only feeds it the way the desktop program does:
  * inserting a SERV_TRANS row makes its trigger create the ORDERS / TRANSAC (stock and sales) rows;
  * FINISH_SERVCARDS checks the card (every work has a mechanic, nothing is left to pay), sets SERV_STATUS = 2, and the
    SERVCARDS_AI0 trigger then posts the journal (SERVCARDS2JOURNAL). Nothing here re-implements that.
Money columns follow pricing.py. Rules read out of the database's own procedures are noted where they are used.
"""

import logging
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import DatabaseError, connection

from autoservice import pricing
from autoservice.quotes import QuoteError, _clean_lines, _insert, _next_id, _number, _optional_id, _text, cut, vehicle

log = logging.getLogger(__name__)

AGGREGATE = 1  # SERVCARDS.SERVCARD_TYPE of an aggregate repair (2 = body repair)
NOT_STARTED, STARTED, FINISHED = 0, 1, 2

LIMITS = {"doc_no": 12, "user": 12, "journal_user": 20, "note": 800, "desc": 400}

HEADER_FROM = """
FROM SERVCARDS s
LEFT JOIN BRANCH b ON b.BRANCH_ID = s.BRANCH_IDENT
LEFT JOIN CAR_REF r ON r.CAR_ID = s.CAR_IDENT
LEFT JOIN CUSTOMER cu ON cu.CUST_ID = s.REQCUST_IDENT
LEFT JOIN DIS_CARD dc ON dc.DISCOUNT_CARD = s.DISCOUNT_CARD
"""
HEADER_COLUMNS = (
    ("id", "s.SERVCARD_ID"),
    ("doc_no", "s.DOC_NO"),
    ("date_in", "s.ENTRY_DATE"),
    ("started_at", "s.STARTED_DATE"),
    ("date_out", "s.EXIT_DATE"),
    ("status", "s.SERV_STATUS"),
    ("branch_id", "s.BRANCH_IDENT"),
    ("branch", "b.DESCRIPTION"),
    ("vehicle_id", "s.CAROWNER_IDENT"),
    ("car_id", "s.CAR_IDENT"),
    ("mark", "r.DESCRIPTION"),
    ("plate", "s.CAR_NO"),
    ("customer", "s.REQCUST_NAME"),
    ("customer_id", "s.REQCUST_IDENT"),
    ("org", "cu.DESCRIPTION"),
    ("phone", "s.REQCUST_PHONE"),
    ("vin", "s.VIN_NUMBER"),
    ("body_no", "s.KUZOV_NO"),
    ("engine_type", "s.ENGINE_TYPE"),
    ("engine_no", "s.ENGINE_NUMBER"),
    ("color", "s.CAR_COLOR"),
    ("certificate", "s.CERTIFICATE"),
    ("driver_no", "s.DRIVER_NO"),
    ("year", "s.MAKE_YEAR"),
    ("odometer", "s.SPEEDOMETER_REF"),
    ("remark", "s.NOTE"),
    ("warranty", "s.SHOCK_WARRANTY"),
    ("vat_percent", "s.VAT_PERCENT"),
    ("settle_later", "s.IS_RECIEVABLE"),
    ("internal", "s.IS_EXPENSE"),
    ("expense_acct", "s.EXPENSE_ACC"),
    ("card_id", "s.DISCOUNT_CARD"),
    ("card_no", "dc.CARDNO"),
    ("garage_day", "s.GARAGE_DAY"),
    ("garage_price", "s.GARAGE_PRICE"),
    ("quote_id", "s.PRICEVOTE_IDENT"),
    ("user", "s.REG_USER"),
)
HEADER_SELECT = ", ".join(sql for _, sql in HEADER_COLUMNS)

# What the customer pays for a card's lines, and what has been paid (the same rule as CALC_SERVCARDREP).
WORKS_SUM = (
    "(SELECT SUM(j.TOTAL_NT * (1 - (COALESCE(j.DISC_PERCENT, 0) + COALESCE(j.CARD_PERCENT, 0)) / 100)) "
    "FROM SERVJOBS j WHERE j.SERVCARD_IDENT = s.SERVCARD_ID)"
)
PARTS_SUM = (
    "(SELECT SUM(t.TOTAL_NT * (1 - (COALESCE(t.DISCOUNT, 0) + COALESCE(t.CARD_PERCENT, 0)) / 100)) "
    "FROM SERV_TRANS t WHERE t.SERVCARD_IDENT = s.SERVCARD_ID)"
)
PAID_SUM = "(SELECT SUM(p.JAMOUNT) FROM JOURNAL p WHERE p.SERVCARD_IDENT = s.SERVCARD_ID)"


class RepairError(QuoteError):
    """A request the data does not allow (the message is shown to the user)."""


class RepairLocked(RepairError):
    """The card is finished (or has payments) and cannot be changed that way."""


# Exceptions the database raises, by name -> what to tell the user.
DB_MESSAGES = {
    "EMPJOB_NOT_EQUAL": "Ажил бүрт засварчин оноогоогүй эсвэл ажлын дүн засварчны ажилтай тэнцэхгүй байна.",
    "PAYMENT_NOT_EQUAL": "Төлбөр бүрэн хийгдээгүй байна. Үлдэгдэл 0 болтол төлбөр бүртгэнэ үү.",
    "SERVCARD_DATE_IS_NULL": "Орсон болон гарсан огноо заавал байх ёстой.",
    "SERVCARD_CANNOTEDIT": "Дууссан картыг засах боломжгүй.",
    "SERVCARD_CANNOTDELETE": "Дууссан картын төлбөрийг өөрчлөх боломжгүй.",
    "SERVCARD_JOURNALEXISTS": "Журнал үүссэн тул устгах боломжгүй.",
    "CHKPREVENT_DATE": "Энэ огноо хаагдсан тул өөрчлөх боломжгүй.",
    "NOTSELECTCUST": "Авлагын дансанд харилцагч заавал байх ёстой.",
}


def db_error(e: DatabaseError) -> RepairError:
    """The database's own refusal as a RepairError with a message for the user."""
    text = str(e).upper()
    for name, message in DB_MESSAGES.items():
        if name in text:
            return RepairLocked(message)
    log.warning("Database refused a repair request: %s", e)
    detail = f" ({' '.join(str(e).split())})" if settings.DEBUG else ""  # the real reason, for developers only
    return RepairError("Мэдээллийн сан хүсэлтийг зөвшөөрсөнгүй." + detail)


def _header(values: tuple[Any, ...]) -> dict[str, Any]:
    h = {key: _text(v) for (key, _), v in zip(HEADER_COLUMNS, values, strict=True)}
    h["status"] = int(h["status"] or 0)
    h["started"] = h["status"] >= STARTED
    h["finished"] = h["status"] == FINISHED
    h["vat_on"] = float(h["vat_percent"] or 0) > 0
    h["warranty"] = h["warranty"] == "yes"
    h["settle_later"] = h["settle_later"] == "yes"
    h["internal"] = h["internal"] == "yes"
    h["garage_on"] = bool(h["garage_day"])
    h["garage"] = float(h["garage_price"] or 0)
    h["no"] = int(h["doc_no"]) if str(h["doc_no"] or "").isdigit() else h["id"]
    return h


def _work_lines(pk: int) -> list[dict[str, Any]]:
    out = []
    with connection.cursor() as c:
        c.execute(
            "SELECT j.WORK_IDENT, w.CODE, w.DESCRIPTION, j.QUANTITY, j.PRICE, j.DISC_PERCENT, j.CARD_PERCENT, "
            "j.TOTAL_NT, j.PRICE_NT, j.BASEPRICE, j.PROC_N, j.EMP_IDENT, e.DESCRIPTION "
            "FROM SERVJOBS j JOIN WORKS w ON w.WORK_ID = j.WORK_IDENT LEFT JOIN CUSTOMER e ON e.CUST_ID = j.EMP_IDENT "
            "WHERE j.SERVCARD_IDENT = %s ORDER BY j.SERVJOB_ID",
            [pk],
        )
        for ref, code, name, qty, _price, disc, card, _total_nt, price_nt, base, rate, emp, emp_name in c.fetchall():
            # `vat` follows the line's own rate: SERVJOBS has no VAT_AMOUNT column.
            line = pricing.line_from_db(qty, _price, disc, card, rate, price_nt, base, rate)
            line.update(
                ref=ref, code=_text(code) or "", name=_text(name) or "", mech_id=emp, mech=_text(emp_name) or ""
            )
            out.append(line)
    return out


def _part_lines(pk: int) -> list[dict[str, Any]]:
    out = []
    with connection.cursor() as c:
        c.execute(
            "SELECT t.ITEM_IDENT, i.ITEMCODE, i.DESCRIPTION, i.BARCODE, t.TRANSDATE, t.QUANTITY, t.PRICE, t.DISCOUNT, "
            "t.CARD_PERCENT, t.VAT_AMOUNT, t.PRICE_NT, t.PROC_N, t.BAL_QTY "
            "FROM SERV_TRANS t JOIN ITEM i ON i.ITEM_ID = t.ITEM_IDENT WHERE t.SERVCARD_IDENT = %s ORDER BY t.TRANS_ID",
            [pk],
        )
        for ref, code, name, barcode, when, qty, price, disc, card, vat_amount, price_nt, rate, bal in c.fetchall():
            line = pricing.line_from_db(qty, price, disc, card, vat_amount, price_nt, price_nt, rate)
            line.update(
                ref=ref,
                code=_text(code) or "",
                barcode=_text(barcode) or "",
                name=_text(name) or _text(barcode) or "",
                date=when.isoformat(timespec="seconds") if when else "",
                stock=float(bal) if bal is not None else None,
            )
            out.append(line)
    return out


def payments(pk: int) -> list[dict[str, Any]]:
    with connection.cursor() as c:
        c.execute(
            "SELECT p.JOURNAL_ID, p.JDATE, p.JAMOUNT, p.BANK_IDENT, k.DESCRIPTION, p.DBACC_NUM, p.USER_NAME "
            "FROM JOURNAL p LEFT JOIN BANKS k ON k.BANK_ID = p.BANK_IDENT WHERE p.SERVCARD_IDENT = %s "
            "ORDER BY p.JDATE, p.JOURNAL_ID",
            [pk],
        )
        return [
            {
                "id": jid,
                "date": when.isoformat(timespec="seconds") if when else "",
                "amount": float(amount or 0),
                "bank_id": bank,
                "method": _text(method) or "",
                "account": _text(acc) or "",
                "user": _text(user) or "",
            }
            for jid, when, amount, bank, method, acc, user in c.fetchall()
        ]


def balance(pk: int) -> dict[str, float]:
    """What the database itself says about the card (CALC_SERVCARDBAL): the same numbers FINISH_SERVCARDS checks."""
    with connection.cursor() as c:
        c.execute(
            "SELECT SALETOTAL, DISCOUNT, JTOTAL, DUETOTAL, TOTAL_NT, VAT_AMOUNT, WTOTAL, MATTOTAL, EMPWTOTAL "
            "FROM CALC_SERVCARDBAL(%s)",
            [pk],
        )
        row = c.fetchone()
    keys = ("sale_total", "discount", "paid", "due", "total", "vat", "works_total", "parts_total", "mechanic_total")
    return {k: round(float(v or 0), 2) for k, v in zip(keys, row or (), strict=False)}


def load(pk: int) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(
            f"SELECT {HEADER_SELECT} {HEADER_FROM} WHERE s.SERVCARD_ID = %s AND s.SERVCARD_TYPE = %s", [pk, AGGREGATE]
        )  # noqa: S608
        row = c.fetchone()
    if row is None:
        return None
    card = _header(row)
    card.update(works=_work_lines(pk), parts=_part_lines(pk), pays=payments(pk), totals=balance(pk))
    return card


def listing(filters: dict[str, str], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where = ["s.SERVCARD_TYPE = %s"]
    params: list[Any] = [AGGREGATE]
    if filters.get("status", "").isdigit():
        where.append("COALESCE(s.SERV_STATUS, 0) = %s")
        params.append(int(filters["status"]))
    if filters.get("mode") in ("sheet", "internal"):
        where.append("COALESCE(s.IS_EXPENSE, 'no') " + ("= 'yes'" if filters["mode"] == "internal" else "<> 'yes'"))
    if filters.get("plate"):
        where.append("UPPER(s.CAR_NO) LIKE UPPER(%s)")
        params.append(f"%{filters['plate']}%")
    if filters.get("org"):
        where.append("UPPER(cu.DESCRIPTION) LIKE UPPER(%s)")
        params.append(f"%{filters['org']}%")
    if filters.get("q"):
        like = f"%{filters['q']}%"
        where.append(
            "(s.DOC_NO LIKE %s OR UPPER(s.CAR_NO) LIKE UPPER(%s) OR UPPER(s.REQCUST_NAME) LIKE UPPER(%s) "
            "OR UPPER(cu.DESCRIPTION) LIKE UPPER(%s))"
        )
        params += [like] * 4
    clause = " WHERE " + " AND ".join(where)
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) {HEADER_FROM}{clause}", params)  # noqa: S608 - constants + parameters
        total = int(c.fetchone()[0])
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {HEADER_SELECT}, {WORKS_SUM}, {PARTS_SUM}, {PAID_SUM} "  # noqa: S608
            f"{HEADER_FROM}{clause} ORDER BY s.ENTRY_DATE DESC, s.SERVCARD_ID DESC",
            params,
        )
        rows = c.fetchall()
    n = len(HEADER_COLUMNS)
    out = []
    for row in rows:
        card = _header(row[:n])
        works, parts, paid = (float(v or 0) for v in row[n:])
        card.update(
            works_total=round(works, 2), parts_total=round(parts, 2), total=round(works + parts, 2), paid=round(paid, 2)
        )
        out.append(card)
    return out, total


# --- writing -----------------------------------------------------------------------------------------------------


def _item(c: Any, item_id: int) -> dict[str, Any]:
    c.execute(
        "SELECT i.INC_ACC, i.DESCRIPTION, i.BARCODE, "
        "(SELECT FIRST 1 b.BARCODES_ID FROM BARCODES b WHERE b.ITEMNAME_IDENT = i.ITEMNAME_IDENT) "
        "FROM ITEM i WHERE i.ITEM_ID = %s",
        [item_id],
    )
    row = c.fetchone()
    if row is None:
        raise RepairError("Сэлбэг (бараа) олдсонгүй.")
    income, name, barcode, barcode_id = row
    if not (income or "").strip():
        raise RepairError(f"«{_text(name) or _text(barcode)}» барааны орлогын данс тохируулаагүй байна.")
    return {"income": income.strip(), "name": _text(name) or _text(barcode) or "", "barcode_id": barcode_id}


def _employee(c: Any, emp_id: int) -> None:
    """A mechanic is a CUSTOMER flagged as an employee (that is what EMP_WORKS.EMP_IDENT points at)."""
    c.execute("SELECT 1 FROM CUSTOMER WHERE CUST_ID = %s AND EMPLOYEE = 'yes'", [emp_id])
    if c.fetchone() is None:
        raise RepairError("Засварчин олдсонгүй.")


def _clean_works(raw: Any) -> list[dict[str, Any]]:
    lines = _clean_lines(raw, "work_id", "Ажил")
    for line, src in zip(lines, raw or [], strict=True):
        line["mech_id"] = _optional_id(src.get("mech_id"), "Засварчин")
    return lines


def _clean_parts(raw: Any) -> list[dict[str, Any]]:
    lines = _clean_lines(raw, "item_id", "Сэлбэг")
    for line, src in zip(lines, raw or [], strict=True):
        line["date"] = _when(src.get("date")) if src.get("date") else None
    return lines


def _when(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T")).replace(tzinfo=None, microsecond=0)
    except ValueError as e:
        raise RepairError("Огнооны хэлбэр буруу байна.") from e


def parse(body: dict[str, Any]) -> dict[str, Any]:
    """Check a request body (the same fields as a repair sheet on the screen) and turn it into what is stored."""
    try:
        vehicle_id = int(body.get("vehicle_id") or 0)
    except (TypeError, ValueError):
        vehicle_id = 0
    if vehicle_id <= 0:
        raise RepairError("Автомашин сонгоно уу (vehicle_id).")
    car = vehicle(vehicle_id)
    if car is None:
        raise RepairError("Автомашин олдсонгүй.")
    if not car["car_id"]:
        raise RepairError("Автомашины марк бүртгэгдээгүй тул карт үүсгэх боломжгүй.")
    customer = cut(body.get("customer") or car["owner"], "customer")
    if not customer:
        raise RepairError("Үйлчлүүлэгчийн нэрийг бөглөнө үү.")
    works, parts = _clean_works(body.get("works")), _clean_parts(body.get("parts"))
    if not works and not parts:
        raise RepairError("Ажил эсвэл сэлбэгийн мөр нэмнэ үү.")
    internal = bool(body.get("internal"))
    garage = _number(body, "garage", 0, 1_000_000_000, "Гарааж") if body.get("garage_on") else 0
    odometer = body.get("odometer")
    return {
        "car": car,
        "customer": customer,
        "customer_id": _optional_id(body.get("customer_id"), "Харилцагч"),
        "branch_id": _optional_id(body.get("branch_id"), "Салбар"),
        "phone": cut(body.get("phone") or car["phone"], "phone"),
        "date_in": _when(body["date_in"]) if body.get("date_in") else datetime.now().replace(microsecond=0),
        "vat_on": bool(body.get("vat_on", True)),
        "odometer": int(str(odometer).strip()) if str(odometer or "").strip().isdigit() else None,
        "remark": str(body.get("remark") or "").strip()[: LIMITS["note"]],
        "warranty": bool(body.get("warranty")),
        "settle_later": bool(body.get("settle_later")),
        "internal": internal,
        "expense_acct": str(body.get("expense_acct") or "").strip()[:12] if internal else "",
        "card_no": str(body.get("card_no") or "").strip(),
        "garage": garage,
        "quote_id": _optional_id(body.get("quote_id"), "Үнийн санал"),
        "works": works,
        "parts": parts,
    }


def _card_id_of(c: Any, card_no: str) -> int | None:
    if not card_no:
        return None
    c.execute("SELECT DISCOUNT_CARD FROM DIS_CARD WHERE CARDNO = %s", [card_no])
    row = c.fetchone()
    if row is None:
        raise RepairError("Хөнгөлөлтийн карт олдсонгүй.")
    return int(row[0])


def _header_values(c: Any, data: dict[str, Any], user: str) -> dict[str, Any]:
    car = data["car"]
    garage = data["garage"]
    return {
        "REQCUST_NAME": data["customer"],
        "REQCUST_IDENT": data["customer_id"],
        "REQCUST_PHONE": data["phone"],
        "CAR_IDENT": car["car_id"],
        "CAROWNER_IDENT": car["id"],
        "CAR_NO": cut(car["plate"], "plate"),
        "KUZOV_NO": cut(car["body_no"], "body_no"),
        "ENGINE_TYPE": cut(car["engine_type"], "engine_type"),
        "VIN_NUMBER": cut(car["vin"], "vin"),
        "CAR_COLOR": cut(car["color"], "color"),
        "ENGINE_NUMBER": cut(car["engine_no"], "engine_no"),
        "CERTIFICATE": cut(car["certificate"], "certificate"),
        "DRIVER_NO": cut(car["driver_no"], "driver_no"),
        "MAKED_DATE": car["maked"],
        "SPECIFICATION": cut(car["spec"], "spec"),
        "MAKE_YEAR": car["year"],
        "ENTRY_DATE": data["date_in"],
        "SPEEDOMETER_REF": data["odometer"],
        "NOTE": data["remark"],
        "SHOCK_WARRANTY": "yes" if data["warranty"] else "no",
        "IS_RECIEVABLE": "yes" if data["settle_later"] else "no",
        "IS_EXPENSE": "yes" if data["internal"] else "no",
        "EXPENSE_ACC": data["expense_acct"] or None,
        "DISCOUNT_CARD": _card_id_of(c, data["card_no"]),
        "GARAGE_DAY": 1 if garage else None,
        "GARAGE_PRICE": garage or 0.0,  # the column refuses NULL
        "VAT_PERCENT": pricing.VAT_RATE if data["vat_on"] else 0.0,
        "BRANCH_IDENT": data["branch_id"],
        "PRICEVOTE_IDENT": data["quote_id"],
    }


def _write_lines(c: Any, pk: int, data: dict[str, Any]) -> None:
    now = datetime.now().replace(microsecond=0)
    for line in data["works"]:
        db = pricing.line_to_db(line, data["vat_on"])
        _insert(
            c,
            "SERVJOBS",
            {
                "SERVJOB_ID": _next_id(c, "GEN_SERVJOBS_ID"),
                "SERVCARD_IDENT": pk,
                "WORK_IDENT": line["ref"],
                "QUANTITY": db["QUANTITY"],
                "PRICE": db["PRICE"],
                "TOTAL": db["TOTAL"],
                "PRICE_NT": db["PRICE_NT"],
                "TOTAL_NT": db["TOTAL_NT"],
                "DISC_PERCENT": db["DISCOUNT"],
                "CARD_PERCENT": db["CARD_PERCENT"],
                "PROC_N": db["PROC_N"],
                "BASEPRICE": db["BASEPRICE"],
                "IS_OTHER": "no",
                "EMP_IDENT": line["mech_id"],
                "WTOTAL": 0.0,
                "IS_PEOPLETIME": 0,
                "CITYTAX": 0.0,
            },
        )
        if line["mech_id"]:
            _employee(c, line["mech_id"])
            rate = db["PROC_N"]
            _insert(
                c,
                "EMP_WORKS",
                {
                    # the mechanic's share is the whole undiscounted work (CALC_SERVCARDREP sums TOTAL_NT)
                    "EMP_IDENT": line["mech_id"],
                    "WORK_IDENT": line["ref"],
                    "MYEAR": now.year,
                    "MMONTH": now.month,
                    "SALTYPE": 1 if now.day > 15 else 0,  # second half of the month (FINISH_SERVCARDS does the same)
                    "DISC_PERCENT": 0.0,
                    "QUANTITY": db["QUANTITY"],
                    "PRICE": round(db["PRICE_NT"] / (1 + rate / 100), 6),
                    "TOTAL": round(db["TOTAL_NT"] / (1 + rate / 100), 6),
                    "PRICE_NT": db["PRICE_NT"],
                    "TOTAL_NT": db["TOTAL_NT"],
                    "PROC_N": rate,
                    "BASEPRICE": db["BASEPRICE"],
                    "SERVCARD_IDENT": pk,
                    "WDATE": now,
                    "FINISHED": "no",
                },
            )
    for line in data["parts"]:
        db = pricing.line_to_db(line, data["vat_on"])
        item = _item(c, line["ref"])
        stock = line["stock"]
        _insert(
            c,
            "SERV_TRANS",
            {
                "TRANS_ID": _next_id(c, "GEN_SERV_TRANS_ID"),
                "SERVCARD_IDENT": pk,
                "ITEM_IDENT": line["ref"],
                "TRANSDATE": line["date"] or now,
                "QUANTITY": db["QUANTITY"],
                "PRICE": db["PRICE"],
                "TOTAL": db["TOTAL"],
                "PRICE_NT": db["PRICE_NT"],
                "TOTAL_NT": db["TOTAL_NT"],
                "PROC_N": db["PROC_N"],
                "DISCOUNT": db["DISCOUNT"],
                "CARD_PERCENT": db["CARD_PERCENT"],
                # SERV_TRANS keeps the VAT of ONE unit (card 19315: quantity 4, 1075.14 = 10751.44 x 10 %)
                "VAT_AMOUNT": round(db["PRICE"] * db["PROC_N"] / 100, 6),
                "PRICE2": db["PRICE_NT"],
                "WHOLE_PRICE": 0.0,
                "BAL_QTY": float(stock) if isinstance(stock, int | float) else 0.0,
                "CRACC_NUM": item["income"],  # the item's income account (checked: all 270 existing rows)
                "DESCRIPTION": item["name"][: LIMITS["desc"]],
                "BARCODE_IDENT": item["barcode_id"],
                "CITYTAX": 0.0,
                "TAXTYPE": 1 if db["PROC_N"] else None,  # 1 on every line the desktop wrote with VAT
            },
        )


def _status(c: Any, pk: int) -> int | None:
    c.execute(
        "SELECT COALESCE(SERV_STATUS, 0) FROM SERVCARDS WHERE SERVCARD_ID = %s AND SERVCARD_TYPE = %s", [pk, AGGREGATE]
    )
    row = c.fetchone()
    return None if row is None else int(row[0])


def create(data: dict[str, Any], user: str) -> int:
    """Insert a not-started card with its lines (call inside a transaction). The number is the last numeric one + 1."""
    with connection.cursor() as c:
        # Some numbers are not numeric ('AGR-1'), so the highest number is taken here, not with a SQL CAST.
        c.execute("SELECT DOC_NO FROM SERVCARDS WHERE SERVCARD_TYPE = %s", [AGGREGATE])
        number = (
            max(
                (int(n.strip()) for (n,) in c.fetchall() if n and n.strip().isdigit() and len(n.strip()) < 10),
                default=0,
            )
            + 1
        )
        pk = _next_id(c, "GEN_SERVCARDS_ID")
        values = {
            "SERVCARD_ID": pk,
            "DOC_NO": cut(number, "doc_no"),
            "SERVCARD_TYPE": AGGREGATE,
            "SERV_STATUS": NOT_STARTED,
            "REG_USER": cut(user, "user"),
            # the zeros and flags the desktop program writes on a new card
            "DISCOUNT_PERCENT": 0.0,
            "DISCOUNT_TOTAL": 0.0,
            "DISC_PERCENT": 0.0,
            "CARD_AMT": 0.0,
            "CASH_AMT": 0.0,
            "IS_PTIME": "no",
            "USECUST_PRICE": 0,
        } | _header_values(c, data, user)
        _insert(c, "SERVCARDS", values)
        _write_lines(c, pk, data)
    return pk


def replace(pk: int, data: dict[str, Any], user: str) -> bool:
    """Rewrite a card (header and all lines). False when there is no such card; refused once it is finished."""
    with connection.cursor() as c:
        status = _status(c, pk)
        if status is None:
            return False
        if status == FINISHED:
            raise RepairLocked(DB_MESSAGES["SERVCARD_CANNOTEDIT"])
        header = _header_values(c, data, user)
        sets = ", ".join(f"{col} = %s" for col in header)
        c.execute(f"UPDATE SERVCARDS SET {sets} WHERE SERVCARD_ID = %s", [*header.values(), pk])  # noqa: S608 - constants
        # Removing a part makes its trigger mark the TRANSAC rows deleted (status 'D'), as the desktop program does;
        # the new parts below get fresh rows. Works are removed together with their EMP_WORKS.
        c.execute("DELETE FROM SERV_TRANS WHERE SERVCARD_IDENT = %s", [pk])
        c.execute("DELETE FROM SERVJOBS WHERE SERVCARD_IDENT = %s", [pk])
        c.execute("DELETE FROM EMP_WORKS WHERE SERVCARD_IDENT = %s", [pk])
        _write_lines(c, pk, data)
    return True


def delete(pk: int) -> bool:
    """Delete a card (the database removes its lines and refuses once a journal exists, see DB_MESSAGES)."""
    with connection.cursor() as c:
        status = _status(c, pk)
        if status is None:
            return False
        if status == FINISHED:
            raise RepairLocked("Дууссан картыг устгах боломжгүй.")
        c.execute("SELECT COUNT(*) FROM JOURNAL WHERE SERVCARD_IDENT = %s", [pk])
        if int(c.fetchone()[0]):
            raise RepairLocked("Төлбөр бүртгэгдсэн тул устгах боломжгүй. Эхлээд төлбөрийг устгана уу.")
        c.execute("DELETE FROM EMP_WORKS WHERE SERVCARD_IDENT = %s", [pk])
        c.execute("DELETE FROM SERV_TRANS WHERE SERVCARD_IDENT = %s", [pk])
        c.execute("DELETE FROM SERVJOBS WHERE SERVCARD_IDENT = %s", [pk])
        c.execute("DELETE FROM SERVCARDS WHERE SERVCARD_ID = %s", [pk])
    return True


def start(pk: int) -> bool:
    """Mark a not-started card as started now."""
    with connection.cursor() as c:
        status = _status(c, pk)
        if status is None:
            return False
        if status != NOT_STARTED:
            raise RepairError("Карт аль хэдийн эхэлсэн эсвэл дууссан байна.")
        c.execute(
            "UPDATE SERVCARDS SET STARTED_DATE = %s, SERV_STATUS = %s WHERE SERVCARD_ID = %s",
            [datetime.now().replace(microsecond=0), STARTED, pk],
        )
    return True


def finish(pk: int, when: datetime | None = None) -> bool:
    """Finish a card: set the exit date, then let FINISH_SERVCARDS do the checks and the status change."""
    with connection.cursor() as c:
        status = _status(c, pk)
        if status is None:
            return False
        if status == FINISHED:
            raise RepairError("Карт аль хэдийн дууссан байна.")
        exit_at = (when or datetime.now()).replace(microsecond=0)
        c.execute(
            "UPDATE SERVCARDS SET EXIT_DATE = %s, STARTED_DATE = COALESCE(STARTED_DATE, ENTRY_DATE) "
            "WHERE SERVCARD_ID = %s",
            [exit_at, pk],
        )
        c.execute("EXECUTE PROCEDURE FINISH_SERVCARDS(%s)", [pk])
    return True


def pay(pk: int, body: dict[str, Any], user: str) -> int:
    """Record a payment as the desktop program does: one JOURNAL row, debit the payment method's account
    (BANKS.RECACC), credit the receivable account (settings.AUTOSERVICE_RECEIVABLE_ACCOUNT), both for the
    card's customer."""
    amount = _number(body, "amount", 0.01, 1_000_000_000, "Төлбөрийн дүн")
    try:
        bank_id = int(str(body.get("bank_id")))
    except ValueError as e:
        raise RepairError("Төлбөрийн төрөл (bank_id) сонгоно уу.") from e
    with connection.cursor() as c:
        status = _status(c, pk)
        if status is None:
            raise RepairError("Карт олдсонгүй.")
        if status == FINISHED:
            raise RepairLocked(DB_MESSAGES["SERVCARD_CANNOTDELETE"])
        c.execute("SELECT RECACC FROM BANKS WHERE BANK_ID = %s", [bank_id])
        bank = c.fetchone()
        if bank is None or not (bank[0] or "").strip():
            raise RepairError("Төлбөрийн төрөл олдсонгүй эсвэл данс нь тохируулаагүй байна.")
        c.execute("SELECT DOC_NO, REQCUST_IDENT FROM SERVCARDS WHERE SERVCARD_ID = %s", [pk])
        doc_no, customer = c.fetchone()
        if customer is None:  # the desktop falls back to the company-wide customer of aggregate repairs
            c.execute("SELECT AGGREG_CUST FROM INFO")
            customer = c.fetchone()[0]
        due = balance(pk)["due"]
        if amount > due + 0.01:
            raise RepairError(f"Төлбөр үлдэгдлээс ({due:,.2f}) их байна.")
        jid = _next_id(c, "GEN_JOURNALID")
        _insert(
            c,
            "JOURNAL",
            {
                "JOURNAL_ID": jid,
                "JNUMBER": cut((doc_no or "").strip(), "doc_no"),
                "JDATE": datetime.now().replace(microsecond=0),
                "DBACC_NUM": bank[0].strip(),
                "CRACC_NUM": getattr(settings, "AUTOSERVICE_RECEIVABLE_ACCOUNT", "1207-001"),
                "DBCUST_IDENT": customer,
                "CRCUST_IDENT": customer,
                "JAMOUNT": amount,
                "JTYPE": 1,
                "JOURNALCODE": "GEN",
                "SERVCARD_IDENT": pk,
                "USER_NAME": (user or "")[: LIMITS["journal_user"]].upper(),
                "BANK_IDENT": bank_id,
            },
        )
    return jid


def remove_payment(pk: int, journal_id: int) -> bool:
    with connection.cursor() as c:
        c.execute(
            "SELECT COUNT(*) FROM JOURNAL WHERE JOURNAL_ID = %s AND SERVCARD_IDENT = %s AND JOURNALCODE = 'GEN'",
            [journal_id, pk],
        )
        if not int(c.fetchone()[0]):
            return False
        status = _status(c, pk)
        if status == FINISHED:
            raise RepairLocked(DB_MESSAGES["SERVCARD_CANNOTDELETE"])
        c.execute("DELETE FROM JOURNAL WHERE JOURNAL_ID = %s", [journal_id])
    return True


def banks() -> list[dict[str, Any]]:
    """Payment methods (BANKS rows that have an account): the choices of the payment dialog."""
    with connection.cursor() as c:
        c.execute("SELECT BANK_ID, DESCRIPTION, RECACC FROM BANKS WHERE RECACC IS NOT NULL ORDER BY BANK_ID")
        return [
            {"id": i, "name": _text(n) or "", "account": _text(a) or ""}
            for i, n, a in c.fetchall()
            if (a or "").strip()
        ]

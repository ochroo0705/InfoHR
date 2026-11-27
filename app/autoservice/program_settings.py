"""Program settings (Програмын тохируулга) as the desktop program keeps them in MACS. Read only.

  Үндсэн тохиргоо   INFO (one row; AGGREG_* for the aggregate shop, KUZOV_* for the body shop)
  VAT               SPRAVC, CODE 1 (the company's own row has no branch)
  Payment methods   BANKS (a method's account is BANKS.RECACC); the cash and bank accounts are *these*, not settings
  Advanced          MACS_OPTIONS, idents CARSERVICE_*; the user names come from SECURITY

The Advanced part is served separately (see views_settings) because it is only handed out after a password.
"""

from typing import Any

from django.db import connection

from autoservice import repairs
from autoservice.quotes import _text

SHOPS = {"agg": "AGGREG", "body": "KUZOV"}  # shop -> its prefix in INFO
SHOP_FIELDS = (  # INFO column suffix -> key in the answer
    ("INCACC", "income_account"),
    ("OTHERINCACC", "other_income_account"),
    ("ACCRP", "receivable_account"),
    ("ACC", "settlement_account"),
    ("DISCACC", "discount_account"),
    ("EXPACC", "expense_account"),
)
FLAGS = {  # MACS_OPTIONS ident -> key
    "CARSERVICE_SERVTRANS": "register_sales",
    "CARSERVICE_TELLERMODULE": "teller_module",
    "CARSERVICE_USEBANKACC": "use_bank_account",
    "CARSERVICE_EDITPRICE": "edit_price",
    "CARSERVICE_EDITDISCOUNT": "edit_discount",
}
USER_LISTS = {"CARSERVICE_EDITPRICE_USERS": "price_users", "CARSERVICE_EDITDISC_USERS": "discount_users"}


def _info_columns() -> list[str]:
    shop = [f"{p}_{suffix}" for p in SHOPS.values() for suffix, _ in SHOP_FIELDS]
    own = [f"{p}_{x}" for p in SHOPS.values() for x in ("CUST", "SEGMENT", "LASTNUMBER")]
    return [
        "COM_NAME", "LEGAL_NAME", "REGISTERNO", "TAXABLE", "BANKNAME", "BANKNUMBER", "CHKDATE", "STORE_ACC", "ACC1",
        *shop, *own,
    ]  # fmt: skip


def _names(sql: str, keys: set[Any]) -> dict[Any, str]:
    """{key: name} for the given keys, with one query (the sql ends in `IN (...)`)."""
    keys.discard(None)
    if not keys:
        return {}
    ids = list(keys)
    with connection.cursor() as c:
        c.execute(f"{sql} ({', '.join(['%s'] * len(ids))})", ids)  # noqa: S608 - constant sql, %s marks
        return {k.strip() if isinstance(k, str) else k: _text(n) or "" for k, n in c.fetchall()}


def _info() -> dict[str, Any]:
    cols = _info_columns()
    with connection.cursor() as c:
        c.execute(f"SELECT {', '.join(cols)} FROM INFO")  # noqa: S608 - column names are constants
        row = c.fetchone()
    return {k: (v.strip() if isinstance(v, str) else v) or None for k, v in zip(cols, row or (), strict=False)}


def _vat() -> dict[str, Any]:
    """The company's own VAT row (SPRAVC code 1, no branch): the account the journal posts VAT to."""
    with connection.cursor() as c:
        c.execute("SELECT ACCNO_IDENT, CUST_IDENT, PROCENT FROM SPRAVC WHERE CODE = 1 AND BRANCH_IDENT IS NULL")
        row = c.fetchone()
    return {"account": _text(row[0]), "customer_id": row[1], "percent": float(row[2] or 0)} if row else {}


def main() -> dict[str, Any]:
    """Company, main accounts, per-shop accounts and numbering, VAT and the payment methods."""
    info = _info()
    vat = _vat()
    accounts = {
        v for k, v in info.items() if k.endswith(("ACC", "ACCRP", "INCACC", "OTHERINCACC", "DISCACC", "EXPACC", "ACC1"))
    }
    accounts |= {vat.get("account")}
    account_names = _names("SELECT ACCNO, DESCRIPTION FROM ACCOUNT WHERE ACCNO IN", set(accounts))
    customer_ids = {info[f"{p}_CUST"] for p in SHOPS.values()} | {vat.get("customer_id")}
    customer_names = _names("SELECT CUST_ID, DESCRIPTION FROM CUSTOMER WHERE CUST_ID IN", set(customer_ids))

    def account(code: str | None) -> dict[str, str] | None:
        return {"number": code, "name": account_names.get(code, "")} if code else None

    def customer(cid: int | None) -> dict[str, Any] | None:
        return {"id": cid, "name": customer_names.get(cid, "")} if cid is not None else None

    shops: dict[str, Any] = {}
    for shop, p in SHOPS.items():
        last = int(info[f"{p}_LASTNUMBER"] or 0)
        segment = info[f"{p}_SEGMENT"] or ""
        shops[shop] = {key: account(info[f"{p}_{suffix}"]) for suffix, key in SHOP_FIELDS} | {
            "customer": customer(info[f"{p}_CUST"]),
            "segment": segment,
            "last_number": last,
            "next_number": last + 1,  # the "Баримт эхлэх дугаар" of the desktop screen
            "next_doc_no": f"{segment}{last + 1}",
        }
    closing = info["CHKDATE"]
    return {
        "company": {
            "name": info["COM_NAME"],
            "legal_name": info["LEGAL_NAME"],
            "register_no": info["REGISTERNO"],
            "taxable": info["TAXABLE"] == "yes",
            "bank_name": info["BANKNAME"],
            "bank_number": info["BANKNUMBER"],
            "closing_date": closing.isoformat() if closing else None,
        },
        "store_account": account(info["STORE_ACC"]),
        "asset_account": account(info["ACC1"]),
        "shops": shops,
        "vat": {
            "account": account(vat.get("account")),
            "customer": customer(vat.get("customer_id")),
            "percent": vat.get("percent", 0.0),
        },
        "payment_methods": repairs.banks(),
    }


def _flag(value: Any) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes")


def advanced() -> dict[str, Any]:
    """The Advanced tab: the switches, the users allowed to edit prices / discounts, and all user names."""
    with connection.cursor() as c:
        c.execute("SELECT IDENT, VAL FROM MACS_OPTIONS WHERE UPPER(IDENT) STARTING WITH 'CARSERVICE_'")
        values = {str(i).strip().upper(): v for i, v in c.fetchall()}
        c.execute("SELECT USER_NAME FROM SECURITY ORDER BY USER_NAME")
        users = [str(u).strip() for (u,) in c.fetchall()]
    options = {key: _flag(values.get(ident)) for ident, key in FLAGS.items()}
    lists = {
        key: [u.strip() for u in str(values.get(ident) or "").split(",") if u.strip()]
        for ident, key in USER_LISTS.items()
    }
    return {"options": options, **lists, "users": users}

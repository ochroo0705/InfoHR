"""How a quote line is stored in MACS (PRICEVOTEJOB / PRICEVOTEITEM) and how it is read back.

The screen works with ONE unit price that already includes VAT, plus a discount % and a card %.
MACS keeps, per line (checked against the existing rows of the Carservice database):
  PRICE_NT, TOTAL_NT, BASEPRICE  the VAT-included price, before discount (total = quantity x price)
  PRICE, TOTAL                   the price after discount, without VAT
  VAT_AMOUNT                     TOTAL x VAT rate
  DISCOUNT, CARD_PERCENT         the two percents;  PROC_N  the VAT rate used for the line (0 = no VAT)
What the customer pays for a line is TOTAL + VAT_AMOUNT = quantity x price x (1 - (discount + card) / 100).
"""

from typing import Any

VAT_RATE = 10.0  # percent; MACS stores the rate used on every row, this is the default for a new quote


def line_to_db(line: dict[str, Any], vat_on: bool, vat_rate: float = VAT_RATE) -> dict[str, float]:
    """Column values for one line. `line` has qty, price (VAT included), disc, card and vat (bool)."""
    qty, price = float(line["qty"]), float(line["price"])
    disc, card = float(line["disc"]), float(line["card"])
    rate = vat_rate if (vat_on and line["vat"]) else 0.0
    net_unit = price * (1 - (disc + card) / 100) / (1 + rate / 100)
    total = qty * net_unit
    return {
        "QUANTITY": qty,
        "PRICE": round(net_unit, 6),
        "TOTAL": round(total, 6),
        "DISCOUNT": disc,
        "CARD_PERCENT": card,
        "VAT_AMOUNT": round(total * rate / 100, 6),
        "PRICE_NT": price,
        "TOTAL_NT": round(qty * price, 6),
        "BASEPRICE": price,
        "PROC_N": rate,
    }


def line_from_db(
    quantity: Any, price: Any, discount: Any, card: Any, vat_amount: Any, price_nt: Any, baseprice: Any, rate: Any
) -> dict[str, Any]:
    """The screen's view of a stored line (price = VAT-included, before discount)."""
    shown = _f(price_nt) or _f(baseprice) or _f(price) * (1 + _f(rate) / 100)
    return {
        "qty": _f(quantity),
        "price": round(shown, 4),
        "disc": _f(discount),
        "card": _f(card),
        "vat": _f(vat_amount) > 0,
    }


def _f(v: Any) -> float:
    """A stored number as float; NULL means 0."""
    return float(v or 0)

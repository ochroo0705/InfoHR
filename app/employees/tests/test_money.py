from decimal import Decimal

from employees.money import MoneyField, MoneyInput, group
from employees.templatetags.hr import mnt


def test_group_uses_commas_and_drops_whole_decimals() -> None:
    assert group(Decimal("2500000.00")) == "2,500,000"
    assert group(Decimal("1234.5")) == "1,234.50"
    assert mnt(Decimal("2500000")) == "2,500,000₮"


def test_money_field_accepts_grouped_text() -> None:
    field = MoneyField()
    assert field.clean("2,500,000") == Decimal("2500000")
    assert field.clean(" 1 200.50 ") == Decimal("1200.50")


def test_money_input_renders_grouped_and_marked() -> None:
    html = MoneyInput().render("amount", Decimal("2500000.00"))
    assert 'value="2,500,000"' in html and "data-money" in html and 'type="text"' in html

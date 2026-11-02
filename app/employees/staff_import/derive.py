"""Birth date and gender read from a Mongolian register number (two letters, then 8 digits: YY MM DD NN)."""

from datetime import date

from employees.validators import REGISTER_NO, normalize_register_no


def derive_from_register(register_no: str) -> tuple[date | None, str | None]:
    """Return (birth date, "M" or "F") for a register number, or (None, None) if it does not parse to a real date.

    Digits are YY MM DD NN. A month above 20 means born in 2000 or later (month minus 20), otherwise 1900 or later.
    The gender digit is the seventh digit (the second to last of the eight): odd for a man, even for a woman. A birth
    date after today is rejected.
    """
    value = normalize_register_no(register_no)
    if not REGISTER_NO.match(value):
        return None, None
    digits = value[2:]
    year_part, month, day = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    if month > 20:
        year, month = 2000 + year_part, month - 20
    else:
        year = 1900 + year_part
    try:
        born = date(year, month, day)
    except ValueError:
        return None, None
    if born > date.today():
        return None, None
    gender = "M" if int(digits[6]) % 2 else "F"
    return born, gender

import re

from django.core.exceptions import ValidationError

REGISTER_NO = re.compile(r"^[А-ЯЁӨҮ]{2}\d{8}$")


def normalize_register_no(value: str) -> str:
    """Upper case, no spaces: ' уб 99112233 ' -> 'УБ99112233'."""
    return re.sub(r"\s+", "", value).upper()


def validate_register_no(value: str) -> None:
    if not REGISTER_NO.match(normalize_register_no(value)):
        raise ValidationError("Регистрийн дугаар 2 үсэг, 8 цифрээс бүрдэнэ (жишээ: УБ99112233).")

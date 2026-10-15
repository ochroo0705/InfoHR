"""Password rule (user decision 2026-10-15): at least one lowercase letter, one uppercase letter and one digit.
Length is checked by Django's MinimumLengthValidator (8)."""

from typing import Any

from django.core.exceptions import ValidationError


class CharacterClassesValidator:
    def validate(self, password: str, user: Any = None) -> None:
        if not (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            raise ValidationError("Том, жижиг үсэг, тоо тус бүр нэгээс доошгүй байна.", code="password_classes")

    def get_help_text(self) -> str:
        return "Том, жижиг үсэг, тоо тус бүр нэгээс доошгүй."

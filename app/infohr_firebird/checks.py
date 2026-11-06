"""Django system checks for the Firebird engine (firebird3-foundation plan, Task 10a).

Each registered check does nothing unless settings.DATABASES["default"]["ENGINE"] is infohr_firebird,
so the PostgreSQL run gets no output from this module. Only HR-owned models are checked: managed
models outside the MACS app (MACS tables are unmanaged mappings of the existing Firebird file).
The message builders take a list of model classes, so they can be tested on synthetic models.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.apps import apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register
from django.core.checks import Warning as CheckWarning
from django.db import connection, models
from macs.triggers import EXPECTED as MACS_TRIGGERS
from macs.triggers import missing as missing_macs_triggers

from infohr_firebird.emulated import EMULATED

ENGINE = "infohr_firebird"
MACS_APP_LABEL = "macs"
MAX_DECIMAL_DIGITS = 9  # dialect 1 stores wider NUMERIC as a double and returns floats
BIG_FIELD_TYPES = (models.BigIntegerField, models.PositiveBigIntegerField, models.DurationField)
AUTO_FIELD_TYPES = (models.AutoField, models.BigAutoField, models.SmallAutoField)  # ids are mapped on purpose


def _enabled() -> bool:
    return str(settings.DATABASES["default"]["ENGINE"]) == ENGINE


def _hr_fields(
    model_classes: Iterable[type[models.Model]],
) -> Iterator[tuple[type[models.Model], models.Field[Any, Any]]]:
    for model in model_classes:
        meta = model._meta
        if not meta.managed or meta.app_label == MACS_APP_LABEL:
            continue
        for field in meta.local_fields:
            yield model, field


def wide_decimal_messages(model_classes: Iterable[type[models.Model]]) -> list[CheckMessage]:
    messages: list[CheckMessage] = []
    for model, field in _hr_fields(model_classes):
        if (
            isinstance(field, models.DecimalField)
            and (field.max_digits or 0) > MAX_DECIMAL_DIGITS
            and not getattr(field, "exact_money", False)  # ExactMoneyField is stored as a double on purpose
        ):
            messages.append(
                CheckWarning(
                    f"{model._meta.label}.{field.name} is a DecimalField with max_digits={field.max_digits}.",
                    hint=(
                        f"Firebird SQL dialect 1 returns numbers with more than {MAX_DECIMAL_DIGITS} digits "
                        "as floats. Keep max_digits at 9 or less, or accept float rounding on this field."
                    ),
                    obj=model,
                    id="infohr_firebird.W001",
                )
            )
    return messages


def big_integer_messages(model_classes: Iterable[type[models.Model]]) -> list[CheckMessage]:
    messages: list[CheckMessage] = []
    for model, field in _hr_fields(model_classes):
        if not isinstance(field, BIG_FIELD_TYPES) or isinstance(field, AUTO_FIELD_TYPES):
            continue
        if isinstance(field, models.DurationField):
            hint = (
                "Firebird SQL dialect 1 has no BIGINT, and a DurationField stores microseconds that do not "
                "fit a 32-bit integer, so this column cannot be created."
            )
        else:
            hint = "Firebird SQL dialect 1 stores this as a 32-bit INTEGER: values above 2,147,483,647 overflow."
        messages.append(
            CheckWarning(
                f"{model._meta.label}.{field.name} is a {type(field).__name__}.",
                hint=hint,
                obj=model,
                id="infohr_firebird.W002",
            )
        )
    return messages


@register(Tags.models)
def check_wide_decimals(app_configs: object, **kwargs: object) -> list[CheckMessage]:
    if not _enabled():
        return []
    return wide_decimal_messages(apps.get_models(include_auto_created=True))


@register(Tags.models)
def check_big_integers(app_configs: object, **kwargs: object) -> list[CheckMessage]:
    if not _enabled():
        return []
    return big_integer_messages(apps.get_models(include_auto_created=True))


def unknown_conditional_unique_messages(model_classes: Iterable[type[models.Model]]) -> list[CheckMessage]:
    messages: list[CheckMessage] = []
    for model in model_classes:
        meta = model._meta
        if not meta.managed or meta.app_label == MACS_APP_LABEL:
            continue
        for constraint in meta.constraints:
            if not isinstance(constraint, models.UniqueConstraint) or constraint.condition is None:
                continue
            if constraint.name in EMULATED:
                continue
            messages.append(
                Error(
                    f"{meta.label} has the conditional unique constraint {constraint.name}, "
                    "which Firebird cannot create as a partial index.",
                    hint=(
                        f"Add {constraint.name} to EMULATED in app/infohr_firebird/emulated.py "
                        "(a UNIQUE index over a COMPUTED BY expression), then create it in the migration."
                    ),
                    obj=model,
                    id="infohr_firebird.E010",
                )
            )
    return messages


@register(Tags.models)
def check_conditional_unique(app_configs: object, **kwargs: object) -> list[CheckMessage]:
    if not _enabled():
        return []
    return unknown_conditional_unique_messages(apps.get_models(include_auto_created=True))


@register(Tags.models)
def check_table_prefix(app_configs: object, **kwargs: object) -> list[CheckMessage]:
    if not _enabled() or settings.HR_TABLE_PREFIX:
        return []
    return [
        Error(
            "HR_TABLE_PREFIX is empty while DB_ENGINE is firebird.",
            hint=(
                "The MACS database already has HR_* tables. Set DJANGO_HR_TABLE_PREFIX=IHR_ "
                "(the default in firebird mode) so HR tables never collide with them."
            ),
            id="infohr_firebird.E001",
        )
    ]


@register(Tags.database)
def check_macs_triggers(
    app_configs: object = None, databases: Collection[str] | None = None, **kwargs: object
) -> list[CheckMessage]:
    """E011: a MACS trigger that HR relies on is missing or inactive (macs.triggers.EXPECTED).

    Django calls every database check with databases=None when no database is being checked, so this
    returns [] then. It also returns [] outside Firebird mode, without querying anything.
    """
    if not _enabled() or not databases or "default" not in databases:
        return []
    names = missing_macs_triggers(*sorted(MACS_TRIGGERS))
    if not names:
        return []
    return [
        Error(
            f"MACS triggers missing or inactive: {', '.join(names)}.",
            hint=(
                "HR writes depend on these triggers. Activate them in the MACS Firebird database "
                "(ALTER TRIGGER <name> ACTIVE) or restore them from the MACS install. HR refuses writes until then."
            ),
            id="infohr_firebird.E011",
        )
    ]


PROJECT_ZONE = ZoneInfo("Asia/Ulaanbaatar")
MAX_SERVER_CLOCK_SKEW = timedelta(minutes=2)


def _ulaanbaatar_now() -> datetime:
    """The current time in the project zone, as a naive wall-clock value (the way Firebird stores TIMESTAMP)."""
    return datetime.now(PROJECT_ZONE).replace(tzinfo=None)


def _firebird_server_now() -> datetime:
    """The Firebird server clock. CURRENT_TIMESTAMP is the server's wall clock, in the server's zone."""
    with connection.cursor() as cursor:
        cursor.execute("select current_timestamp from rdb$database")
        value: datetime = cursor.fetchone()[0]
    return value


def server_time_zone_messages(server_now: datetime, local_now: datetime) -> list[CheckMessage]:
    """W011 when the server's wall clock differs from Asia/Ulaanbaatar wall clock by more than 2 minutes.

    Both values are naive wall-clock times. A tz-aware server value keeps its own wall clock on purpose: a server
    set to another zone shows that zone's wall clock, which is the mistake this check looks for.
    """
    server_naive = server_now.replace(tzinfo=None)
    if abs(server_naive - local_now) <= MAX_SERVER_CLOCK_SKEW:
        return []
    return [
        CheckWarning(
            f"The Firebird server clock reads {server_naive:%Y-%m-%d %H:%M:%S}, "
            f"but Asia/Ulaanbaatar time is {local_now:%Y-%m-%d %H:%M:%S}.",
            hint=(
                f"Server time {server_naive:%Y-%m-%d %H:%M:%S} and Ulaanbaatar time {local_now:%Y-%m-%d %H:%M:%S} "
                "differ; the Firebird server time zone must be Asia/Ulaanbaatar, or HR records and dates are wrong."
            ),
            id="infohr_firebird.W011",
        )
    ]


@register(Tags.database)
def check_server_time_zone(
    app_configs: object = None, databases: Collection[str] | None = None, **kwargs: object
) -> list[CheckMessage]:
    """W011: the Firebird server clock is not on Asia/Ulaanbaatar time. Runs only with the 'default' database."""
    if not _enabled() or not databases or "default" not in databases:
        return []
    return server_time_zone_messages(_firebird_server_now(), _ulaanbaatar_now())

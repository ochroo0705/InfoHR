"""Only employees/services/macs_writes.py may save or delete production rows (spec §2)."""

import inspect
import re
from pathlib import Path

from django.db import models
from macs import models as macs_models

APP = Path(__file__).resolve().parent.parent
# Every concrete model in macs.models (the production mirror), read from the module so new ones are covered.
MACS_NAMES = sorted(
    name
    for name, cls in vars(macs_models).items()
    if inspect.isclass(cls)
    and issubclass(cls, models.Model)
    and cls.__module__ == macs_models.__name__
    and not cls._meta.abstract
)
WRITE_OPS = r"create|bulk_create|bulk_update|update_or_create|get_or_create|update|delete|save|in_bulk_update"
WRITE = re.compile(
    r"\b(" + "|".join(MACS_NAMES) + r")\.(objects|_default_manager|_base_manager)\.(" + WRITE_OPS + r")\b"
)
# Queryset writes chained on one line after a macs model name, e.g. Employee.objects.filter(...).update(...).
CHAIN_WRITE = re.compile(r"\b(" + "|".join(MACS_NAMES) + r")\b.*\.(update|delete|bulk_update)\(")
ALLOWED = {
    APP / "employees" / "services" / "macs_writes.py",  # employee-side production writes (spec §2)
    APP / "leave" / "services" / "writes.py",  # leave-side production writes: the one write layer for leave tables
    APP / "employees" / "services" / "personal_writes.py",  # personal-list production writes (family, educ, talents...)
}


def _sources() -> list[Path]:
    return [
        p
        for p in APP.rglob("*.py")
        if "migrations" not in p.parts
        and "tests" not in p.parts
        and p.parent.name != "tests_guard"
        and p not in ALLOWED
    ]


def test_macs_model_list_is_not_empty() -> None:
    assert {"Employee", "Department", "Position", "Country", "MaritalStatus"} <= set(MACS_NAMES)


def test_no_production_writes_outside_macs_writes() -> None:
    offenders = [
        f"{p}:{i}"
        for p in _sources()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if WRITE.search(line)
    ]
    assert offenders == []


def test_no_queryset_chain_writes_on_macs_models_outside_macs_writes() -> None:
    # Same-line chains such as Employee.objects.filter(...).update(...). Instance save()/delete() on macs
    # objects cannot be found by a text scan; they are covered by review of macs_writes callers (see Baton).
    offenders = [
        f"{p}:{i}"
        for p in _sources()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if CHAIN_WRITE.search(line)
    ]
    assert offenders == []


CUSTOMER_WRITER = APP / "employees" / "services" / "macs_writes.py"  # hire row + address copy (D-024)


def test_only_macs_writes_touches_customer_and_nothing_deletes_employees() -> None:
    never = re.compile(r"delete\s+from\s+(employee|customer)\b", re.I)
    customer = re.compile(r"\bcustomer\b", re.I)
    offenders = []
    for p in APP.rglob("*.py"):
        if "migrations" in p.parts or "tests" in p.parts or p.parent.name == "tests_guard":
            continue
        text = p.read_text(encoding="utf-8")
        if never.search(text) or (p != CUSTOMER_WRITER and customer.search(text)):
            offenders.append(str(p))
    assert offenders == []

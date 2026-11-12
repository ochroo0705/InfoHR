"""The reviewed descriptions of the governed views: one TOML file per view in hr_sql/descriptions/.

A file says what a view and its columns mean, in English and Mongolian, with the business rules a question needs. A
file is a draft until `reviewed_by` and `reviewed_on` are set; only the domain owner signs (`sign` below, through the
governed_descriptions command). The column names must match hr_sql/views.py exactly; the loader checks that.
"""

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from sqlcore.catalogue import Column, View

from hr_sql.views import view_columns

DESCRIPTIONS_DIR = Path(__file__).resolve().parent / "descriptions"
_SIGNER_FORBIDDEN = re.compile(r'["\\\r\n]')


def _path(name: str) -> Path:
    return DESCRIPTIONS_DIR / f"{name.strip().lower()}.toml"


def _text(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{path.name}: key {key!r} must be text")
    return value


def _texts(data: dict[str, Any], key: str, path: Path) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path.name}: key {key!r} must be a list of text")
    return tuple(value)


def load_view(name: str) -> View:
    """The described view `name`, with its columns in the view's own order. Raises ValueError naming the file and the
    key when the file is missing, does not parse, or does not match the view's columns."""
    key = name.strip().upper()
    columns = view_columns()
    if key not in columns:
        raise ValueError(f"{key}: not a governed view")
    path = _path(key)
    if not path.is_file():
        raise ValueError(f"{path.name}: the description file for {key} is missing")
    with path.open("rb") as handle:
        try:
            data: dict[str, Any] = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"{path.name}: does not parse: {error}") from error

    described: dict[str, Column] = {}
    tables = data.get("columns", [])
    if not isinstance(tables, list):
        raise ValueError(f"{path.name}: 'columns' must be a list of [[columns]] tables")
    for table in tables:
        column_name = table.get("name")
        if not isinstance(column_name, str) or not column_name:
            raise ValueError(f"{path.name}: a [[columns]] table has no 'name'")
        if column_name in described:
            raise ValueError(f"{path.name}: column {column_name} is listed twice")
        described[column_name] = Column(
            name=column_name,
            description=_text(table, "description", path),
            synonyms=_texts(table, "synonyms", path),
            description_mn=_text(table, "description_mn", path),
            label_mn=_text(table, "label_mn", path),
        )

    expected = columns[key]
    for column_name in expected:
        if column_name not in described:
            raise ValueError(f"{path.name}: no [[columns]] entry named {column_name} for view {key}")
    for column_name in described:
        if column_name not in expected:
            raise ValueError(f"{path.name}: column {column_name} is not a column of view {key}")

    return View(
        name=key,
        description=_text(data, "description", path),
        columns=tuple(described[column_name] for column_name in expected),
        description_mn=_text(data, "description_mn", path),
        rules=_texts(data, "rules", path),
        reviewed_by=_text(data, "reviewed_by", path),
        reviewed_on=_text(data, "reviewed_on", path),
    )


def load_all() -> dict[str, View]:
    return {name: load_view(name) for name in view_columns()}


def draft_views() -> list[str]:
    """The governed views whose description is not signed yet (reviewed_by is empty)."""
    return [name for name in view_columns() if not load_view(name).reviewed_by]


def sign(name: str, by: str, on: date) -> None:
    """Write the signer and the date into the view's file. The only way a file becomes signed.

    Only the two top-level keys change; the rest of the file is kept as it is. The new text must still parse, or
    nothing is written.
    """
    who = by.strip()
    if not who:
        raise ValueError("the signer's name is empty; give the name of the domain owner")
    if _SIGNER_FORBIDDEN.search(who):
        raise ValueError("the signer's name may not contain quotes, backslashes or line breaks")
    key = name.strip().upper()
    load_view(key)  # an unknown or broken file is refused before anything is written
    path = _path(key)
    text = path.read_text(encoding="utf-8")
    text, by_count = re.subn(r'^reviewed_by = ".*"$', f'reviewed_by = "{who}"', text, count=1, flags=re.MULTILINE)
    text, on_count = re.subn(
        r'^reviewed_on = ".*"$', f'reviewed_on = "{on.isoformat()}"', text, count=1, flags=re.MULTILINE
    )
    if by_count != 1 or on_count != 1:
        raise ValueError(f"{path.name}: the reviewed_by and reviewed_on lines were not found")
    tomllib.loads(text)
    path.write_text(text, encoding="utf-8")

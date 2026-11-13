"""The view descriptions are reviewed files (hr_sql/descriptions/*.toml). These tests need no database: they read the
files, the view definitions in hr_sql/views.py, and the catalogue built from them.
"""

import re
import shutil
import tomllib
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from hr_sql import descriptions
from hr_sql.catalogue import EMPLOYEES, catalogue_for
from hr_sql.descriptions import DESCRIPTIONS_DIR, draft_views, load_all, load_view
from hr_sql.management.commands.governed_descriptions import Command
from hr_sql.views import view_columns

ALL_VIEWS = [
    "GOV_EMPLOYEES",
    "GOV_CHILDREN",
    "GOV_LEAVE",
    "GOV_ORDERS",
    "GOV_SALARY",
    "GOV_LOANS",
]


@pytest.fixture
def copy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throw-away copy of the description files, with every sign-off blanked (all views are drafts), so the tests do
    not depend on whether the real files have been signed. The loader reads the copy for the test."""
    target = tmp_path / "descriptions"
    shutil.copytree(DESCRIPTIONS_DIR, target)
    for path in target.glob("*.toml"):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r'(?m)^reviewed_by = ".*"$', 'reviewed_by = ""', text)
        text = re.sub(r'(?m)^reviewed_on = ".*"$', 'reviewed_on = ""', text)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(descriptions, "DESCRIPTIONS_DIR", target)
    yield target


def test_every_governed_view_has_a_file() -> None:
    assert sorted(view_columns()) == sorted(ALL_VIEWS)
    for name in view_columns():
        assert (DESCRIPTIONS_DIR / f"{name.lower()}.toml").is_file(), name


def test_every_column_of_every_view_is_described_in_both_languages() -> None:
    for name, view in load_all().items():
        assert view.description, name
        assert view.description_mn, name
        assert [column.name for column in view.columns] == list(view_columns()[name])
        for column in view.columns:
            assert column.description, f"{name}.{column.name}"
            assert column.description_mn, f"{name}.{column.name}"


def test_no_file_describes_a_column_the_view_lacks() -> None:
    for name, columns in view_columns().items():
        with (DESCRIPTIONS_DIR / f"{name.lower()}.toml").open("rb") as handle:
            data: dict[str, Any] = tomllib.load(handle)
        listed = [table["name"] for table in data["columns"]]
        assert sorted(listed) == sorted(columns), name


def test_loader_names_file_and_key_on_error(copy_dir: Path) -> None:
    path = copy_dir / "gov_employees.toml"
    path.write_text(path.read_text(encoding="utf-8").replace('name = "FIRST_NAME"', 'name = "FIRST_NAMEX"'), "utf-8")

    with pytest.raises(ValueError, match="gov_employees.toml") as caught:
        load_view("GOV_EMPLOYEES")

    assert "FIRST_NAME" in str(caught.value)


def test_draft_views_lists_unsigned_files(copy_dir: Path) -> None:
    assert draft_views() == ALL_VIEWS

    leave = copy_dir / "gov_leave.toml"
    text = leave.read_text(encoding="utf-8")
    leave.write_text(text.replace('reviewed_by = ""', 'reviewed_by = "Test Name"', 1), encoding="utf-8")

    assert "GOV_LEAVE" not in draft_views()
    assert len(draft_views()) == len(ALL_VIEWS) - 1


class _StubUser:
    is_active = True

    def has_perm(self, perm: str) -> bool:
        return perm in {"macs.view_employees", "macs.view_personal", "macs.view_salary"}


def test_catalogue_for_uses_the_file_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hr_sql.catalogue.own_employee", lambda user: None)
    catalogue = catalogue_for(_StubUser())  # type: ignore[arg-type]

    for name in ALL_VIEWS:
        view = catalogue.get(name)
        assert view is not None, name
        expected = load_view(name)
        assert view.description == expected.description
        assert [column.description for column in view.columns] == [column.description for column in expected.columns]
    assert catalogue.get("GOV_EMPLOYEES") is not None
    assert EMPLOYEES.description == load_view("GOV_EMPLOYEES").description


def test_status_lists_each_view_as_draft(copy_dir: Path) -> None:
    out = StringIO()

    call_command(Command(), "status", stdout=out)

    for name in ALL_VIEWS:
        assert name in out.getvalue()
    assert "draft" in out.getvalue()


def test_sign_refuses_an_empty_name(copy_dir: Path) -> None:
    with pytest.raises(CommandError):
        call_command(Command(), "sign", "GOV_LEAVE", "--by", "   ", stdout=StringIO())

    assert "GOV_LEAVE" in draft_views()


def test_sign_writes_name_and_date(copy_dir: Path) -> None:
    call_command(Command(), "sign", "GOV_LEAVE", "--by", "Test Name", stdout=StringIO())

    view = load_view("GOV_LEAVE")
    assert view.reviewed_by == "Test Name"
    assert len(view.reviewed_on) == 10  # YYYY-MM-DD
    assert "GOV_LEAVE" not in draft_views()
    assert "GOV_EMPLOYEES" in draft_views()

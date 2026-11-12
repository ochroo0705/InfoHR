"""The grants script (scripts/grant_governed_fb.sql) against the governed objects in hr_sql/views.py. No database.

The script must give the read-only login SELECT on every governed view, SELECT, INSERT and DELETE on GOV_SCOPE, and
nothing else: no other privilege, no other object, no other statement.
"""

import re
from pathlib import Path

from hr_sql.views import view_columns

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "grant_governed_fb.sql"
GRANT = re.compile(r"GRANT\s+(?P<rights>[A-Z, ]+?)\s+ON\s+(?P<object>\w+)\s+TO\s+(?P<user>\w+)", re.IGNORECASE)
SCOPE_RIGHTS = {"SELECT", "INSERT", "DELETE"}
VIEW_RIGHTS = {"SELECT"}


def _statements() -> list[str]:
    """The script's statements: comments removed, split on semicolons, blanks dropped."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    text = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    return [part.strip() for part in text.split(";") if part.strip()]


def _grants() -> list[tuple[set[str], str, str]]:
    found = []
    for statement in _statements():
        match = GRANT.fullmatch(statement)
        if match:
            rights = {right.strip().upper() for right in match.group("rights").split(",")}
            found.append((rights, match.group("object").upper(), match.group("user").upper()))
    return found


def test_script_grants_select_on_every_governed_view() -> None:
    granted = {obj: rights for rights, obj, _ in _grants() if obj != "GOV_SCOPE"}
    for view in view_columns():
        assert view != "GOV_SCOPE"
        assert granted.get(view) == VIEW_RIGHTS, f"{view} needs SELECT in the script"


def test_script_grants_scope_table_select_insert_delete() -> None:
    granted = {obj: rights for rights, obj, _ in _grants()}
    assert granted.get("GOV_SCOPE") == SCOPE_RIGHTS


def test_every_view_name_in_the_view_headers_appears_in_a_grant_line() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    grant_lines = [line for line in text.splitlines() if line.lstrip().upper().startswith("GRANT")]
    for view in view_columns():
        assert any(re.search(rf"\b{view}\b", line) for line in grant_lines), view


def test_script_grants_nothing_else() -> None:
    allowed_objects = set(view_columns()) | {"GOV_SCOPE"}
    for statement in _statements():
        if statement.upper() == "COMMIT":
            continue
        match = GRANT.fullmatch(statement)
        assert match is not None, f"not a plain GRANT or COMMIT: {statement!r}"
        rights = {right.strip().upper() for right in match.group("rights").split(",")}
        obj = match.group("object").upper()
        assert obj in allowed_objects, f"GRANT on something that is not a governed object: {obj}"
        assert obj.startswith("GOV_"), obj
        assert rights <= SCOPE_RIGHTS, f"forbidden right in {statement!r}"
        assert rights <= (SCOPE_RIGHTS if obj == "GOV_SCOPE" else VIEW_RIGHTS), statement
        assert match.group("user").upper() == "MACS_GOV_RT", statement


def test_script_header_names_all_six_views() -> None:
    header = "\n".join(line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if line.startswith("--"))
    assert "two governed views" not in header
    assert "six governed views" in header

"""The core must not reach into HR code or a database. This test enforces it by reading the imports."""

import ast
from pathlib import Path

BANNED = {
    "accounts",
    "employees",
    "reports",
    "assistant",
    "macs",
    "leave",
    "lists",
    "checklists",
    "recruitment",
    "config",
    "django",
}

CORE_DIR = Path(__file__).resolve().parent.parent


def _core_source_files() -> list[Path]:
    files = []
    for path in CORE_DIR.rglob("*.py"):
        if "tests" in path.relative_to(CORE_DIR).parts:
            continue
        files.append(path)
    return files


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_core_imports_nothing_from_hr() -> None:
    files = _core_source_files()
    assert files, "the boundary walk found no .py files under app/sqlcore; the test would pass by scanning nothing"

    offenders: dict[str, set[str]] = {}
    for path in files:
        found = _imported_top_level_modules(path) & BANNED
        if found:
            offenders[str(path.relative_to(CORE_DIR))] = found

    assert offenders == {}

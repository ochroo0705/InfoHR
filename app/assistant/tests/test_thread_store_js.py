"""The browser-side thread store (app/static/js/thread_store.js) keeps its unit tests in Node; this runs them."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "app" / "static" / "js" / "thread_store.test.mjs"


def test_thread_store_unit_tests_pass() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        ["node", "--test", str(SCRIPT)],  # noqa: S607 - node from PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

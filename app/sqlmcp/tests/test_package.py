import subprocess
import sys
from pathlib import Path

import sqlmcp

APP_DIR = Path(__file__).resolve().parents[2]


def test_version_and_name() -> None:
    assert sqlmcp.SQL_MCP_VERSION == "1.0"
    assert sqlmcp.SERVER_NAME == "macs-governed-sql"


def test_no_django_import() -> None:
    result = subprocess.run(  # noqa: S603  (fixed argv: this interpreter, no user input)
        [sys.executable, "-c", "import sqlmcp, sys; assert 'django' not in sys.modules"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

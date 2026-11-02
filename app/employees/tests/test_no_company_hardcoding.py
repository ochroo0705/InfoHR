"""No customer's name is written into the product (D-043, D-053): company facts are per-install settings."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2]
NAMES = ("infosystems", "инфосистемс")
SKIP_PARTS = {"tests", "__pycache__", "migrations", "node_modules"}


def test_no_customer_name_in_the_application_code() -> None:
    found = [
        str(path.relative_to(APP))
        for pattern in ("*.py", "*.html", "*.js", "*.po")
        for path in APP.rglob(pattern)
        if not SKIP_PARTS & set(path.relative_to(APP).parts)
        and any(name in path.read_text(encoding="utf-8", errors="ignore").lower() for name in NAMES)
    ]
    assert not found, f"a customer's name is hard-coded in: {found}"

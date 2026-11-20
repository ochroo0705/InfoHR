from __future__ import annotations

from pathlib import Path

import pytest

from front_server.static import is_ported, load_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "web" / "dist"
MANIFEST = DIST_DIR / "ported.json"

PORTED_SAMPLES = ["/employees/orders/print/", "/", "/employees/12/", "/me/"]
UNPORTED_SAMPLES = ["/employees/12/edit/", "/leave/", "/api/v1/meta", "/employees/orders/print/x"]


@pytest.mark.skipif(
    not MANIFEST.is_file(),
    reason="web/dist/ported.json is absent: run npm run build in web/ to create it",
)
@pytest.mark.parametrize("path", PORTED_SAMPLES)
def test_ported_path_matches_in_python(path: str) -> None:
    assert is_ported(path, load_patterns(DIST_DIR))


@pytest.mark.skipif(
    not MANIFEST.is_file(),
    reason="web/dist/ported.json is absent: run npm run build in web/ to create it",
)
@pytest.mark.parametrize("path", UNPORTED_SAMPLES)
def test_unported_path_does_not_match_in_python(path: str) -> None:
    assert not is_ported(path, load_patterns(DIST_DIR))

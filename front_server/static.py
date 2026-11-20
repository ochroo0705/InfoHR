from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response

ASSET_PREFIX = "/assets/"
FONT_PREFIX = "/fonts/"
ASSET_CACHE = "public, max-age=31536000, immutable"
FONT_CACHE = "public, max-age=86400"
INDEX_CACHE = "no-cache"
MISSING_BUILD_TEXT = "Run npm run build in web/"


def load_patterns(dist_dir: Path) -> list[re.Pattern[str]]:
    """Compile the regex sources that the web build wrote to ported.json."""
    manifest = dist_dir / "ported.json"
    if not manifest.is_file():
        return []
    sources: list[str] = json.loads(manifest.read_text(encoding="utf-8"))
    return [re.compile(source) for source in sources]


def is_ported(path: str, patterns: list[re.Pattern[str]]) -> bool:
    """True when the path (without query string) is a React-ported route."""
    return any(pattern.search(path) for pattern in patterns)


def _file_under(root: Path, relative: str) -> Path | None:
    """Return the file at root/relative, or None if it is missing or resolves outside root."""
    try:
        base = root.resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            return None
    except (OSError, ValueError):
        return None
    return candidate


async def serve_static(request: Request, dist_dir: Path, patterns: list[re.Pattern[str]]) -> Response | None:
    """Answer a GET/HEAD the static side owns; return None so the caller can pass it on."""
    if request.method not in ("GET", "HEAD"):
        return None
    path = request.url.path
    if path.startswith(ASSET_PREFIX) or path.startswith(FONT_PREFIX):
        cache = ASSET_CACHE if path.startswith(ASSET_PREFIX) else FONT_CACHE
        prefix = ASSET_PREFIX if path.startswith(ASSET_PREFIX) else FONT_PREFIX
        folder = dist_dir / prefix.strip("/")
        found = _file_under(folder, path[len(prefix) :])
        if found is None:
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(found, headers={"Cache-Control": cache})
    if is_ported(path, patterns):
        index = _file_under(dist_dir, "index.html")
        if index is None:
            return PlainTextResponse(MISSING_BUILD_TEXT, status_code=503)
        return FileResponse(index, headers={"Cache-Control": INDEX_CACHE})
    return None

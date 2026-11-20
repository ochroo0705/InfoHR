from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from front_server.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8080"
DEFAULT_DJANGO_URL = "http://127.0.0.1:8000"
DEFAULT_WEB_DIST = "web/dist"


def main() -> None:
    """Read the four FRONT_* / DJANGO_URL / WEB_DIST variables and serve until stopped."""
    host = os.environ.get("FRONT_HOST", DEFAULT_HOST)
    port = int(os.environ.get("FRONT_PORT", DEFAULT_PORT))
    django_url = os.environ.get("DJANGO_URL", DEFAULT_DJANGO_URL)
    # A relative WEB_DIST is taken from the repo root, not from the current folder.
    dist_dir = REPO_ROOT / os.environ.get("WEB_DIST", DEFAULT_WEB_DIST)
    app = create_app(dist_dir, django_url)
    # proxy_headers=False: uvicorn would rewrite the client address from a client-supplied
    # X-Forwarded-For when the peer is in forwarded_allow_ips (default 127.0.0.1), and the proxy
    # would then forward that value to Django. The explicit False is still right.
    uvicorn.run(app, host=host, port=port, proxy_headers=False)


if __name__ == "__main__":
    main()

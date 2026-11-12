"""Run the HR MCP server (governed SQL over Streamable HTTP) with uvicorn."""

from __future__ import annotations

from typing import Any

import uvicorn
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from hr_mcp.app import make_app


class Command(BaseCommand):
    help = "Run the MCP server. Off unless MCP_ENABLED=true; binds 127.0.0.1:8765 by default."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--host", default=settings.MCP_BIND_HOST, help="Bind address.")
        parser.add_argument("--port", type=int, default=settings.MCP_BIND_PORT, help="Bind port.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.MCP_ENABLED:
            raise CommandError("The MCP server is turned off. Set MCP_ENABLED=true to run it.")
        uvicorn.run(make_app(), host=options["host"], port=options["port"], log_level="info")

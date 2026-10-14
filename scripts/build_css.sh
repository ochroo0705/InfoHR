#!/usr/bin/env bash
# Build app/static/css/app.css with the Tailwind standalone CLI (tools/tailwindcss.exe).
set -euo pipefail
cd "$(dirname "$0")/.."
tools/tailwindcss.exe -i app/static/css/input.css -o app/static/css/app.css --minify "$@"

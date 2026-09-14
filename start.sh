#!/usr/bin/env bash
# One-command start for the PeopleSoft emulator. Seeds the demo org on first run.
# Usage: ./start.sh [port]      env overrides: see .env.example
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then echo "python3 (3.9+) is required"; exit 1; fi
[ -f .env ] || cp .env.example .env
export PS_PORT="${1:-${PS_PORT:-8080}}"
exec python3 -m peopleschoft serve --port "$PS_PORT"

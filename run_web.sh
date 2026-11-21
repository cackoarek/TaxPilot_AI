#!/usr/bin/env bash
# ==============================================================================
# TaxPilot AI - Launcher Serwera Webowego
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_BIN="python"
else
    PYTHON_BIN="python3"
fi

echo "🚀 Uruchamianie TaxPilot AI Web UI..."
echo "📍 Adres: http://127.0.0.1:8000"
echo "💡 Użyty interpreter: $PYTHON_BIN"
echo "--------------------------------------------------"

exec "$PYTHON_BIN" -m uvicorn src.web.app:app --reload --reload-dir src --reload-delay 1.0 --host 127.0.0.1 --port 8000 "$@"

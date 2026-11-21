#!/usr/bin/env bash
# examples/pages/regenerate_pages.sh
# Skrypt do szybkiej regeneracji stron demonstracyjnych HTML w katalogu examples/pages/
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${ROOT_DIR}"

PYTHON_BIN="python3"
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

echo "=========================================================="
echo "🔄 Regeneracja pakietu stron demo TaxPilot AI dla GitHub Pages"
echo "=========================================================="

${PYTHON_BIN} scripts/export_demo_pages.py --output "${SCRIPT_DIR}"

echo ""
echo "✅ Gotowe! Strony zaktualizowane w: ${SCRIPT_DIR}"

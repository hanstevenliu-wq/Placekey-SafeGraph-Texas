#!/usr/bin/env bash
# Daily SafeGraph Texas geocoding pipeline (Cursor automation).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

"$PYTHON" geocode.py
"$PYTHON" send_report.py
"$PYTHON" reschedule_automation.py
"$PYTHON" merge_pr.py

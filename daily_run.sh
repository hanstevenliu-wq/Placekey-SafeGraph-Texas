#!/usr/bin/env bash
# Daily SafeGraph Texas geocoding pipeline (Cursor automation).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

"$PYTHON" geocode.py

if [ -f geocoded_results.csv ]; then
  rows=$(( $(wc -l < geocoded_results.csv) - 1 ))
  echo "geocoded_results.csv: ${rows} data rows"
else
  echo "geocoded_results.csv: missing (no successful geocodes yet)" >&2
fi

"$PYTHON" send_report.py
"$PYTHON" reschedule_automation.py
"$PYTHON" merge_pr.py

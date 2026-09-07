#!/usr/bin/env bash
# JobRadar delivery chain: pull latest S3 postings -> run the scoring funnel ->
# append new ranked jobs to Google Sheets. Meant to be driven by jobradar.timer.
#
# fail-fast: if any stage exits non-zero the whole chain stops. This is
# intentional - fetch_latest_postings.py exits non-zero when S3 is empty or
# unreachable, and we do NOT want the funnel/delivery running on stale data.
set -euo pipefail

# Resolve the repo dir from this script's own location, so the wrapper works
# wherever the repo is checked out (no hardcoded path to keep in sync).
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Interpreter. Plain python3 picks up user-site deps under systemd's default
# PATH. If you run the project from a venv, set this to that venv's python.
PYTHON="${JOBRADAR_PYTHON:-python3}"

cd "$PROJECT_DIR"

echo "=== chain start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
"$PYTHON" fetch_latest_postings.py
"$PYTHON" run_funnel_local.py
"$PYTHON" deliver_to_sheets.py
echo "=== chain done  $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

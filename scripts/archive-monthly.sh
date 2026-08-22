#!/usr/bin/env bash
# Monthly Overture archive. Intended to be run by cron.
#
# WHY THIS IS THE MOST URGENT JOB IN THE PROJECT.
# Overture's S3 retains roughly two releases and the community mirror lags by
# months. A release missing from both is gone permanently — 2026-06-17.0
# already is. Every month this does not run is citywide history that cannot be
# recovered at any later date, and that history is the product's differentiator.
#
# It writes a heartbeat file on success so a missed month is detectable rather
# than silent. `scripts/archive-status.sh` reads it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/.dev-logs}"
STAMP_FILE="$LOG_DIR/archive-last-success"
LOG="$LOG_DIR/archive-$(date +%Y-%m).log"

mkdir -p "$LOG_DIR"

# Under cron there is no terminal, so everything goes to the log. Run by hand,
# it goes to BOTH — a manual run that prints nothing looks hung, and this is a
# job people will want to watch the first time.
run() {
  echo "=== $(date -Is) starting archive_release.py ==="
  cd "$ROOT"
  if [ ! -x .venv/bin/python ]; then
    echo "FATAL: .venv/bin/python not found. Cron does not inherit your shell,"
    echo "       and this script deliberately uses the venv interpreter directly."
    exit 1
  fi
  .venv/bin/python -u pipeline/sources/archive_release.py
  echo "=== $(date -Is) completed ok ==="
}

if [ -t 1 ]; then
  run 2>&1 | tee -a "$LOG"
  # tee's exit status is not the script's; check the real one.
  status=${PIPESTATUS[0]}
  [ "$status" -eq 0 ] || exit "$status"
else
  run >>"$LOG" 2>&1
fi

# Only written when the run exits 0, so its date is the last KNOWN-GOOD run.
date -Is >"$STAMP_FILE"

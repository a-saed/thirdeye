#!/usr/bin/env bash
# Did the monthly archive actually fire? Run this any time.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/.dev-logs}"
STAMP_FILE="$LOG_DIR/archive-last-success"

if [ -t 1 ]; then AMBER=$'\033[33m'; TEAL=$'\033[36m'; OFF=$'\033[0m'
else AMBER=''; TEAL=''; OFF=''; fi

echo "Snapshots on disk:"
ls -d "$ROOT"/data/raw/overture/snapshot=* 2>/dev/null | tail -3 | sed 's|.*snapshot=|  |'
n=$(ls -d "$ROOT"/data/raw/overture/snapshot=* 2>/dev/null | wc -l)
echo "  ($n total)"
echo

if [ ! -f "$STAMP_FILE" ]; then
  echo "${AMBER}The archive has never completed successfully on this machine.${OFF}"
  echo "Run scripts/archive-monthly.sh once by hand to confirm it works."
  exit 1
fi

last=$(cat "$STAMP_FILE")
last_epoch=$(date -d "$last" +%s)
days=$(( ( $(date +%s) - last_epoch ) / 86400 ))
echo "Last successful run: $last (${days}d ago)"

# Overture ships monthly; 45 days means a release has probably already aged out
# of S3, and it cannot be fetched later.
if [ "$days" -gt 45 ]; then
  echo "${AMBER}OVERDUE — a release may already be unrecoverable.${OFF}"
  echo "Check $LOG_DIR/archive-*.log for the last attempt."
  exit 1
fi
echo "${TEAL}Healthy.${OFF}"

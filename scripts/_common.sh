#!/usr/bin/env bash
# Shared settings for the dev scripts. Sourced, never run directly.

set -euo pipefail

# Resolve the repo root from this file's location, so the scripts work no
# matter which directory they are invoked from.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-5173}"
API_HOST="${API_HOST:-127.0.0.1}"
# Loopback by default: a dev server on 0.0.0.0 is reachable by anything on the
# network. Set WEB_HOST=0.0.0.0 deliberately to test from a phone.
WEB_HOST="${WEB_HOST:-127.0.0.1}"
# Browser geolocation is gated on a SECURE CONTEXT — https, or localhost.
# Over http://<lan-ip> it refuses to run, so the locate button cannot be
# tested from a phone without TLS. Set WEB_HTTPS=1 to serve https; the certs
# are generated on first use.
# Unset means "decide from WEB_HOST" — resolved below, once both are known.
WEB_HTTPS="${WEB_HTTPS:-}"
CERT_DIR="${CERT_DIR:-$ROOT/.dev-certs}"

# BINDING TO THE NETWORK IMPLIES WANTING TLS.
# Serving on anything but loopback means testing from another device, and
# another device means the browser needs a secure context or it will refuse
# geolocation outright. Leaving these as two independent switches meant the
# common case — LAN, no https — was a silent half-configuration that looked
# like it worked until the locate button failed. Loopback stays http, because
# localhost is already a secure context and nothing is gained.
# WEB_HTTPS=0 forces it off; WEB_HTTPS=1 forces it on.
if [ -z "$WEB_HTTPS" ] && [ "$WEB_HOST" != "127.0.0.1" ] && [ "$WEB_HOST" != "localhost" ]; then
  WEB_HTTPS=1
fi
[ "$WEB_HTTPS" = "0" ] && WEB_HTTPS=""

DATA_DIR="${DATA_DIR:-$ROOT/data/derived/h3_tables}"
LOG_DIR="${LOG_DIR:-$ROOT/.dev-logs}"

# Colours only when attached to a terminal, so redirected logs stay clean.
if [ -t 1 ]; then
  DIM=$'\033[2m'; BOLD=$'\033[1m'; TEAL=$'\033[36m'; AMBER=$'\033[33m'; OFF=$'\033[0m'
else
  DIM=''; BOLD=''; TEAL=''; AMBER=''; OFF=''
fi

say()  { printf '%s%s%s\n' "$TEAL" "$*" "$OFF"; }
warn() { printf '%s%s%s\n' "$AMBER" "$*" "$OFF" >&2; }
die()  { printf '%s%s%s\n' "$AMBER" "$*" "$OFF" >&2; exit 1; }

port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

# Free a port and confirm it actually let go. fuser matches by socket, not by
# command string — pkill -f on a name like "thirdeye-api" also matches the
# shell that is running the kill, which terminates the caller.
free_port() {
  local port="$1"
  port_busy "$port" || return 0
  fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    port_busy "$port" || return 0
    sleep 0.25
  done
  return 1
}

# The API loads every parquet table into RAM before it serves, so "started" and
# "ready" are ~10s apart. Poll rather than sleeping a guessed interval.
wait_for_api() {
  local tries="${1:-90}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null "http://${API_HOST}:${API_PORT}/healthz" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Refuse to start against missing tables instead of serving an empty store.
check_data() {
  [ -d "$DATA_DIR" ] || die "No data directory at $DATA_DIR
Run the pipeline first, or point DATA_DIR at the tables."
  local missing=()
  for f in h3_cell_res9.parquet h3_metric_res9.parquet h3_metric_history_res9.parquet; do
    [ -f "$DATA_DIR/$f" ] || missing+=("$f")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    die "Missing tables in $DATA_DIR: ${missing[*]}"
  fi
}

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed or not on PATH."; }

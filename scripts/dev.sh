#!/usr/bin/env bash
# Start BOTH: API in the background, web in the foreground.
# Ctrl-C stops both. This is the one to use day to day.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

need go
need npm
check_data
mkdir -p "$LOG_DIR"

API_LOG="$LOG_DIR/api.log"

cleanup() {
  printf '\n'
  say "Stopping…"
  free_port "$API_PORT" || warn "Port $API_PORT did not release; check manually."
  free_port "$WEB_PORT" || true
}
trap cleanup EXIT INT TERM

for p in "$API_PORT" "$WEB_PORT"; do
  if port_busy "$p"; then
    warn "Port $p is in use — stopping whatever holds it."
    free_port "$p" || die "Could not free port $p."
  fi
done

say "Building api…"
( cd "$ROOT/api" && go build -o "$ROOT/api/thirdeye-api" . )

say "Starting api on ${API_HOST}:${API_PORT} — log: $API_LOG"
# -web enables server-rendered meta on /report and /compare. It needs a build,
# so this is best-effort: a missing web/dist only disables share previews.
"$ROOT/api/thirdeye-api" \
  -data "$DATA_DIR" \
  -limits "$ROOT/api/limitations.json" \
  -web "$ROOT/web/dist" \
  -addr "${API_HOST}:${API_PORT}" > "$API_LOG" 2>&1 &

printf '%swaiting for the store to load…%s\n' "$DIM" "$OFF"
if ! wait_for_api 90; then
  warn "API never became healthy. Last lines of $API_LOG:"
  tail -n 20 "$API_LOG" >&2 || true
  exit 1
fi
say "API ready."

cd "$ROOT/web"
[ -d node_modules ] || { say "Installing dependencies…"; npm install; }

say "Web on http://127.0.0.1:${WEB_PORT}"
printf '%s%s%s\n' "$DIM" "  /          coverage map — click to pick a location" "$OFF"
printf '%s%s%s\n' "$DIM" "  /report    report card for a point" "$OFF"
printf '%s%s%s\n' "$DIM" "  /tokens    design system preview" "$OFF"
printf '%s%s%s\n' "$DIM" "  api log:   tail -f $API_LOG" "$OFF"
npm run dev -- --port "$WEB_PORT" --host 127.0.0.1

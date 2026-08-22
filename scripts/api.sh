#!/usr/bin/env bash
# Start the Go API in the foreground. Ctrl-C to stop.
#
# Must run from api/: go.mod lives there, so `go run ./api` from the repo root
# fails with "go.mod file not found".
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

need go
check_data

if port_busy "$API_PORT"; then
  warn "Port $API_PORT is in use — stopping whatever holds it."
  free_port "$API_PORT" || die "Could not free port $API_PORT."
fi

cd "$ROOT/api"
say "Building api…"
go build -o "$ROOT/api/thirdeye-api" .

say "API on http://${API_HOST}:${API_PORT}  (loads parquet into RAM first, ~10s)"
printf '%s%s%s\n' "$DIM" "data: $DATA_DIR" "$OFF"
exec "$ROOT/api/thirdeye-api" \
  -data "$DATA_DIR" \
  -limits "$ROOT/api/limitations.json" \
  -web "$ROOT/web/dist" \
  -addr "${API_HOST}:${API_PORT}"

#!/usr/bin/env bash
# Start the Vite dev server in the foreground. Ctrl-C to stop.
#
# The frontend calls /api/* and Vite proxies that to the Go API, so the API
# should already be running — otherwise /report renders its "No report" state.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

need npm

if port_busy "$WEB_PORT"; then
  warn "Port $WEB_PORT is in use — stopping whatever holds it."
  free_port "$WEB_PORT" || die "Could not free port $WEB_PORT."
fi

cd "$ROOT/web"
[ -d node_modules ] || { say "Installing dependencies…"; npm install; }

if ! curl -fsS -o /dev/null "http://${API_HOST}:${API_PORT}/healthz" 2>/dev/null; then
  warn "API is not answering on ${API_HOST}:${API_PORT} — the home map will still"
  warn "render (it reads static files), but /report will show 'No report'."
  warn "Start it with scripts/api.sh, or run scripts/dev.sh for both."
fi

say "Web on http://127.0.0.1:${WEB_PORT}   /  ·  /report  ·  /tokens"
exec npm run dev -- --port "$WEB_PORT" --host 127.0.0.1

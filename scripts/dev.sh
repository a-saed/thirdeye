#!/usr/bin/env bash
# Start BOTH: API in the background, web in the foreground.
# Ctrl-C stops both. This is the one to use day to day.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

need go
need npm
check_data
mkdir -p "$LOG_DIR"

# The address the LAN sees us on, for the certificate SANs and the
# printed URL. A cert without the IP in its SANs is rejected by name,
# not by trust, so this cannot be left to a wildcard.
LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' || echo 127.0.0.1)"

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

# TLS is opt-in. Generating it unconditionally would put a private key in the
# tree for everyone who only ever opens localhost, where http is already a
# secure context and nothing is gained.
SCHEME=http
if [ -n "$WEB_HTTPS" ]; then
  need mkcert
  if [ ! -f "$CERT_DIR/cert.key" ] || [ ! -f "$CERT_DIR/cert.crt" ]; then
    say "Generating a dev CA and certificate in $CERT_DIR…"
    mkdir -p "$CERT_DIR"
    ( cd "$CERT_DIR" \
      && mkcert create-ca --organization "Third Eye Dev" --validity 825 \
           --key ca.key --cert ca.crt >/dev/null \
      && mkcert create-cert --ca-key ca.key --ca-cert ca.crt --validity 825 \
           --key cert.key --cert cert.crt \
           --domains localhost 127.0.0.1 $LAN_IP >/dev/null )
    warn "Install $CERT_DIR/ca.crt on any device you test from, or the"
    warn "browser will reject the certificate."
  fi
  export WEB_TLS_KEY="$CERT_DIR/cert.key"
  export WEB_TLS_CERT="$CERT_DIR/cert.crt"
  SCHEME=https
fi

say "Web on ${SCHEME}://${WEB_HOST}:${WEB_PORT}"
printf '%s%s%s\n' "$DIM" "  /          coverage map — click to pick a location" "$OFF"
printf '%s%s%s\n' "$DIM" "  /report    report card for a point" "$OFF"
printf '%s%s%s\n' "$DIM" "  /tokens    design system preview" "$OFF"
printf '%s%s%s\n' "$DIM" "  api log:   tail -f $API_LOG" "$OFF"
if [ "$WEB_HOST" = "0.0.0.0" ]; then
  say "On the LAN: ${SCHEME}://${LAN_IP}:${WEB_PORT}"
fi
npm run dev -- --port "$WEB_PORT" --host "$WEB_HOST"

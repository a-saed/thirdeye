#!/usr/bin/env bash
# Stop both, whatever started them.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

for p in "$API_PORT" "$WEB_PORT"; do
  if port_busy "$p"; then
    free_port "$p" && say "Stopped whatever held port $p." \
      || warn "Port $p is still held."
  else
    printf '%sport %s already free%s\n' "$DIM" "$p" "$OFF"
  fi
done

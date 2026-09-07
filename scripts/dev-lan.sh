#!/usr/bin/env bash
# Dev stack reachable from other devices on the LAN, over https.
#
# ONE COMMAND, because the two-variable version was a footgun: WEB_HOST alone
# binds to the network but serves http, and a phone will then refuse
# geolocation with no obvious cause — the failure surfaces as a browser
# message about a secure connection, several steps from the missing variable.
#
# The certificate is generated on first run and reused after; install
# .dev-certs/ca.crt on any device you test from.
WEB_HOST="${WEB_HOST:-0.0.0.0}" exec "$(dirname "${BASH_SOURCE[0]}")/dev.sh" "$@"

#!/usr/bin/env bash
set -euo pipefail

game_port="${SOULMASK_PORT:-7777}"
query_port="${SOULMASK_QUERY_PORT:-27015}"

if ! pgrep -f "WSServer-Linux-Shipping" >/dev/null 2>&1; then
  exit 1
fi

# Some environments can have flaky/absent query/list ports even while direct-connect works.
# Prefer validating the game port; accept query port as an alternate signal.
if command -v ss >/dev/null 2>&1; then
  ports="$(ss -lun 2>/dev/null | awk '{print $5}' || true)"
  if echo "${ports}" | grep -Eq "[:.]${game_port}\\b"; then
    exit 0
  fi
  if echo "${ports}" | grep -Eq "[:.]${query_port}\\b"; then
    exit 0
  fi
  exit 1
fi

exit 0

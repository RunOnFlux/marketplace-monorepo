#!/usr/bin/env bash
set -euo pipefail

query_port="${SOULMASK_QUERY_PORT:-27015}"

if ! pgrep -f "WSServer-Linux-Shipping" >/dev/null 2>&1; then
  exit 1
fi

if command -v ss >/dev/null 2>&1; then
  if ! ss -lun 2>/dev/null | awk '{print $5}' | grep -Eq "[:.]${query_port}\\b"; then
    exit 1
  fi
fi

exit 0

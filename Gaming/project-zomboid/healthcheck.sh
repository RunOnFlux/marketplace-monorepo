#!/usr/bin/env bash
set -euo pipefail

if pgrep -f "zombie\\.network\\.GameServer" >/dev/null 2>&1; then
  exit 0
fi

if pgrep -f "ProjectZomboid(32|64)" >/dev/null 2>&1; then
  exit 0
fi

exit 1


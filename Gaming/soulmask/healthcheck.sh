#!/usr/bin/env bash
set -euo pipefail

# Soulmask's SteamNetDriver can behave differently across environments; in some cases
# gameplay works but UDP socket visibility/query ports are unreliable. Flux will mark
# the container unhealthy if our healthcheck is too strict.
#
# Keep this check process-based: if the dedicated server is running, we're healthy.
pgrep -f "WSServer-Linux-Shipping" >/dev/null 2>&1

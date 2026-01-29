#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[soulmask] %s\n' "$*"
}

log_err() {
  printf '[soulmask] %s\n' "$*" >&2
}

is_true() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

bytes_available_on_path() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    path="$(dirname "${path}")"
  fi
  df -PB1 "${path}" 2>/dev/null | awk 'NR==2 {print $4}'
}

mountpoint_for_path() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    path="$(dirname "${path}")"
  fi
  df -P "${path}" 2>/dev/null | awk 'NR==2 {print $6}'
}

disk_preflight() {
  if ! is_true "${DISK_PREFLIGHT:-true}"; then
    return 0
  fi

  local required_gb="${MIN_FREE_GB:-15}"
  if [[ ! "${required_gb}" =~ ^[0-9]+$ ]]; then
    required_gb=15
  fi
  local required_bytes=$((required_gb * 1024 * 1024 * 1024))

  local avail_bytes
  avail_bytes="$(bytes_available_on_path "${STEAM_INSTALL_DIR}")"
  if [[ -z "${avail_bytes}" ]]; then
    log "Disk preflight: unable to determine free space for ${STEAM_INSTALL_DIR} (skipping)"
    return 0
  fi

  local avail_gb=$((avail_bytes / 1024 / 1024 / 1024))
  local mountpoint
  mountpoint="$(mountpoint_for_path "${STEAM_INSTALL_DIR}")"

  if (( avail_bytes < required_bytes )); then
    log_err "ERROR: Not enough free disk space to install/update Soulmask."
    log_err "Install path: ${STEAM_INSTALL_DIR} (mount: ${mountpoint:-unknown})"
    log_err "Required: ${required_gb} GB free; Available: ${avail_gb} GB free"
    log_err "Tip: On Flux, the requested HDD applies to the mounted app volume (containerData), not the container root filesystem (/)."
    exit 1
  fi
}

mask_args_for_log() {
  local in=("$@")
  local out=()
  local i=0
  while (( i < ${#in[@]} )); do
    local arg="${in[i]}"
    case "${arg}" in
      -PSW=*)
        out+=("-PSW=<redacted>")
        ;;
      -adminpsw=*)
        out+=("-adminpsw=<redacted>")
        ;;
      *)
        out+=("${arg}")
        ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "${out[*]}"
}

STEAMCMD="/home/steam/steamcmd/steamcmd.sh"
STEAM_APP_ID="${STEAM_APP_ID:-3017300}"
STEAM_INSTALL_DIR="${STEAM_INSTALL_DIR:-/data/server}"

log "=========================================="
log "  Soulmask Dedicated Server"
log "  (SteamCMD, Flux-friendly, headless)"
log "=========================================="
log "Steam AppID: ${STEAM_APP_ID}"
log "Install dir: ${STEAM_INSTALL_DIR}"
log "Config dir:  /config"
log "Ports:       ${SOULMASK_PORT:-7777}/udp (game), ${SOULMASK_QUERY_PORT:-27015}/udp (query), ${SOULMASK_ECHO_PORT:-18888}/tcp (echo)"
log "Note:        Server also opens 19000/tcp (observed on startup)"

id_changed="false"
if [[ "$(id -u)" -eq 0 ]]; then
  if [[ -n "${PUID:-}" ]] && [[ "${PUID}" != "1000" ]]; then
    log "Updating UID to ${PUID}..."
    if usermod -u "${PUID}" steam; then
      id_changed="true"
    fi
  fi

  if [[ -n "${PGID:-}" ]] && [[ "${PGID}" != "1000" ]]; then
    log "Updating GID to ${PGID}..."
    if groupmod -g "${PGID}" steam; then
      id_changed="true"
    fi
  fi
else
  if [[ -n "${PUID:-}" || -n "${PGID:-}" ]]; then
    log "Warning: PUID/PGID set but container is not running as root; skipping user/group modifications."
  fi
fi

mkdir -p "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R steam:steam "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config >/dev/null 2>&1 || true
fi

if is_true "${HARDEN_FLUX_VOLUME_BROWSER:-true}"; then
  chmod 700 "${STEAM_INSTALL_DIR}" >/dev/null 2>&1 || true
else
  chmod 755 "${STEAM_INSTALL_DIR}" >/dev/null 2>&1 || true
fi
chmod 755 /config >/dev/null 2>&1 || true

disk_preflight

steamcmd_update() {
  if ! is_true "${AUTO_UPDATE:-true}"; then
    log "AUTO_UPDATE=false; skipping SteamCMD update."
    return 0
  fi

  local force_dir=(+force_install_dir "${STEAM_INSTALL_DIR}")
  local app_update=(+app_update "${STEAM_APP_ID}")

  if [[ -n "${STEAM_BRANCH:-}" ]]; then
    log "Using Steam branch: ${STEAM_BRANCH}"
    app_update=(+app_update "${STEAM_APP_ID}" -beta "${STEAM_BRANCH}")
    if [[ -n "${STEAM_BRANCH_PASSWORD:-}" ]]; then
      app_update+=(-betapassword "${STEAM_BRANCH_PASSWORD}")
    fi
  fi

  if is_true "${STEAMCMD_VALIDATE:-false}"; then
    app_update+=(validate)
  fi

  if [[ -n "${STEAMCMD_EXTRA_ARGS:-}" ]]; then
    read -r -a extra <<<"${STEAMCMD_EXTRA_ARGS}"
    app_update+=("${extra[@]}")
  fi

  local cmd=(
    "${STEAMCMD}"
    "${force_dir[@]}"
    +login "${STEAM_LOGIN:-anonymous}" "${STEAM_PASSWORD:-}" "${STEAM_GUARD:-}"
    "${app_update[@]}"
    +quit
  )

  log "Updating Soulmask via SteamCMD..."

  local attempts="${STEAMCMD_RETRIES:-3}"
  if [[ ! "${attempts}" =~ ^[0-9]+$ ]]; then
    attempts=3
  fi

  local i
  local rc=0
  for ((i = 1; i <= attempts; i++)); do
    set +e
    gosu steam "${cmd[@]}" 2>&1 | tee "${STEAMCMD_LOG_FILE:-/data/steam/steamcmd.log}"
    rc=${PIPESTATUS[0]}
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      return 0
    fi
    log_err "SteamCMD failed (attempt ${i}/${attempts}, rc=${rc})."
    sleep $((i * 5))
  done

  return "${rc}"
}

ensure_steamclient() {
  local src="/home/steam/steamcmd/linux64/steamclient.so"
  local dst_dir="/home/steam/.steam/sdk64"
  local dst="${dst_dir}/steamclient.so"

  if [[ -f "${src}" ]]; then
    mkdir -p "${dst_dir}"
    if [[ ! -e "${dst}" ]]; then
      ln -s "${src}" "${dst}" >/dev/null 2>&1 || true
    fi
  fi
}

if ! steamcmd_update; then
  log_err "SteamCMD update failed."
fi
ensure_steamclient

server_bin="${STEAM_INSTALL_DIR}/WS/Binaries/Linux/WSServer-Linux-Shipping"
if [[ ! -x "${server_bin}" ]]; then
  log_err "ERROR: Server binary not found or not executable: ${server_bin}"
  log_err "Check SteamCMD logs at: ${STEAMCMD_LOG_FILE:-/data/steam/steamcmd.log}"
  exit 1
fi

# Persist saves/configs under /config by linking WS/Saved
saved_src="${STEAM_INSTALL_DIR}/WS/Saved"
saved_dst="/config/WS/Saved"
mkdir -p "${saved_dst}"

if [[ -d "${saved_src}" ]] && [[ ! -L "${saved_src}" ]]; then
  if [[ -z "$(ls -A "${saved_dst}" 2>/dev/null || true)" ]] && [[ -n "$(ls -A "${saved_src}" 2>/dev/null || true)" ]]; then
    log "Migrating existing WS/Saved into /config..."
    cp -a "${saved_src}/." "${saved_dst}/" >/dev/null 2>&1 || true
  fi
  rm -rf "${saved_src}" >/dev/null 2>&1 || true
fi
if [[ ! -e "${saved_src}" ]]; then
  ln -s "${saved_dst}" "${saved_src}" >/dev/null 2>&1 || true
fi

if [[ "$(id -u)" -eq 0 ]]; then
  chown -R steam:steam /config >/dev/null 2>&1 || true
fi

game_mode="${SOULMASK_GAME_MODE:-pve}"
case "${game_mode,,}" in
  pve) game_mode_flag="-pve" ;;
  pvp) game_mode_flag="-pvp" ;;
  *)
    log_err "Invalid SOULMASK_GAME_MODE=${game_mode} (expected: pve|pvp). Defaulting to pve."
    game_mode_flag="-pve"
    ;;
esac

cmd=(
  "${server_bin}"
  "WS"
  "${SOULMASK_MAP:-Level01_Main}"
  "-server"
  "-log"
  "-UTF8Output"
  "-MULTIHOME=0.0.0.0"
  "${game_mode_flag}"
  "-SteamServerName=${SOULMASK_SERVER_NAME:-RunOnFlux - Soulmask}"
  "-MaxPlayers=${SOULMASK_MAX_PLAYERS:-20}"
  "-Port=${SOULMASK_PORT:-7777}"
  "-QueryPort=${SOULMASK_QUERY_PORT:-27015}"
  "-EchoPort=${SOULMASK_ECHO_PORT:-18888}"
  "-saving=${SOULMASK_SAVING_INTERVAL:-600}"
  "-backup=${SOULMASK_BACKUP_INTERVAL:-900}"
  "-gamedistindex=${SOULMASK_GAMEDISTINDEX:-1}"
)

if [[ -n "${SOULMASK_PASSWORD:-}" ]]; then
  cmd+=("-PSW=${SOULMASK_PASSWORD}")
fi
if [[ -n "${SOULMASK_ADMIN_PASSWORD:-}" ]]; then
  cmd+=("-adminpsw=${SOULMASK_ADMIN_PASSWORD}")
fi
if is_true "${SOULMASK_INIT_BACKUP:-true}"; then
  cmd+=("-initbackup")
fi
if [[ -n "${SOULMASK_BACKUP_INTERVAL_MINUTES:-}" ]]; then
  cmd+=("-backupinterval=${SOULMASK_BACKUP_INTERVAL_MINUTES}")
fi
if [[ -n "${SOULMASK_MOD_ID:-}" ]]; then
  cmd+=("-mod=${SOULMASK_MOD_ID}")
fi
if [[ -n "${SOULMASK_EXTRA_ARGS:-}" ]]; then
  read -r -a extra_args <<<"${SOULMASK_EXTRA_ARGS}"
  cmd+=("${extra_args[@]}")
fi

log "Launching server..."
log "Mode: ${game_mode_flag#-}"
log "Config: /config/WS/Saved (symlinked into ${saved_src})"
log "Args: $(mask_args_for_log "${cmd[@]}")"

shutdown_grace="${SOULMASK_SHUTDOWN_GRACE:-180}"
echo_port="${SOULMASK_ECHO_PORT:-18888}"
admin_password="${SOULMASK_ADMIN_PASSWORD:-}"

graceful_shutdown() {
  log "Received shutdown signal."

  if [[ -z "${admin_password}" ]]; then
    log "SOULMASK_ADMIN_PASSWORD is empty; skipping echo/telnet quit."
    return 0
  fi

  if [[ ! "${shutdown_grace}" =~ ^[0-9]+$ ]]; then
    shutdown_grace=180
  fi

  log "Attempting graceful shutdown via echo port (quit ${shutdown_grace})..."
  {
    printf '%s\r\n' "${admin_password}"
    printf 'quit %s\r\n' "${shutdown_grace}"
  } | nc -w 2 127.0.0.1 "${echo_port}" >/dev/null 2>&1 || true
}

server_pid=""
if [[ "$(id -u)" -eq 0 ]]; then
  gosu steam "${cmd[@]}" &
  server_pid="$!"
else
  "${cmd[@]}" &
  server_pid="$!"
fi

wait_for_exit() {
  local timeout_seconds="$1"
  local waited=0
  while kill -0 "${server_pid}" >/dev/null 2>&1; do
    if (( waited >= timeout_seconds )); then
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

on_signal() {
  graceful_shutdown

  local total_wait="${shutdown_grace}"
  if [[ ! "${total_wait}" =~ ^[0-9]+$ ]]; then
    total_wait=180
  fi

  if wait_for_exit "${total_wait}"; then
    exit 0
  fi

  log_err "Server still running after ${total_wait}s; sending SIGTERM..."
  kill -TERM "${server_pid}" >/dev/null 2>&1 || true

  if wait_for_exit 30; then
    exit 0
  fi

  log_err "Server still running; sending SIGKILL..."
  kill -KILL "${server_pid}" >/dev/null 2>&1 || true
  exit 0
}

trap on_signal TERM INT
wait "${server_pid}"

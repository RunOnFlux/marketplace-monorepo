#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[project-zomboid] %s\n' "$*"
}

log_err() {
  printf '[project-zomboid] %s\n' "$*" >&2
}

is_true() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "${s}"
}

one_line() {
  local s="${1:-}"
  s="${s//$'\r'/}"
  s="${s//$'\n'/ }"
  printf '%s' "${s}"
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

  local required_gb="${MIN_FREE_GB:-10}"
  if [[ ! "${required_gb}" =~ ^[0-9]+$ ]]; then
    required_gb=10
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
    log_err "ERROR: Not enough free disk space to install/update Project Zomboid Dedicated Server."
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
      -adminpassword)
        out+=("-adminpassword" "<redacted>")
        i=$((i + 2))
        ;;
      -adminpassword=*)
        out+=("-adminpassword=<redacted>")
        i=$((i + 1))
        ;;
      *)
        out+=("${arg}")
        i=$((i + 1))
        ;;
    esac
  done
  printf '%s' "${out[*]}"
}

ini_set() {
  local file="$1"
  local key="$2"
  local value="${3:-}"

  local key_esc
  key_esc="$(printf '%s' "${key}" | sed -e 's/[][\\/.*^$+?(){}|]/\\\\&/g')"

  local value_esc
  value_esc="$(printf '%s' "${value}" | sed -e 's/[\\/&]/\\\\&/g')"

  if grep -qE "^${key_esc}=" "${file}"; then
    sed -i -E "s/^${key_esc}=.*$/${key}=${value_esc}/" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${file}"
  fi
}

normalize_bool() {
  if is_true "${1:-}"; then
    printf 'true'
  else
    printf 'false'
  fi
}

normalize_list_semicolon() {
  local s
  s="$(trim "${1:-}")"
  s="${s//,/;}"
  s="${s//;;/;}"
  s="${s#;}"
  s="${s%;}"
  printf '%s' "${s}"
}

locate_start_script() {
  local expected="${STEAM_INSTALL_DIR}/start-server.sh"
  if [[ -f "${expected}" ]]; then
    printf '%s' "${expected}"
    return 0
  fi

  local found=""
  found="$(find "${STEAM_INSTALL_DIR}" -maxdepth 4 -type f -name 'start-server.sh' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${found}" ]]; then
    printf '%s' "${found}"
    return 0
  fi

  return 1
}

patch_java_memory_json() {
  local file="$1"
  [[ -f "${file}" ]] || return 0

  local xms="${PZ_JAVA_XMS:-}"
  local xmx="${PZ_JAVA_XMX:-}"

  if [[ -n "${xms}" ]]; then
    sed -i -E "s/-Xms[0-9]+[mMgG]/-Xms${xms}/g" "${file}" || true
  fi
  if [[ -n "${xmx}" ]]; then
    sed -i -E "s/-Xmx[0-9]+[mMgG]/-Xmx${xmx}/g" "${file}" || true
  fi
}

STEAMCMD="/home/steam/steamcmd/steamcmd.sh"
STEAM_APP_ID="${STEAM_APP_ID:-380870}"
STEAM_INSTALL_DIR="${STEAM_INSTALL_DIR:-/data/server}"

PZ_SERVER_NAME="$(trim "${PZ_SERVER_NAME:-servertest}")"
if [[ -z "${PZ_SERVER_NAME}" ]]; then
  PZ_SERVER_NAME="servertest"
fi

log "=========================================="
log "  Project Zomboid Dedicated Server"
log "  (SteamCMD, Flux-friendly, headless)"
log "=========================================="
log "Steam AppID: ${STEAM_APP_ID}"
log "Install dir: ${STEAM_INSTALL_DIR}"
log "Config dir:  /config (Zomboid persisted under /config/Zomboid)"
log "Ports:       ${PZ_PORT:-16261}/udp (game), ${PZ_UDP_PORT:-16262}/udp (udp)"

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

mkdir -p "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config /config/Zomboid/Server
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R steam:steam "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config >/dev/null 2>&1 || true
fi

if is_true "${HARDEN_FLUX_VOLUME_BROWSER:-true}"; then
  chmod 700 "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" >/dev/null 2>&1 || true
else
  chmod 755 "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" >/dev/null 2>&1 || true
fi
chmod 755 /config /config/Zomboid /config/Zomboid/Server >/dev/null 2>&1 || true

disk_preflight

if [[ -e /home/steam/Zomboid && ! -L /home/steam/Zomboid ]]; then
  mv /home/steam/Zomboid "/home/steam/Zomboid.backup.$(date +%s)" >/dev/null 2>&1 || true
fi
ln -sfn /config/Zomboid /home/steam/Zomboid
if [[ "$(id -u)" -eq 0 ]]; then
  chown -h steam:steam /home/steam/Zomboid >/dev/null 2>&1 || true
fi

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

  log "Updating Project Zomboid via SteamCMD..."

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

if ! steamcmd_update; then
  log_err "SteamCMD update failed."
fi

start_script="$(locate_start_script || true)"
if [[ -z "${start_script}" ]]; then
  log_err "ERROR: start-server.sh not found under ${STEAM_INSTALL_DIR}."
  log_err "Check SteamCMD logs at: ${STEAMCMD_LOG_FILE:-/data/steam/steamcmd.log}"
  exit 1
fi

chmod +x "${start_script}" >/dev/null 2>&1 || true

# Patch common JVM heap settings used by the official scripts.
patch_java_memory_json "${STEAM_INSTALL_DIR}/ProjectZomboid64.json"
patch_java_memory_json "${STEAM_INSTALL_DIR}/ProjectZomboid32.json"

ini_path="/config/Zomboid/Server/${PZ_SERVER_NAME}.ini"
if is_true "${PZ_MANAGE_CONFIG:-true}"; then
  if [[ ! -f "${ini_path}" ]]; then
    log "Creating server INI: ${ini_path}"
    cat >"${ini_path}" <<EOF
DefaultPort=${PZ_PORT:-16261}
UDPPort=${PZ_UDP_PORT:-16262}
Public=$(normalize_bool "${PZ_PUBLIC:-true}")
PublicName=$(one_line "${PZ_PUBLIC_NAME:-RunOnFlux - Project Zomboid}")
PublicDescription=$(one_line "${PZ_PUBLIC_DESCRIPTION:-Project Zomboid dedicated server on Flux.}")
MaxPlayers=${PZ_MAX_PLAYERS:-16}
Password=$(one_line "${PZ_PASSWORD:-}")
PVP=$(normalize_bool "${PZ_PVP:-false}")
PauseEmpty=$(normalize_bool "${PZ_PAUSE_EMPTY:-true}")
GlobalChat=$(normalize_bool "${PZ_GLOBAL_CHAT:-true}")
Open=$(normalize_bool "${PZ_OPEN:-true}")
Map=$(one_line "${PZ_MAP:-Muldraugh, KY}")
SaveWorldEveryMinutes=${PZ_SAVE_EVERY_MINUTES:-10}
Mods=$(normalize_list_semicolon "${PZ_MODS:-}")
WorkshopItems=$(normalize_list_semicolon "${PZ_WORKSHOP_ITEMS:-}")
RCONPort=${PZ_RCON_PORT:-27015}
RCONPassword=$(one_line "${PZ_RCON_PASSWORD:-}")
EOF
  else
    ini_set "${ini_path}" DefaultPort "${PZ_PORT:-16261}"
    ini_set "${ini_path}" UDPPort "${PZ_UDP_PORT:-16262}"
    ini_set "${ini_path}" Public "$(normalize_bool "${PZ_PUBLIC:-true}")"
    ini_set "${ini_path}" PublicName "$(one_line "${PZ_PUBLIC_NAME:-RunOnFlux - Project Zomboid}")"
    ini_set "${ini_path}" PublicDescription "$(one_line "${PZ_PUBLIC_DESCRIPTION:-Project Zomboid dedicated server on Flux.}")"
    ini_set "${ini_path}" MaxPlayers "${PZ_MAX_PLAYERS:-16}"
    ini_set "${ini_path}" Password "$(one_line "${PZ_PASSWORD:-}")"
    ini_set "${ini_path}" PVP "$(normalize_bool "${PZ_PVP:-false}")"
    ini_set "${ini_path}" PauseEmpty "$(normalize_bool "${PZ_PAUSE_EMPTY:-true}")"
    ini_set "${ini_path}" GlobalChat "$(normalize_bool "${PZ_GLOBAL_CHAT:-true}")"
    ini_set "${ini_path}" Open "$(normalize_bool "${PZ_OPEN:-true}")"
    ini_set "${ini_path}" Map "$(one_line "${PZ_MAP:-Muldraugh, KY}")"
    ini_set "${ini_path}" SaveWorldEveryMinutes "${PZ_SAVE_EVERY_MINUTES:-10}"
    ini_set "${ini_path}" Mods "$(normalize_list_semicolon "${PZ_MODS:-}")"
    ini_set "${ini_path}" WorkshopItems "$(normalize_list_semicolon "${PZ_WORKSHOP_ITEMS:-}")"
    ini_set "${ini_path}" RCONPort "${PZ_RCON_PORT:-27015}"
    ini_set "${ini_path}" RCONPassword "$(one_line "${PZ_RCON_PASSWORD:-}")"
  fi

  if [[ -n "${PZ_SERVER_INI_EXTRA_B64:-}" ]]; then
    log "Appending server INI extra lines (PZ_SERVER_INI_EXTRA_B64)..."
    printf '%s' "${PZ_SERVER_INI_EXTRA_B64}" | base64 -d >>"${ini_path}" 2>/dev/null || {
      log_err "WARNING: failed to decode PZ_SERVER_INI_EXTRA_B64 (expected base64 text)."
    }
    printf '\n' >>"${ini_path}"
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    chown steam:steam "${ini_path}" >/dev/null 2>&1 || true
  fi
else
  log "PZ_MANAGE_CONFIG=false; leaving ${ini_path} untouched."
fi

first_run=true
if [[ -d /config/Zomboid/db ]] && find /config/Zomboid/db -maxdepth 1 -type f | grep -q .; then
  first_run=false
fi

admin_user="$(trim "${PZ_ADMIN_USERNAME:-admin}")"
admin_pass="${PZ_ADMIN_PASSWORD:-}"
if is_true "${first_run}"; then
  if [[ -z "${admin_pass}" ]]; then
    log_err "ERROR: PZ_ADMIN_PASSWORD must be set on first boot (to avoid an interactive prompt)."
    log_err "Tip: set PZ_ADMIN_PASSWORD=test1234 for VPS testing, then change it."
    exit 1
  fi
fi

cmd=( "${start_script}" -servername "${PZ_SERVER_NAME}" )

if [[ -n "${admin_pass}" ]]; then
  cmd+=( -adminusername "${admin_user:-admin}" -adminpassword "${admin_pass}" )
fi

if is_true "${PZ_NOSTEAM:-false}"; then
  cmd+=( -nosteam )
fi

if is_true "${PZ_RCON_ENABLED:-false}"; then
  ini_set "${ini_path}" RCONPort "${PZ_RCON_PORT:-27015}"
else
  ini_set "${ini_path}" RCONPort "0"
fi

if [[ -n "${PZ_EXTRA_ARGS:-}" ]]; then
  read -r -a extra <<<"${PZ_EXTRA_ARGS}"
  cmd+=("${extra[@]}")
fi

log "Launching: $(mask_args_for_log "${cmd[@]}")"

cd "${STEAM_INSTALL_DIR}"
exec gosu steam "${cmd[@]}"

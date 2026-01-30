#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[rust] %s\n' "$*"
}

log_err() {
  printf '[rust] %s\n' "$*" >&2
}

is_true() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

is_int() {
  [[ "${1:-}" =~ ^-?[0-9]+$ ]]
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
    log_err "ERROR: Not enough free disk space to install/update Rust Dedicated Server."
    log_err "Install path: ${STEAM_INSTALL_DIR} (mount: ${mountpoint:-unknown})"
    log_err "Required: ${required_gb} GB free; Available: ${avail_gb} GB free"
    log_err "Tip: On Flux, the requested HDD applies to the mounted app volume (containerData), not the container root filesystem (/)."
    exit 1
  fi
}

normalize_bool() {
  if is_true "${1:-}"; then
    printf 'true'
  else
    printf 'false'
  fi
}

mask_args_for_log() {
  local in=("$@")
  local out=()
  local i=0
  while (( i < ${#in[@]} )); do
    local arg="${in[i]}"
    case "${arg}" in
      +rcon.password|+rcon.password=*)
        if [[ "${arg}" == "+rcon.password" ]]; then
          out+=("+rcon.password" "<redacted>")
          i=$((i + 2))
          continue
        fi
        out+=("+rcon.password=<redacted>")
        ;;
      *)
        out+=("${arg}")
        ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "${out[*]}"
}

discover_map_info() {
  local dir="$1"
  local newest=""

  newest="$(ls -1t "${dir}"/*.map 2>/dev/null | head -n1 || true)"
  if [[ -z "${newest}" ]]; then
    newest="$(ls -1t "${dir}"/*.sav 2>/dev/null | head -n1 || true)"
  fi
  if [[ -z "${newest}" ]]; then
    return 1
  fi

  local base
  base="$(basename "${newest}")"
  base="${base%.*}"

  if [[ "${base}" =~ \.([0-9]+)\.([0-9]+)$ ]]; then
    printf '%s %s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi

  return 1
}

rand_seed() {
  # bash RANDOM is 0..32767; combine to get a 31-bit integer > 0
  printf '%s' "$(( (RANDOM << 16) + RANDOM + 1 ))"
}

atomic_write_number() {
  local path="$1"
  local value="$2"
  local tmp="${path}.tmp.$$"
  printf '%s\n' "${value}" >"${tmp}"
  mv -f "${tmp}" "${path}"
}

wait_for_synced_world_files() {
  local identity_dir="$1"
  local wait_s="${RUST_SYNC_WAIT_SECONDS:-900}"
  local fail="${RUST_SYNC_WAIT_FAIL:-true}"

  if ! is_int "${wait_s}" || (( wait_s < 0 )); then
    wait_s=900
  fi

  local has_player_files="false"
  if find "${identity_dir}" -maxdepth 1 -type f -name 'player*' -print -quit 2>/dev/null | grep -q .; then
    has_player_files="true"
  fi

  local has_world_files="false"
  if find "${identity_dir}" -maxdepth 1 -type f \( -name '*.map' -o -name '*.sav' \) -print -quit 2>/dev/null | grep -q .; then
    has_world_files="true"
  fi

  if [[ "${has_player_files}" != "true" || "${has_world_files}" == "true" ]]; then
    return 0
  fi

  if (( wait_s == 0 )); then
    log_err "ERROR: Detected existing player data but no world files in ${identity_dir}; refusing to start."
    exit 1
  fi

  log "Detected existing player data but no world files yet (likely g:/ sync still catching up)."
  log "Waiting up to ${wait_s}s for *.map/*.sav to appear before starting..."

  local start
  start="$(date +%s)"
  while true; do
    if find "${identity_dir}" -maxdepth 1 -type f \( -name '*.map' -o -name '*.sav' \) -print -quit 2>/dev/null | grep -q .; then
      log "World files detected; continuing startup."
      return 0
    fi

    local now elapsed
    now="$(date +%s)"
    elapsed=$((now - start))
    if (( elapsed >= wait_s )); then
      if is_true "${fail}"; then
        log_err "ERROR: Timed out waiting for world files in ${identity_dir} (${wait_s}s)."
        log_err "Refusing to start to avoid generating a new world and wiping player progress."
        log_err "If you want to force-start anyway, set RUST_SYNC_WAIT_FAIL=false (not recommended)."
        exit 1
      fi
      log_err "WARNING: Timed out waiting for world files; continuing anyway (RUST_SYNC_WAIT_FAIL=false)."
      return 0
    fi

    sleep 5
  done
}

STEAMCMD="/home/steam/steamcmd/steamcmd.sh"
STEAM_APP_ID="${STEAM_APP_ID:-258550}"
STEAM_INSTALL_DIR="${STEAM_INSTALL_DIR:-/data/server}"

identity="$(trim "${RUST_SERVER_IDENTITY:-rust}")"
if [[ -z "${identity}" ]]; then
  identity="rust"
fi

log "=========================================="
log "  Rust Dedicated Server"
log "  (SteamCMD, Flux-friendly, headless)"
log "=========================================="
log "Steam AppID: ${STEAM_APP_ID}"
log "Install dir: ${STEAM_INSTALL_DIR}"
log "Config dir:  /config (server/ persisted under /config/server)"
log "Ports:       ${RUST_SERVER_PORT:-28015}/udp (game), ${RUST_RCON_PORT:-28016}/tcp (rcon), ${RUST_SERVER_QUERYPORT:-28017}/udp (query)"

if [[ "$(id -u)" -eq 0 ]]; then
  if [[ -n "${PUID:-}" ]] && [[ "${PUID}" != "1000" ]]; then
    log "Updating UID to ${PUID}..."
    usermod -u "${PUID}" steam >/dev/null 2>&1 || true
  fi
  if [[ -n "${PGID:-}" ]] && [[ "${PGID}" != "1000" ]]; then
    log "Updating GID to ${PGID}..."
    groupmod -g "${PGID}" steam >/dev/null 2>&1 || true
  fi
else
  if [[ -n "${PUID:-}" || -n "${PGID:-}" ]]; then
    log "Warning: PUID/PGID set but container is not running as root; skipping user/group modifications."
  fi
fi

mkdir -p "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config /config/server
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R steam:steam "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" /config >/dev/null 2>&1 || true
fi

if is_true "${HARDEN_FLUX_VOLUME_BROWSER:-true}"; then
  chmod 700 "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" >/dev/null 2>&1 || true
else
  chmod 755 "${STEAM_INSTALL_DIR}" "${STEAMCMD_HOME:-/data/steam}" >/dev/null 2>&1 || true
fi
chmod 755 /config /config/server >/dev/null 2>&1 || true

disk_preflight

# Keep the huge install on /data, but persist server identity/saves under /config.
mkdir -p /config/server
if [[ -e "${STEAM_INSTALL_DIR}/server" && ! -L "${STEAM_INSTALL_DIR}/server" ]]; then
  mv "${STEAM_INSTALL_DIR}/server" "${STEAM_INSTALL_DIR}/server.backup.$(date +%s)" >/dev/null 2>&1 || true
fi
ln -sfn /config/server "${STEAM_INSTALL_DIR}/server"
if [[ "$(id -u)" -eq 0 ]]; then
  chown -h steam:steam "${STEAM_INSTALL_DIR}/server" >/dev/null 2>&1 || true
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

  log "Updating Rust via SteamCMD..."

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

server_bin="${STEAM_INSTALL_DIR}/RustDedicated"
if [[ ! -x "${server_bin}" ]]; then
  log_err "ERROR: Server binary not found or not executable: ${server_bin}"
  log_err "Check SteamCMD logs at: ${STEAMCMD_LOG_FILE:-/data/steam/steamcmd.log}"
  exit 1
fi

identity_dir="/config/server/${identity}"
cfg_dir="${identity_dir}/cfg"
mkdir -p "${cfg_dir}"
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R steam:steam "/config/server/${identity}" >/dev/null 2>&1 || true
fi

wait_for_synced_world_files "${identity_dir}"

map_worldsize=""
map_seed=""
if map_info="$(discover_map_info "${identity_dir}" 2>/dev/null)"; then
  map_worldsize="${map_info%% *}"
  map_seed="${map_info##* }"
fi

seed_file="${identity_dir}/seed.txt"
worldsize_file="${identity_dir}/worldsize.txt"

effective_seed="${RUST_SEED:-0}"
if ! is_int "${effective_seed}"; then
  effective_seed=0
fi

if (( effective_seed <= 0 )); then
  if [[ -f "${seed_file}" ]]; then
    seed_from_file="$(trim "$(cat "${seed_file}" 2>/dev/null || true)")"
    if is_int "${seed_from_file}" && (( seed_from_file > 0 )); then
      effective_seed="${seed_from_file}"
    fi
  fi
fi

if (( effective_seed <= 0 )) && [[ -n "${map_seed}" ]] && is_int "${map_seed}"; then
  effective_seed="${map_seed}"
fi

if (( effective_seed <= 0 )); then
  effective_seed="$(rand_seed)"
fi

effective_worldsize="${RUST_WORLD_SIZE:-3000}"
if ! is_int "${effective_worldsize}"; then
  effective_worldsize=3000
fi

if [[ -z "${RUST_WORLD_SIZE:-}" ]]; then
  if [[ -f "${worldsize_file}" ]]; then
    ws_from_file="$(trim "$(cat "${worldsize_file}" 2>/dev/null || true)")"
    if is_int "${ws_from_file}" && (( ws_from_file > 0 )); then
      effective_worldsize="${ws_from_file}"
    fi
  elif [[ -n "${map_worldsize}" ]] && is_int "${map_worldsize}"; then
    effective_worldsize="${map_worldsize}"
  fi
fi

atomic_write_number "${seed_file}" "${effective_seed}" >/dev/null 2>&1 || true
atomic_write_number "${worldsize_file}" "${effective_worldsize}" >/dev/null 2>&1 || true

server_cfg="${cfg_dir}/server.cfg"
if is_true "${RUST_WRITE_CFG:-true}"; then
  cat >"${server_cfg}" <<EOF
server.hostname "$(one_line "${RUST_SERVER_NAME:-RunOnFlux - Rust}")"
server.description "$(one_line "${RUST_SERVER_DESCRIPTION:-Rust dedicated server on Flux.}")"
server.url "$(one_line "${RUST_SERVER_URL:-}")"
server.headerimage "$(one_line "${RUST_SERVER_HEADERIMAGE:-}")"
server.tags "$(one_line "${RUST_SERVER_TAGS:-vanilla,flux}")"
server.maxplayers ${RUST_MAX_PLAYERS:-100}
server.seed ${effective_seed}
server.worldsize ${effective_worldsize}
server.saveinterval ${RUST_SAVE_INTERVAL:-600}
server.tickrate ${RUST_TICKRATE:-30}
server.secure $(normalize_bool "${RUST_SERVER_SECURE:-true}")
EOF

  if [[ -n "${RUST_SERVER_CFG_B64:-}" ]]; then
    log "Appending server.cfg from RUST_SERVER_CFG_B64..."
    printf '%s' "${RUST_SERVER_CFG_B64}" | base64 -d >>"${server_cfg}" 2>/dev/null || {
      log_err "WARNING: failed to decode RUST_SERVER_CFG_B64 (expected base64 text)."
    }
    printf '\n' >>"${server_cfg}"
  fi
else
  log "RUST_WRITE_CFG=false; leaving ${server_cfg} untouched."
fi

if [[ "$(id -u)" -eq 0 ]]; then
  chown steam:steam "${server_cfg}" >/dev/null 2>&1 || true
fi

port="${RUST_SERVER_PORT:-28015}"
queryport="${RUST_SERVER_QUERYPORT:-28017}"
rcon_port="${RUST_RCON_PORT:-28016}"
rcon_password="${RUST_RCON_PASSWORD:-}"

cmd=(
  "${server_bin}"
  -batchmode
  -nographics
  +server.ip "${RUST_SERVER_IP:-0.0.0.0}"
  +server.port "${port}"
  +server.queryport "${queryport}"
  +server.identity "${identity}"
  +server.level "$(one_line "${RUST_LEVEL:-Procedural Map}")"
  +rcon.ip 0.0.0.0
  +rcon.port "${rcon_port}"
  +rcon.web "$(normalize_bool "${RUST_RCON_WEB:-true}")"
)

if [[ -n "${rcon_password}" ]]; then
  cmd+=( +rcon.password "${rcon_password}" )
else
  log "Warning: RUST_RCON_PASSWORD is empty (RCON will not be protected)."
fi

if [[ -n "${RUST_APP_PORT:-}" ]]; then
  cmd+=( +app.port "${RUST_APP_PORT}" )
fi

if [[ -n "${RUST_EXTRA_ARGS:-}" ]]; then
  read -r -a extra <<<"${RUST_EXTRA_ARGS}"
  cmd+=("${extra[@]}")
fi

log "Launching: $(mask_args_for_log "${cmd[@]}")"
cd "${STEAM_INSTALL_DIR}"
exec gosu steam "${cmd[@]}"

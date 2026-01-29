# Soulmask Dedicated Server (Flux-friendly, headless)

Professional Soulmask dedicated server container designed for Flux Marketplace deployment.

Key goals:

- **Flux-friendly persistence**: persistent data lives under `/config` (recommended Flux `g:/config`)
- **Low syncthing churn**: Steam install + cache live under `/data` (recommended local/non-synced volume)
- **Consumer-friendly env vars**: server name, password, game mode, ports, player count, autosave/backup

## Ports

Default ports:

- `7777/udp` — game port
- `7777/tcp` — some hosts recommend opening TCP as well
- `27015/udp` — query port (Steam)

Optional:

- `18888/tcp` — echo / telnet admin port (used for graceful shutdown)
- `19000/tcp` — internal listener observed on startup (recommended to expose if clients cannot connect)

## Volumes

- `/config` — persistent settings + saves (on Flux use `g:/config`)
  - This container persists `WS/Saved` under `/config/WS/Saved`
- `/data` — Steam install + SteamCMD cache (on Flux keep this local to the node)

## Quick start (Docker)

```bash
docker run -d --name soulmask \
  -p 7777:7777/tcp \
  -p 7777:7777/udp \
  -p 27015:27015/udp \
  -p 18888:18888/tcp \
  -p 19000:19000/tcp \
  -e SOULMASK_SERVER_NAME="RunOnFlux - Soulmask" \
  -e SOULMASK_PASSWORD="test1234" \
  -e SOULMASK_ADMIN_PASSWORD="admin1234" \
  -e SOULMASK_GAME_MODE="pve" \
  -v "$PWD/soulmask-config:/config" \
  -v "$PWD/soulmask-data:/data" \
  littlestache/soulmask-flux:latest
```

To join in-game:

- Search for server name: `SOULMASK_SERVER_NAME` (if the server is publicly listed)
- Or connect via IP: `SERVER_IP:7777`
- Password: `SOULMASK_PASSWORD`

## Configuration (env vars)

### SteamCMD / install

- `AUTO_UPDATE` (default: `true`)
- `STEAM_APP_ID` (default: `3017300`) — Soulmask Dedicated Server tool (Linux)
- `STEAM_INSTALL_DIR` (default: `/data/server`)
- `STEAMCMD_HOME` (default: `/data/steam`)
- `STEAMCMD_LOG_FILE` (default: `/data/steam/steamcmd.log`)
- `STEAMCMD_VALIDATE` (default: `false`) — set `true` for slower but stricter updates
- `DISK_PREFLIGHT` (default: `true`)
- `MIN_FREE_GB` (default: `15`)

### Server basics (player-facing)

- `SOULMASK_SERVER_NAME` (default: `RunOnFlux - Soulmask`)
- `SOULMASK_MAP` (default: `Level01_Main`)
- `SOULMASK_GAME_MODE` (default: `pve`) — `pve` or `pvp`
- `SOULMASK_PASSWORD` (default: empty)
- `SOULMASK_ADMIN_PASSWORD` (default: empty) — used for the echo/telnet admin interface
- `SOULMASK_MAX_PLAYERS` (default: `20`)
- `SOULMASK_PORT` (default: `7777`) — UDP
- `SOULMASK_QUERY_PORT` (default: `27015`) — UDP
- `SOULMASK_ECHO_PORT` (default: `18888`) — TCP (admin/shutdown)
- Note: the server also opens `19000/tcp` by default (not configurable here); expose it if you cannot connect
- `SOULMASK_GAMEDISTINDEX` (default: `1`) — region/index (if supported by your server build)

### Saves / backups

- `SOULMASK_SAVING_INTERVAL` (default: `600`) — seconds
- `SOULMASK_BACKUP_INTERVAL` (default: `900`) — seconds
- `SOULMASK_INIT_BACKUP` (default: `true`) — if `true`, passes `-initbackup`
- `SOULMASK_BACKUP_INTERVAL_MINUTES` (default: `10`) — passes `-backupinterval` (minutes)

### Mods / advanced

- `SOULMASK_MOD_ID` (optional) — passes `-mod=<id>` (if supported by your server build)
- `SOULMASK_EXTRA_ARGS` (optional) — extra args appended to the server command
- `SOULMASK_SHUTDOWN_GRACE` (default: `180`) — seconds for `quit <seconds>` on shutdown
- `HARDEN_FLUX_VOLUME_BROWSER` (default: `true`) — `chmod 700` the top-level cache dirs under `/data` to reduce Flux volume explorer load

## Flux notes (recommended production layout)

This repo’s Flux pattern for survival/long-lived worlds is:

- **3 instances** (so `g:/config` is replicated)
- **2 components**
  - `data` → local `/data` volume (not synced)
  - `server` → `g:/config|0:/data` (saves synced, install local)

See `Gaming/soulmask/flux-spec.json` as a template.

## VPS test (required by repo rules)

On the VPS (`root@46.224.159.242`):

```bash
cd /root/flux-marketplace-dockers/Gaming/soulmask
rm -rf soulmask-config soulmask-data || true
docker compose down --remove-orphans || true
cp -f .env.example .env
docker compose up -d --build
docker logs -f soulmask-server
```

Health check:

```bash
docker inspect --format '{{.State.Health.Status}}' soulmask-server
```

Cleanup:

```bash
docker compose down -v
rm -rf soulmask-config soulmask-data
```

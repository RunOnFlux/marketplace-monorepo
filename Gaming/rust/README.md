# Rust Dedicated Server (Flux-friendly)

This folder builds a **headless, SteamCMD-based** Rust dedicated server container designed for Flux marketplace deployments:

- **No server binaries are shipped** in the image (installed/updated at runtime via SteamCMD).
- **/data** holds the Steam install + caches (recommended **local** volume on Flux).
- **/config** holds persistent identity/saves/config (recommended **synced `g:/config`** on Flux).

## Quick start (VPS / Docker)

On the VPS:

```bash
cd /path/to/flux-marketplace-dockers/Gaming/rust
cp .env.example .env
docker compose up -d --build
docker compose logs -f --tail=200 server
```

In Rust:
- Press `F1` and run: `client.connect 46.224.159.242:28015`

## Ports

Default Rust ports:
- `28015/udp` — game port
- `28016/tcp` — RCON (recommended; protect with password)
- `28017/udp` — query port

## Persistence

Mount these:
- `/data` (local; Steam install/cache)
- `/config` (persistent; server identity/saves/config)

Persistent server files are stored under:
- `/config/server/<identity>/`
  - `/config/server/<identity>/cfg/server.cfg`
  - saves, logs, etc.

## Environment variables (most important)

### Identity / listing
- `RUST_SERVER_IDENTITY` (default: `rust`)
- `RUST_SERVER_NAME`
- `RUST_SERVER_DESCRIPTION`
- `RUST_SERVER_TAGS`

### World settings
- `RUST_LEVEL` (default: `Procedural Map`)
- `RUST_SEED`
  - set a number (recommended) for a fixed world
  - or use `0` to auto-generate **once** and persist it to `/config/server/<identity>/seed.txt`
- `RUST_WORLD_SIZE` (default: `3000`)
- `RUST_MAX_PLAYERS` (default: `100`)
- `RUST_SAVE_INTERVAL` (default: `600` seconds)

### Failover safety (Flux)
When Flux fails over to another node, `g:/config` may take time to sync large world files. If the server starts without the world save present, it can generate a new world and you may see messages like:
“PlayerState was from old protocol or different seed… Clearing player state”.

This image mitigates that by waiting when it detects player data but no world save yet.

- `RUST_SYNC_WAIT_SECONDS` (default: `900`) — max time to wait for `*.map/*.sav` to appear in `/config/server/<identity>/`
- `RUST_SYNC_WAIT_FAIL` (default: `true`) — when `true`, the container exits instead of generating a new world (recommended)

### RCON (recommended)
- `RUST_RCON_PASSWORD` (**set this**)
- `RUST_RCON_PORT` (default: `28016`)
- `RUST_RCON_WEB` (`true/false`)

### Advanced config
- `RUST_SERVER_CFG_B64` — base64 text appended to `/config/server/<identity>/cfg/server.cfg`
- `RUST_EXTRA_ARGS` — extra args passed to `RustDedicated`

## Flux notes

### Recommended Flux volume layout
- `g:/config` → `/config` (synced; keeps world/config safe)
- `0:/data` → `/data` (local; faster; avoids syncing huge Steam install)

### Instances
The provided `flux-spec.json` is set to **3 instances** and uses **2 components** (`data` + `server`) to support the `0:/data` local cache volume pattern.

## Troubleshooting

- If the server won’t start, check SteamCMD logs: `/data/steam/steamcmd.log`
- If you see OOM or instability, raise Flux RAM and adjust `RUST_WORLD_SIZE` / `RUST_MAX_PLAYERS`.

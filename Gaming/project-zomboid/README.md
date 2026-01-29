# Project Zomboid Dedicated Server (Flux-friendly)

This folder builds a **headless, SteamCMD-based** Project Zomboid dedicated server container designed to be **Flux marketplace friendly**:

- **No server binaries are shipped** in the image (installed/updated at runtime via SteamCMD).
- **/data** holds the Steam install + caches (recommended **local** volume on Flux).
- **/config** holds persistent saves/config (recommended **synced `g:/config`** on Flux).

## Quick start (VPS / Docker)

On the VPS:

```bash
cd /path/to/flux-marketplace-dockers/Gaming/project-zomboid
cp .env.example .env
docker compose up -d --build
docker compose logs -f --tail=200 server
```

Connect in-game to:
- `46.224.159.242:16261` (UDP)

## Ports

Default ports per PZWiki:
- `16261/udp` — game port (clients connect here)
- `16262/udp` — UDP RakNet port

Optional:
- `27015/tcp` — RCON (if enabled)

## Persistence

Mount these:
- `/data` (local; Steam install/cache)
- `/config` (persistent; server config + saves)

Inside `/config` you’ll find:
- `/config/Zomboid/Server/<servername>.ini` (server settings)
- `/config/Zomboid/db/` (database)
- `/config/Zomboid/Saves/` (world saves)
- `/config/Zomboid/Logs/` (logs)

## Environment variables (most important)

### Identity / listing
- `PZ_SERVER_NAME` (default: `servertest`) — config file name (`/config/Zomboid/Server/<name>.ini`)
- `PZ_PUBLIC_NAME` — server list name
- `PZ_PUBLIC_DESCRIPTION` — server list description
- `PZ_PUBLIC` (`true/false`) — advertise publicly
- `PZ_OPEN` (`true/false`) — allow new players to join

### Gameplay basics
- `PZ_MAX_PLAYERS` (default: `16`)
- `PZ_PASSWORD` — join password (optional)
- `PZ_PVP` (`true/false`)
- `PZ_MAP` (default: `Muldraugh, KY`)
- `PZ_SAVE_EVERY_MINUTES` (default: `10`) — `SaveWorldEveryMinutes` in the server INI
- `PZ_MODS` — mods list (comma or semicolon separated)
- `PZ_WORKSHOP_ITEMS` — Steam Workshop IDs (comma or semicolon separated)

### Admin (non-interactive first boot)
Project Zomboid can prompt interactively for an admin password on first boot. This image avoids that by passing startup parameters:
- `PZ_ADMIN_USERNAME` (default: `admin`)
- `PZ_ADMIN_PASSWORD` (**required on first boot**)

### RCON (optional)
- `PZ_RCON_ENABLED` (`true/false`)
- `PZ_RCON_PORT` (default: `27015`)
- `PZ_RCON_PASSWORD`

### JVM heap (recommended for Flux)
- `PZ_JAVA_XMS` (default: `512m`)
- `PZ_JAVA_XMX` (default: `2048m`)

### Advanced configuration
If you need settings not exposed as env vars, you can append raw INI lines:
- `PZ_SERVER_INI_EXTRA_B64` — base64-encoded text appended to `/config/Zomboid/Server/<servername>.ini`

## Flux notes

### Recommended Flux volume layout
- `g:/config` → `/config` (synced; keeps world/config safe)
- `0:/data` → `/data` (local; faster; avoids syncing thousands of Steam files)

### Instances
The provided `flux-spec.json` is set to **3 instances** (Flux marketplace typical) and uses **2 components** (`data` + `server`) to support the `0:/data` local cache volume pattern.

## Troubleshooting

- If the server won’t start, check SteamCMD logs: `/data/steam/steamcmd.log`
- If you see Java OOMs, increase `PZ_JAVA_XMX` and Flux RAM tier.


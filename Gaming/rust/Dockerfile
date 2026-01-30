# Rust (Facepunch) Dedicated Server (Flux-friendly, headless)
# - Uses SteamCMD to install/update the official Linux dedicated server (appid 258550)
# - /data: local cache (Steam install + SteamCMD caches) (recommended non-synced volume on Flux)
# - /config: synced config + saves/worlds (recommended g:/ on Flux)
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Rust Dedicated Server (Flux-friendly)"
LABEL org.opencontainers.image.description="Official Rust dedicated server via SteamCMD, designed for Flux volumes and marketplace deployment."

ENV DEBIAN_FRONTEND=noninteractive

ENV STEAM_APP_ID=258550 \
    STEAM_INSTALL_DIR=/data/server \
    STEAM_LOGIN=anonymous \
    STEAM_PASSWORD= \
    STEAM_GUARD= \
    STEAM_BRANCH= \
    STEAM_BRANCH_PASSWORD= \
    STEAMCMD_EXTRA_ARGS= \
    STEAMCMD_HOME=/data/steam \
    STEAMCMD_LOG_FILE=/data/steam/steamcmd.log \
    STEAMCMD_VALIDATE=false \
    STEAMCMD_RETRIES=3 \
    AUTO_UPDATE=true \
    DISK_PREFLIGHT=true \
    MIN_FREE_GB=15 \
    HARDEN_FLUX_VOLUME_BROWSER=true

# Common server settings (keep Flux-spec env list <= 20; advanced settings can go in RUST_SERVER_CFG_B64)
ENV RUST_SERVER_IDENTITY=rust \
    RUST_SERVER_NAME="RunOnFlux - Rust" \
    RUST_SERVER_DESCRIPTION="Rust dedicated server on Flux." \
    RUST_SERVER_URL= \
    RUST_SERVER_HEADERIMAGE= \
    RUST_SERVER_TAGS="vanilla,flux" \
    RUST_SERVER_PORT=28015 \
    RUST_SERVER_QUERYPORT=28017 \
    RUST_RCON_PORT=28016 \
    RUST_RCON_PASSWORD= \
    RUST_RCON_WEB=true \
    RUST_APP_PORT= \
    RUST_MAX_PLAYERS=100 \
    RUST_LEVEL="Procedural Map" \
    RUST_SEED=0 \
    RUST_WORLD_SIZE=3000 \
    RUST_SAVE_INTERVAL=600 \
    RUST_TICKRATE=30 \
    RUST_SERVER_SECURE=true \
    RUST_SERVER_IP=0.0.0.0 \
    RUST_WRITE_CFG=true \
    RUST_SERVER_CFG_B64= \
    RUST_EXTRA_ARGS=

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     ca-certificates \
     gosu \
     procps \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /config \
  && chown -R steam:steam /data /config

COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --chmod=755 healthcheck.sh /healthcheck.sh

WORKDIR /home/steam

# Rust ports (default):
# - 28015/udp game
# - 28016/tcp rcon (if enabled)
# - 28017/udp query
EXPOSE 28015/udp 28016/tcp 28017/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20m --retries=3 \
  CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]


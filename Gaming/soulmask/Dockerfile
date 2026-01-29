# Soulmask Dedicated Server (Flux-friendly, headless)
# - Installs/updates the official Linux dedicated server via SteamCMD (appid 3017300)
# - /data: local cache (Steam install + SteamCMD caches) (recommended non-synced volume on Flux)
# - /config: synced config + saves/worlds (recommended g:/ on Flux)
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Soulmask Dedicated Server (Flux-friendly)"
LABEL org.opencontainers.image.description="Official Soulmask dedicated server via SteamCMD, designed for Flux volumes and marketplace deployment."

ENV DEBIAN_FRONTEND=noninteractive

ENV STEAM_APP_ID=3017300 \
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

ENV SOULMASK_SERVER_NAME="RunOnFlux - Soulmask" \
    SOULMASK_MAP="Level01_Main" \
    SOULMASK_GAME_MODE="pve" \
    SOULMASK_PASSWORD= \
    SOULMASK_ADMIN_PASSWORD= \
    SOULMASK_MAX_PLAYERS=20 \
    SOULMASK_PORT=7777 \
    SOULMASK_QUERY_PORT=27015 \
    SOULMASK_ECHO_PORT=18888 \
    SOULMASK_SAVING_INTERVAL=600 \
    SOULMASK_BACKUP_INTERVAL=900 \
    SOULMASK_INIT_BACKUP=true \
    SOULMASK_BACKUP_INTERVAL_MINUTES=10 \
    SOULMASK_GAMEDISTINDEX=1 \
    SOULMASK_MOD_ID= \
    SOULMASK_EXTRA_ARGS= \
    SOULMASK_SHUTDOWN_GRACE=180

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     ca-certificates \
     gosu \
     iproute2 \
     netcat-openbsd \
     procps \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /config \
  && chown -R steam:steam /data /config

COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --chmod=755 healthcheck.sh /healthcheck.sh

WORKDIR /home/steam

EXPOSE 7777/udp 27015/udp 18888/tcp 19000/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20m --retries=3 \
  CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]

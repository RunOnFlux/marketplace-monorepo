# Project Zomboid Dedicated Server (Flux-friendly, headless)
# - Uses SteamCMD to install/update the official dedicated server tool (appid 380870)
# - /data: local cache (Steam install + SteamCMD caches) (recommended non-synced volume on Flux)
# - /config: synced config + saves/worlds (recommended g:/ on Flux)
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Project Zomboid Dedicated Server (Flux-friendly)"
LABEL org.opencontainers.image.description="Official Project Zomboid dedicated server via SteamCMD, designed for Flux volumes and marketplace deployment."

ENV DEBIAN_FRONTEND=noninteractive

ENV STEAM_APP_ID=380870 \
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
    MIN_FREE_GB=10 \
    HARDEN_FLUX_VOLUME_BROWSER=true

ENV PZ_MANAGE_CONFIG=true \
    PZ_SERVER_NAME=servertest \
    PZ_PORT=16261 \
    PZ_UDP_PORT=16262 \
    PZ_PUBLIC=true \
    PZ_PUBLIC_NAME="RunOnFlux - Project Zomboid" \
    PZ_PUBLIC_DESCRIPTION="Project Zomboid dedicated server on Flux." \
    PZ_MAX_PLAYERS=16 \
    PZ_PASSWORD= \
    PZ_PVP=false \
    PZ_PAUSE_EMPTY=true \
    PZ_GLOBAL_CHAT=true \
    PZ_OPEN=true \
    PZ_MAP="Muldraugh, KY" \
    PZ_SAVE_EVERY_MINUTES=10 \
    PZ_MODS= \
    PZ_WORKSHOP_ITEMS= \
    PZ_RCON_ENABLED=false \
    PZ_RCON_PORT=27015 \
    PZ_RCON_PASSWORD= \
    PZ_ADMIN_USERNAME=admin \
    PZ_ADMIN_PASSWORD= \
    PZ_NOSTEAM=false \
    PZ_JAVA_XMS=512m \
    PZ_JAVA_XMX=2048m \
    PZ_SERVER_INI_EXTRA_B64= \
    PZ_EXTRA_ARGS=

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

# Default ports per PZWiki:
# - 16261/udp: game port (clients connect here)
# - 16262/udp: UDP RakNet port
EXPOSE 16261/udp 16262/udp

# Optional RCON (disabled by default)
EXPOSE 27015/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20m --retries=3 \
  CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]


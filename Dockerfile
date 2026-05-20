FROM python:3.13-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/config/.cache

ARG S6_OVERLAY_VERSION=3.2.1.0
ARG TARGETARCH
ARG YTDLP_PIP_SPEC=yt-dlp
ARG SUPERCRONIC_VERSION=0.2.33

# ffmpeg (pre-built binary, no compilation)
ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip xz-utils gosu cron \
        nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "$FFMPEG_URL" \
       | tar -xJ --strip-components=2 -C /usr/local/bin --wildcards '*/bin/ff*' \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && echo "ffmpeg: $(ffmpeg -version 2>&1 | head -1)" \
    && echo "node:   $(node --version)"

RUN set -eux; \
        ARCH="${TARGETARCH:-}"; \
        if [ -z "$ARCH" ]; then \
            ARCH="$(dpkg --print-architecture)"; \
        fi; \
        case "$ARCH" in \
            amd64) DENO_ARCH="x86_64-unknown-linux-gnu" ;; \
            arm64) DENO_ARCH="aarch64-unknown-linux-gnu" ;; \
            *) echo "Unsupported arch: $ARCH"; exit 1 ;; \
        esac; \
        curl -fsSL -o /tmp/deno.zip "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}.zip"; \
        unzip -q /tmp/deno.zip -d /usr/local/bin; \
        chmod +x /usr/local/bin/deno; \
        rm -f /tmp/deno.zip; \
        echo "deno:   $(deno --version | head -1)"

RUN set -eux; \
        ARCH="${TARGETARCH:-}"; \
        if [ -z "$ARCH" ]; then \
            ARCH="$(dpkg --print-architecture)"; \
        fi; \
        case "$ARCH" in \
            amd64) SC_ARCH="linux-amd64" ;; \
            arm64) SC_ARCH="linux-arm64" ;; \
            *) echo "Unsupported arch: $ARCH"; exit 1 ;; \
        esac; \
        curl -fsSL -o /usr/local/bin/supercronic "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-${SC_ARCH}"; \
        chmod +x /usr/local/bin/supercronic; \
        echo "supercronic: $(/usr/local/bin/supercronic --version 2>/dev/null || echo 'installed')"

RUN set -eux; \
        ARCH="${TARGETARCH:-}"; \
        if [ -z "$ARCH" ]; then \
            ARCH="$(dpkg --print-architecture)"; \
        fi; \
        case "$ARCH" in \
            amd64) S6_ARCH="x86_64" ;; \
            arm64) S6_ARCH="aarch64" ;; \
            *) echo "Unsupported arch: $ARCH"; exit 1 ;; \
        esac; \
        curl -fsSL -o /tmp/s6-noarch.tar.xz "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz"; \
        curl -fsSL -o /tmp/s6-arch.tar.xz "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz"; \
        tar -C / -Jxpf /tmp/s6-noarch.tar.xz; \
        tar -C / -Jxpf /tmp/s6-arch.tar.xz; \
        rm -f /tmp/s6-noarch.tar.xz /tmp/s6-arch.tar.xz

RUN pip install --no-cache-dir \
    "${YTDLP_PIP_SPEC}" \
    "mutagen>=1.47.0" \
    "pyyaml>=6.0.2" \
    "bgutil-ytdlp-pot-provider>=1.3.1" \
    "requests>=2.31.0"

RUN yt-dlp --version && deno --version

# User abc (linuxserver-like PUID/PGID pattern)
RUN groupadd -g 1000 abc && useradd -u 1000 -g abc -s /bin/bash -d /app abc

WORKDIR /app
COPY sync.py ./
COPY rootfs/ /
RUN chmod +x /etc/cont-init.d/10-user-setup \
    /etc/services.d/ytmusic-sync/run \
    /usr/local/bin/healthcheck.sh \
    && test -x /command/with-contenv \
    && test -f /etc/cont-init.d/10-user-setup \
    && test -f /etc/services.d/ytmusic-sync/run

VOLUME ["/config", "/music"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/init"]

FROM python:3.13-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG S6_OVERLAY_VERSION=3.2.1.0
ARG TARGETARCH
ARG YTDLP_PIP_SPEC=yt-dlp

# ffmpeg (pre-built binary, no compilation)
ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils gosu cron \
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
    "bgutil-ytdlp-pot-provider>=1.3.1"

RUN yt-dlp --version && node --version

# User abc (linuxserver-like PUID/PGID pattern)
RUN groupadd -g 1000 abc && useradd -u 1000 -g abc -s /bin/bash -d /app abc

WORKDIR /app
COPY sync.py ./
COPY rootfs/ /
RUN chmod +x /etc/cont-init.d/10-user-setup \
    /etc/services.d/ytmusic-sync/run \
    /usr/local/bin/healthcheck.sh

VOLUME ["/config", "/music"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/init"]

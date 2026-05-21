FROM python:3.13-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/config/.cache

ARG TARGETARCH
ARG YTDLP_PIP_SPEC=yt-dlp

# ffmpeg (pre-built binary, no compilation)
ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip xz-utils gosu \
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
RUN chmod +x /usr/local/bin/entrypoint.sh \
    /usr/local/bin/run-sync-logged.py \
    /usr/local/bin/healthcheck.sh \
    && test -f /usr/local/bin/entrypoint.sh

VOLUME ["/config", "/music"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

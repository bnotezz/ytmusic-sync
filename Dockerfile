FROM python:3.12-slim

# ── ffmpeg (pre-built, не компілює) ──────────────────────────────────────────
ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils gosu cron \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "$FFMPEG_URL" \
       | tar -xJ --strip-components=2 -C /usr/local/bin --wildcards '*/bin/ff*' \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && echo "ffmpeg: $(ffmpeg -version 2>&1 | head -1)" \
    && echo "node:   $(node --version)" \
    && echo "npm:    $(npm --version)"

# ── Python залежності + bgutil yt-dlp плагін ─────────────────────────────────
RUN pip install --no-cache-dir \
    "yt-dlp>=2025.1.1" \
    "mutagen>=1.47.0" \
    "pyyaml>=6.0.2" \
    "bgutil-ytdlp-pot-provider>=1.3.1"

# ── Перевірити що yt-dlp бачить node як JS runtime ───────────────────────────
RUN yt-dlp --version && node --version

# ── Користувач abc — linuxserver стиль ───────────────────────────────────────
RUN groupadd -g 1000 abc && useradd -u 1000 -g abc -s /bin/bash -d /app abc

WORKDIR /app
COPY sync.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME ["/config", "/music"]

CMD ["./entrypoint.sh"]

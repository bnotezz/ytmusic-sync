FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    cron \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir yt-dlp mutagen pyyaml

WORKDIR /app
COPY sync.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD test -f /tmp/ytmusic-sync-alive || exit 1

CMD ["./entrypoint.sh"]

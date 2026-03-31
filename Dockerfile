# ytmusic-sync — оптимізовано для Synology DS720+ (x86_64, DSM 7.x)
FROM python:3.12-slim

# Статичний pre-built ffmpeg від yt-dlp проекту
# Не компілює — просто завантажує готові бінарники (~60MB, ~20с)
ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cron ca-certificates curl xz-utils gosu \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "$FFMPEG_URL" \
       | tar -xJ --strip-components=2 -C /usr/local/bin --wildcards '*/bin/ff*' \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && ffmpeg -version | head -1

# Python залежності
RUN pip install --no-cache-dir \
    "yt-dlp>=2025.1.1" \
    "mutagen>=1.47.0" \
    "pyyaml>=6.0.2"

# Користувач abc — linuxserver стиль
RUN groupadd -g 1000 abc && useradd -u 1000 -g abc -s /bin/bash -d /app abc

WORKDIR /app
COPY sync.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

# /config — config.yml + cookies.txt (монтується з хоста)
# /music  — вихідна музика (монтується з NFS або Synology тому)
VOLUME ["/config", "/music"]

CMD ["./entrypoint.sh"]

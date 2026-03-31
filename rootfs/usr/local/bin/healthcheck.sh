#!/usr/bin/env sh
set -eu

[ -f /config/config.yml ] || exit 1
[ -L /app/config.yml ] || exit 1
command -v yt-dlp >/dev/null 2>&1 || exit 1
command -v ffmpeg >/dev/null 2>&1 || exit 1
command -v node >/dev/null 2>&1 || exit 1

crontab -l -u root >/dev/null 2>&1 || exit 1

exit 0

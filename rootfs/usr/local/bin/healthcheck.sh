#!/usr/bin/env sh
set -eu

[ -f /config/config.yml ] || exit 1
[ -L /app/config.yml ] || exit 1
command -v yt-dlp >/dev/null 2>&1 || exit 1
command -v ffmpeg >/dev/null 2>&1 || exit 1
command -v deno >/dev/null 2>&1 || exit 1

if [ "${DISABLE_CRON:-0}" != "1" ]; then
    pgrep -f "supercronic /app/crontab" >/dev/null 2>&1 || exit 1
fi

POT_SERVER_URL="$(python - <<'PY'
from pathlib import Path

import yaml

cfg_path = "/config/config.yml"
value = ""
if Path(cfg_path).exists():
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    value = ((cfg.get("settings") or {}).get("pot_server_url") or "").strip()
print(value)
PY
)"

if [ -n "${POT_SERVER_URL}" ]; then
	POT_PING_URL="${POT_SERVER_URL%/}/ping"
	curl -sS --max-time 5 -o /dev/null "${POT_PING_URL}" || exit 1
fi

exit 0

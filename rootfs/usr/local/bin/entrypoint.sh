#!/usr/bin/env sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "[init] PUID=${PUID} PGID=${PGID}"

groupmod -o -g "${PGID}" abc 2>/dev/null || true
usermod -o -u "${PUID}" abc 2>/dev/null || true

mkdir -p /config /music /app /config/.cache
chown abc:abc /config /music /config/.cache 2>/dev/null || true

if [ ! -f /config/config.yml ]; then
  echo "[init] /config/config.yml not found"
  echo "[init] Copy config.example.yml to /config/config.yml and set playlist URLs"
  exit 1
fi

ln -sf /config/config.yml /app/config.yml

if [ -f /config/cookies.txt ]; then
  chown abc:abc /config/cookies.txt 2>/dev/null || true
  chmod 664 /config/cookies.txt 2>/dev/null || true
  ln -sf /config/cookies.txt /app/cookies.txt
fi

export XDG_CACHE_HOME="/config/.cache"

if [ "$#" -gt 0 ]; then
  exec gosu abc "$@"
fi

exec gosu abc python -u /usr/local/bin/run-sync-logged.py
#!/bin/bash
set -e

# ── PUID/PGID — linuxserver стиль ────────────────────────────────────────────
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "[init] Запуск від PUID=$PUID PGID=$PGID"

# Оновити GID/UID користувача abc
groupmod -o -g "$PGID" abc 2>/dev/null || true
usermod  -o -u "$PUID" abc 2>/dev/null || true

# Права на /config та /music
chown -R abc:abc /config 2>/dev/null || true
chown -R abc:abc /music  2>/dev/null || true

# Перевірити що config.yml є
if [ ! -f /config/config.yml ]; then
    echo "[init] ПОМИЛКА: /config/config.yml не знайдено!"
    echo "[init] Скопіюй config.example.yml → /config/config.yml і заповни URL плейлістів"
    exit 1
fi

# Симлінк config у /app для sync.py
ln -sf /config/config.yml /app/config.yml
[ -f /config/cookies.txt ] && ln -sf /config/cookies.txt /app/cookies.txt

# ── Перший запуск ─────────────────────────────────────────────────────────────
SCHEDULE="${SYNC_SCHEDULE:-0 3 * * 0}"
echo "[init] Розклад: $SCHEDULE"

echo "[init] Перший запуск синхронізації..."
gosu abc python /app/sync.py

# ── Cron ─────────────────────────────────────────────────────────────────────
echo "$SCHEDULE gosu abc python /app/sync.py >> /config/sync.log 2>&1" | crontab -u root -
echo "[init] Cron запущено. Наступний: $SCHEDULE"
cron -f

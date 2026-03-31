#!/bin/bash
set -e

SCHEDULE="${SYNC_SCHEDULE:-0 3 * * 0}"

echo "[entrypoint] Перший запуск синхронізації..."
python /app/sync.py && touch /tmp/ytmusic-sync-alive

echo "[entrypoint] Налаштовую cron: $SCHEDULE"
echo "$SCHEDULE python /app/sync.py >> /var/log/ytmusic-sync.log 2>&1 && touch /tmp/ytmusic-sync-alive" | crontab -

echo "[entrypoint] Cron запущено. Наступний запуск: $SCHEDULE"
cron -f

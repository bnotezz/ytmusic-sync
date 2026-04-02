#!/usr/bin/env sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p local/config local/music

URL="${1:-https://music.youtube.com/watch?v=BKdXNhY1oyY}"
DEFAULT_POT_URL="http://127.0.0.1:4416"

if [ "${NO_POT:-0}" = "1" ]; then
  EFFECTIVE_POT_URL=""
elif [ -n "${POT_SERVER_URL:-}" ]; then
  EFFECTIVE_POT_URL="${POT_SERVER_URL}"
else
  EFFECTIVE_POT_URL="${DEFAULT_POT_URL}"
fi

echo "[local-test] project root: $ROOT_DIR"
echo "[local-test] config dir:   $ROOT_DIR/local/config"
echo "[local-test] music dir:    $ROOT_DIR/local/music"
if [ "${NO_POT:-0}" = "1" ]; then
  echo "[local-test] PO Token mode: DISABLED (NO_POT=1)"
fi
if [ -n "${EFFECTIVE_POT_URL}" ]; then
  echo "[local-test] POT server:   ${EFFECTIVE_POT_URL} (will be written to settings.pot_server_url)"
else
  echo "[local-test] POT server:   disabled (settings.pot_server_url will be empty)"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[local-test] ERROR: docker command not found"
  echo "[local-test] Install Docker Desktop (or Colima) and try again."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[local-test] ERROR: Docker daemon is not running"
  echo "[local-test] Start Docker Desktop and wait until status is 'Engine running'."
  echo "[local-test] Then rerun: ./scripts/local-test.sh \"$URL\""
  exit 1
fi

cat > local/config/config.yml <<EOF
playlists:
  - name: local-test
    url: "$URL"
    output_dir: /music/local-test
    format: opus

settings:
  playlists_dir: /music/playlists
  archive_dir: /music/.sync
  cookies_file: /config/cookies.txt
  sleep_interval: 1
  pot_server_url: "${EFFECTIVE_POT_URL}"
EOF

if [ -f local/config/cookies.txt ]; then
  echo "[local-test] using local/config/cookies.txt"
else
  echo "[local-test] cookies not found (local/config/cookies.txt); continuing without cookies"
fi

echo "[local-test] URL: $URL"
echo "[local-test] building and starting test container..."
compose_cmd="docker compose -f docker-compose.yml -f docker-compose.local.yml"
if [ "${NO_BUILD:-0}" = "1" ]; then
  echo "[local-test] NO_BUILD=1 -> starting without rebuild"
  $compose_cmd up -d
else
  $compose_cmd up -d --build
fi

echo "[local-test] tailing container logs (Ctrl+C to stop view)"
$compose_cmd logs -f ytmusic-sync

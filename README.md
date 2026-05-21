# ytmusic-sync

Сервіс для синхронізації YouTube Music плейлістів у локальні аудіофайли з генерацією `.m3u` плейлістів.

Проєкт орієнтований на Synology DS720+ (DSM 7, `linux/amd64`).

`bgutil-ytdlp-pot-provider` використовується як окремий, уже встановлений контейнер на тому ж сервері.

## Актуальні версії (image)

- Python: `3.13` (`python:3.13-slim-bookworm`)
- yt-dlp: latest на момент збірки образу
- ffmpeg: latest static build з `yt-dlp/FFmpeg-Builds` на момент збірки
- Deno: latest stable runtime на момент збірки

## Як працює

1. Скрипт читає `config.yml`.
2. Для кожного плейліста отримує актуальний список video ID.
3. Видаляє локальні треки, яких більше немає в плейлісті.
4. Дозавантажує нові треки через `yt-dlp` (audio only).
5. Нормалізує теги (прибирає `language` для opus, додає `albumartist`, якщо його немає).
6. Опційно робить enrich метаданих через MusicBrainz.
7. Записує `.m3u` поруч із файлами плейліста та створює `folder.jpg` / `cover.jpg` у тій самій папці.
8. У `.m3u` додає MA-friendly metadata (`#PLAYLIST`, `#EXTMA`, `#EXTARTIST`, `#EXTALBUM`, `#EXTIMG`) включно з оригінальним YT Music URL треку.
9. Повторює запуск за розкладом через зовнішній scheduler, наприклад Synology Task Scheduler.

## Runtime модель

Проєкт має 1 роль:

1. `ytmusic-sync` — one-shot worker:
- готує runtime (`PUID/PGID`, `/config`, `/music`, symlink `/app/config.yml`);
- запускає один sync (`python -u /usr/local/bin/run-sync-logged.py`);
- завершує роботу.

Розклад робиться зовні, через Synology Task Scheduler або інший зовнішній scheduler.

## Залежності в контейнері

- Python 3.13
- `yt-dlp` (latest під час build)
- `ffmpeg` (готовий static build, без компіляції)
- `nodejs` (JS runtime для yt-dlp)
- `bgutil-ytdlp-pot-provider` python plugin
- `deno` (JS runtime для yt-dlp)

## Швидкий старт (Synology)

### 1. Створи каталоги на NAS

```bash
mkdir -p /volume1/docker/ytmusic-sync/config
mkdir -p /volume1/music/kids
```

### 2. Скопіюй конфіг

```bash
cp config.example.yml /volume1/docker/ytmusic-sync/config/config.yml
```

В `config.yml` заміни `url` на свої YouTube Music playlist URL.
Для локального тесту контейнер запускається з мінімальним профілем yt-dlp, щоб швидше ізолювати проблеми з POT / JS runtime / metadata.
### 3. Налаштуй PUID/PGID

```bash
id <synology_user>
```

Постав ці значення в `docker-compose.yml`:
- `PUID`
- `PGID`

### 4. Налаштуй POT у config.yml

Єдине місце налаштування POT:

- `settings.pot_server_url` у `/config/config.yml`

Приклади:

- `pot_server_url: "http://127.0.0.1:4416"`
- `pot_server_url: "http://192.168.1.1:4416"`
- `pot_server_url: ""` (вимкнено)

### 5A. Варіант через Synology Container Manager (Project Create)

1. Відкрий `Container Manager` -> `Project` -> `Create`.
2. `Project Name`: `ytmusic-sync`.
3. `Path`: папка з цим проєктом, наприклад `/volume1/docker/ytmusic-sync`.
4. Переконайся, що `docker-compose.yml` і `config/config.yml` на місці.
5. Натисни `Next` -> `Done` (або `Create`) -> `Build and start`.
6. Відкрий логи контейнера `ytmusic-sync` у UI та перевір перший sync.

### 5B. Варіант через Synology Task Scheduler

Створи задачу, яка запускає один sync:

```bash
cd /volume1/docker/ytmusic-sync && docker compose run --rm ytmusic-sync
```

Якщо хочеш запускати через окрему оболонку без compose, можна використати:

```bash
docker run --rm --network host \
  -e PUID=1026 -e PGID=100 -e TZ=Europe/Kyiv \
  -e HEALTHCHECKS_UUID=df32dfdsf-fdsfdsf-4755-uhiuh-11111111111 \
  -v /volume1/docker/ytmusic-sync/config:/config \
  -v /volume1/music/kids:/music \
  ytmusic-sync:latest
```

### 5C. Варіант через SSH / docker compose

```bash
cd /volume1/docker/ytmusic-sync
docker compose run --rm ytmusic-sync
```

## Docker Compose схема

У `docker-compose.yml` запускається тільки `ytmusic-sync`.

Зовнішній scheduler викликає `docker compose run --rm ytmusic-sync` за розкладом.

`bgutil-ytdlp-pot-provider` залишається зовнішнім сервісом.

## Файли та каталоги

- `/config/config.yml` - основний конфіг.
- `/config/cookies.txt` - optional cookies для приватних плейлістів.
- `/config/sync.log` - персистентний лог запусків sync.
- `/music/<playlist_dir>` - аудіофайли.
- `/music/<playlist_dir>/*.m3u` - згенерований плейліст поруч із файлами.
- `/music/<playlist_dir>/folder.jpg` / `/music/<playlist_dir>/cover.jpg` - thumbnail для Kodi / Music Assistant.
- `/music/.sync/*.ytdlp.archive` - архів уже завантажених ID.

## Приклад `config.yml`

```yaml
playlists:
  - name: tales
    url: "https://music.youtube.com/playlist?list=PL..."
    output_dir: /music/tales
    format: opus

settings:
  archive_dir: /music/.sync
  cookies_file: /config/cookies.txt
  sleep_interval: 2
  musicbrainz_enrich: false
  musicbrainz_min_interval_sec: 1.1
  pot_server_url: "http://192.168.1.1:4416" # або "" для вимкнення
```

За замовчуванням `.m3u` пишеться в `output_dir` кожного плейліста. Якщо треба іншу папку, додай `playlist_dir` у відповідний елемент `playlists`.

`musicbrainz_enrich: true` увімкне доповнення тегів (`musicbrainz_recordingid`, `musicbrainz_artistid`, `musicbrainz_albumid`, а також `album/date` якщо бракує).

## Параметри середовища (`docker-compose.yml`)

- `SYNC_PUID` - UID користувача-власника файлів (`1026` за замовчуванням).
- `SYNC_PGID` - GID групи-власника файлів (`100` за замовчуванням).
- `SYNC_CONFIG_PATH` - шлях до config каталогу (`/volume1/docker/ytmusic-sync/config`).
- `SYNC_MUSIC_PATH` - шлях до music каталогу (`/volume1/music/kids`).
- `TZ` - часовий пояс.
- `HEALTHCHECKS_UUID` - UUID для Healthchecks.io.
- `HA_URL` - optional Home Assistant URL.
- `HA_TOKEN` - optional Home Assistant Long-lived token.

## Розклад через Synology

Рекомендований шлях: Synology Task Scheduler запускає `docker compose run --rm ytmusic-sync`.

Персистентний лог sync:

```bash
tail -n 200 /volume1/docker/ytmusic-sync/config/sync.log
```

## Healthchecks integration

If you use Healthchecks.io for uptime/monitoring, set `HEALTHCHECKS_UUID` in `docker-compose.yml` (see example in `docker-compose.yml`). The container sends three pings per run:

- `https://hc-ping.com/<UUID>/start` at the beginning of the sync
- `https://hc-ping.com/<UUID>` on success (POST body contains a short summary)
- `https://hc-ping.com/<UUID>/fail` on failure (POST body contains error details)

This provides alerts when the container silent-fails or when a sync run fails.

POT налаштовується тільки через `settings.pot_server_url` у `/config/config.yml`.

## Ручний запуск синхронізації

```bash
docker compose run --rm ytmusic-sync
```

## Оновлення контейнера

```bash
cd /volume1/docker/ytmusic-sync
git pull
docker compose up -d --build
```

Для Synology Project Create оновлення робиться через `Project` -> `Action` -> `Rebuild` / `Restart`.

## Інтеграція з Music Assistant

1. Додай Local Files provider.
2. Шлях до бібліотеки: `/volume1/music/kids`.
3. Запусти scan.

Плейлісти з `playlists/*.m3u` будуть доступні в MA.

## Оптимізація build для DS720+

У Dockerfile вже закладено швидкий build-підхід:

1. `ffmpeg` береться готовим binary release.
2. Встановлюються тільки потрібні пакети (`--no-install-recommends`).
3. `npm` прибрано як зайва залежність для цього сценарію.
4. `pip` встановлює залежності без cache (`--no-cache-dir`).
5. Scheduler винесено назовні, worker-контейнер одноразовий і простіший у підтримці.

Для швидких оновлень використовуй:

```bash
docker compose up -d --build
```

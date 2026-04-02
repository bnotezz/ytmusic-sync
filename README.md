# ytmusic-sync

Сервіс для синхронізації YouTube Music плейлістів у локальні аудіофайли з генерацією `.m3u` плейлістів.

Проєкт орієнтований на Synology DS720+ (DSM 7, `linux/amd64`).

`bgutil-ytdlp-pot-provider` використовується як окремий, уже встановлений контейнер на тому ж сервері.

## Актуальні версії (image)

- Python: `3.13` (`python:3.13-slim-bookworm`)
- yt-dlp: latest на момент збірки образу
- ffmpeg: latest static build з `yt-dlp/FFmpeg-Builds` на момент збірки
- Deno: latest stable runtime на момент збірки
- s6-overlay: `3.2.1.0`

## Як працює

1. Скрипт читає `config.yml`.
2. Для кожного плейліста отримує актуальний список video ID.
3. Видаляє локальні треки, яких більше немає в плейлісті.
4. Дозавантажує нові треки через `yt-dlp` (audio only).
5. Оновлює `.m3u` у папці `playlists_dir`.
6. Повторює запуск за cron-розкладом `SYNC_SCHEDULE`.

## Linuxserver-style runtime

Контейнер запускається через `s6-overlay` (`/init`):

1. `cont-init.d`:
- застосовує `PUID/PGID` до користувача `abc`;
- перевіряє наявність `/config/config.yml`;
- створює symlink `/app/config.yml`.

2. `services.d/ytmusic-sync`:
- робить перший sync при старті;
- ставить cron job;
- тримає контейнер у foreground через `cron -f`.

3. `HEALTHCHECK`:
- перевіряє конфіг, symlink і доступність `yt-dlp`, `ffmpeg`, `node`.

## Залежності в контейнері

- Python 3.13
- `yt-dlp` (latest під час build)
- `ffmpeg` (готовий static build, без компіляції)
- `nodejs` (JS runtime для yt-dlp)
- `bgutil-ytdlp-pot-provider` python plugin
- `deno` (JS runtime для yt-dlp)
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
- `pot_server_url: "http://192.168.50.192:4416"`
- `pot_server_url: ""` (вимкнено)

### 5A. Варіант через Synology Container Manager (Project Create)

1. Відкрий `Container Manager` -> `Project` -> `Create`.
2. `Project Name`: `ytmusic-sync`.
3. `Path`: папка з цим проєктом, наприклад `/volume1/docker/ytmusic-sync`.
4. Переконайся, що `docker-compose.yml` і `config/config.yml` на місці.
5. Натисни `Next` -> `Done` (або `Create`) -> `Build and start`.
6. Відкрий логи контейнера `ytmusic-sync` у UI та перевір перший sync.

### 5B. Варіант через SSH / docker compose

```bash
cd /volume1/docker/ytmusic-sync
docker compose up -d --build
docker compose logs -f ytmusic-sync
```

## Docker Compose схема

У `docker-compose.yml` запускається тільки `ytmusic-sync`.

`bgutil-ytdlp-pot-provider` залишається зовнішнім сервісом.

## Файли та каталоги

- `/config/config.yml` - основний конфіг.
- `/config/cookies.txt` - optional cookies для приватних плейлістів.
- `/config/sync.log` - лог cron-запусків.
- `/music/<playlist_dir>` - аудіофайли.
- `/music/playlists/*.m3u` - згенеровані плейлісти.
- `/music/.sync/*.ytdlp.archive` - архів уже завантажених ID.

## Приклад `config.yml`

```yaml
playlists:
  - name: tales
    url: "https://music.youtube.com/playlist?list=PL..."
    output_dir: /music/tales
    format: opus

settings:
  playlists_dir: /music/playlists
  archive_dir: /music/.sync
  cookies_file: /config/cookies.txt
  sleep_interval: 2
  pot_server_url: "http://192.168.50.192:4416" # або "" для вимкнення
```

## Параметри середовища (`docker-compose.yml`)

- `PUID` - UID користувача-власника файлів.
- `PGID` - GID групи-власника файлів.
- `SYNC_SCHEDULE` - cron, за замовчуванням `0 3 * * 0`.
- `TZ` - часовий пояс.
- `HA_URL` - optional Home Assistant URL.
- `HA_TOKEN` - optional Home Assistant Long-lived token.

POT налаштовується тільки через `settings.pot_server_url` у `/config/config.yml`.

## Ручний запуск синхронізації

```bash
docker exec ytmusic-sync gosu abc python /app/sync.py
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
5. s6-init і сервіси додаються як lightweight runtime-шар без зміни логіки sync.

Для швидких оновлень використовуй:

```bash
docker compose up -d --build
```

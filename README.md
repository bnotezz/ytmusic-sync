# ytmusic-sync

Синхронізація YouTube Music плейлістів на Synology NAS з генерацією `.m3u` для Music Assistant.

**Оптимізовано для:** Synology DS720+ (Celeron J4125, x86_64), DSM 7.x, Container Manager.

---

## Швидкий старт

### 1. Структура папок на Synology

Через File Station або SSH:

```
/volume1/docker/ytmusic-sync/
└── config/
    ├── config.yml      ← твої плейлісти
    └── cookies.txt     ← опціонально (приватні плейлісти)

/volume1/music/kids/    ← тут буде музика + .m3u файли
```

```bash
# SSH → Synology
mkdir -p /volume1/docker/ytmusic-sync/config
mkdir -p /volume1/music/kids
```

### 2. Дізнатись PUID/PGID

```bash
# SSH → Synology
id твій_користувач
# uid=1026(denys) gid=100(users) ...
```

Вписати в `docker-compose.yml`: `PUID=1026`, `PGID=100`.

### 3. Налаштувати config.yml

```bash
cp config.example.yml /volume1/docker/ytmusic-sync/config/config.yml
# Відредагуй через File Station → Text Editor або nano:
nano /volume1/docker/ytmusic-sync/config/config.yml
```

Замінити URL плейлістів на свої. ID плейліста знаходиться в URL:
`music.youtube.com/playlist?list=`**`PLR8OfFTQ5xt...`**

### 4. Скопіювати файли проекту

```bash
cd /volume1/docker
git clone https://github.com/ТВІ_USERNAME/ytmusic-sync.git
cd ytmusic-sync
```

### 5. Запустити

**Варіант A — Container Manager UI (без SSH):**
1. Container Manager → **Project** → **Create**
2. Name: `ytmusic-sync`, Path: `/volume1/docker/ytmusic-sync`
3. **Build** → **Start**

**Варіант B — SSH:**
```bash
cd /volume1/docker/ytmusic-sync
docker compose up -d
docker compose logs -f
```

---

## Структура після синку

```
/volume1/music/kids/
├── tales/
│   ├── 001 - Казка про лисичку [aB3xYz1234].opus
│   └── 002 - Колобок [cD5eGh6789].opus
├── lullabies/
│   └── 001 - Колискова [iJ7kLm0123].opus
├── playlists/
│   ├── tales.m3u         ← Music Assistant читає це
│   └── lullabies.m3u
└── .sync/
    ├── tales.archive
    └── lullabies.archive
```

---

## Music Assistant

1. MA → Settings → Music providers → `+` → **Local files**
2. Path: `/volume1/music/kids`
3. **Scan**

Плейлісти з'являться в MA → Library → Playlists.

---

## Home Assistant скрипт

```yaml
service: music_assistant.play_media
data:
  entity_id: media_player.ma_home_mini
  media_id: "local://playlist/tales"
  media_type: playlist
  enqueue: replace
  shuffle: true
```

---

## Cookies (приватні плейлісти)

1. Chrome → встанови [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc)
2. Відкрий `music.youtube.com` → увійди в акаунт
3. Розширення → Export → збережи як `cookies.txt`
4. Скопіюй в `/volume1/docker/ytmusic-sync/config/cookies.txt`

Оновлювати раз на ~3 місяці.

---

## Ручний запуск синку

```bash
docker exec ytmusic-sync gosu abc python /app/sync.py
```

---

## Оновлення

```bash
cd /volume1/docker/ytmusic-sync
git pull
docker compose build --no-cache
docker compose up -d
```

---

## Змінні оточення

| Змінна | За замовч. | Опис |
|---|---|---|
| `PUID` | `1000` | User ID власника файлів |
| `PGID` | `1000` | Group ID власника файлів |
| `SYNC_SCHEDULE` | `0 3 * * 0` | Cron розклад |
| `TZ` | `Europe/Kyiv` | Часовий пояс |
| `HA_URL` | — | URL Home Assistant |
| `HA_TOKEN` | — | HA Long-lived token |

---

## Час збірки

| Компонент | Час |
|---|---|
| apt (cron, curl, xz) | ~30с |
| ffmpeg static binary | ~20–40с |
| pip (yt-dlp, mutagen, pyyaml) | ~30с |
| **Разом** | **~2 хв** |

> Попередній варіант компілював ffmpeg через apt — це займало 5–10 хв.
> Тепер використовуються готові бінарники від yt-dlp/FFmpeg-Builds.

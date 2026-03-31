# ytmusic-sync

Синхронізація YouTube Music плейлістів на NAS з автоматичною генерацією `.m3u` для [Music Assistant](https://music-assistant.io).

**Що робить:**
- Завантажує нові треки з плейлістів у форматі `opus` (нативний YT, без re-encode)
- Видаляє треки які прибрали з плейліста
- Генерує `.m3u` файли які MA читає як плейлісти
- Вбудовує обкладинку та метадані в кожен файл
- Запускається автоматично за розкладом (cron всередині контейнера)

**Результат:** старт плейліста в Home Assistant через MA займає ~3–5с замість 16–20с.

---

## Структура на NAS

```
/volume1/music/kids/
├── tales/
│   ├── 001 - Назва казки [abc123].opus
│   └── 002 - Інша казка [def456].opus
├── lullabies/
│   └── 001 - Колискова [xyz789].opus
├── playlists/
│   ├── tales.m3u        ← Music Assistant читає це
│   └── lullabies.m3u
└── .sync/
    ├── tales.archive    ← список вже скачаного
    └── lullabies.archive
```

---

## Встановлення на Synology (рекомендований спосіб)

### Крок 1 — Підготовка папок

Через **File Station** або SSH створи структуру:

```
/volume1/docker/ytmusic-sync/    ← тут будуть конфіги
/volume1/music/kids/             ← тут буде музика
```

### Крок 2 — Завантажити файли проекту

Через SSH (або Terminal у DSM):

```bash
ssh admin@192.168.1.NAS_IP

cd /volume1/docker
git clone https://github.com/ТВІ_USERNAME/ytmusic-sync.git
cd ytmusic-sync
```

Або вручну через File Station — завантажити і розпакувати ZIP з GitHub.

### Крок 3 — Налаштування

```bash
cp config.example.yml config.yml
nano config.yml   # або редагуй через File Station → Text Editor
```

Заповни свої URL плейлістів. Знайти ID плейліста: відкрий плейліст у браузері → URL містить `list=PL...`.

### Крок 4 — Запуск через Container Manager (UI, без SSH)

1. Відкрий **Container Manager** у DSM
2. Вкладка **Project** → **Create**
3. Назва: `ytmusic-sync`
4. Path: `/volume1/docker/ytmusic-sync`
5. **Build** → **Start**

Container Manager сам збере образ і запустить контейнер.

### Крок 4 (альтернатива) — через SSH

```bash
cd /volume1/docker/ytmusic-sync
docker compose up -d

# Переглянути логи першого запуску
docker compose logs -f
```

---

## Налаштування Music Assistant

1. MA → **Settings** → **Music providers** → `+` → **Local files**
2. **Path:** `/volume1/music/kids`
3. Натиснути **Scan**

MA знайде `.m3u` файли в папці `playlists/` і відобразить їх як плейлісти.

---

## Використання в Home Assistant

```yaml
# script.yaml або через UI → Scripts
play_kids_music:
  alias: "▶ Дитяча музика"
  fields:
    playlist:
      selector:
        select:
          options: [tales, lullabies, party]
    mode:
      selector:
        select:
          options: [shuffle, single_random, story]
  sequence:
    - service: music_assistant.play_media
      data:
        entity_id: media_player.ma_home_mini
        media_id: "local://playlist/{{ playlist }}"
        media_type: playlist
        enqueue: replace
        shuffle: "{{ mode == 'shuffle' }}"
```

---

## Cookies (для приватних плейлістів)

1. Встанови [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) в Chrome
2. Відкрий `music.youtube.com`, увійди в акаунт
3. Розширення → **Export cookies** → збережи як `cookies.txt`
4. Скопіюй в `/volume1/docker/ytmusic-sync/cookies.txt`

> Cookies потрібно оновлювати раз на ~3 місяці.

---

## Змінні оточення

| Змінна | За замовч. | Опис |
|---|---|---|
| `SYNC_SCHEDULE` | `0 3 * * 0` | Cron розклад (щонеділі о 03:00) |
| `TZ` | `Europe/Kyiv` | Часовий пояс |
| `HA_URL` | — | URL Home Assistant для event після синку |
| `HA_TOKEN` | — | Long-lived token HA |

---

## Ручний запуск синхронізації

```bash
# Запустити синк зараз не чекаючи cron
docker exec ytmusic-sync python /app/sync.py

# Або через docker compose
docker compose run --rm ytmusic-sync python /app/sync.py
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

## Відлагодження

```bash
# Логи контейнера
docker compose logs -f

# Перевірити cron всередині
docker exec ytmusic-sync crontab -l

# Переглянути що скачано
ls -la /volume1/music/kids/tales/

# Переглянути m3u
cat /volume1/music/kids/playlists/tales.m3u
```

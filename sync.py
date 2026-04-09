#!/usr/bin/env python3
"""
ytmusic-sync — синхронізація YouTube Music плейлістів
з генерацією m3u для Music Assistant
"""

import os
import re
import sys
import yaml
import json
import logging
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import time
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def normalize_pot_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value or "NAS_IP" in value or "ЗАМІНИТИ" in value:
        return ""
    return value


def check_pot_server(url: str, timeout: int = 5) -> bool:
    if not url:
        logger.info("  POT server: не налаштовано")
        return False
    ping = f"{url.rstrip('/')}/ping"
    try:
        with urllib.request.urlopen(ping, timeout=timeout) as r:
            ok = r.status == 200
            logger.info(f"  POT server: {'✅ доступний' if ok else '⚠ недоступний'} ({ping})") if ok else logger.warning(f"  POT server: ⚠ недоступний ({ping})")
            return ok
    except urllib.error.URLError as e:
        logger.warning(f"  POT server: ⚠ недоступний ({ping}) → {e}")
        return False
    except Exception as e:
        logger.exception(f"  POT server: ⚠ неочікувана помилка ({ping})")
        return False


def load_config(path: str = "/app/config.yml") -> dict:
    for candidate in [
        os.environ.get("YTMUSIC_CONFIG", ""),
        path,
        "/config/config.yml",
    ]:
        if candidate and Path(candidate).exists():
            with open(candidate) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("Config not found")


def ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


VIDEOID_RE = re.compile(r'\[([A-Za-z0-9_-]{11})\]\.(opus|m4a|mp3|ogg)$')
VIDEO_URL_ID_RE = re.compile(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})')
MUSICBRAINZ_USER_AGENT = "ytmusic-sync/1.0 (self-hosted)"
MUSICBRAINZ_WS_URL = "https://musicbrainz.org/ws/2/recording/"
_MB_LAST_REQUEST_TS = 0.0
_MB_CACHE: dict[tuple[str, str], dict] = {}


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return False


# ── Playlist IDs ───────────────────────────────────────────────────────────────

def is_single_video_url(url: str) -> bool:
    value = (url or "").strip()
    return "watch?v=" in value or "youtu.be/" in value


def extract_video_id_from_url(url: str) -> str:
    m = VIDEO_URL_ID_RE.search(url or "")
    return m.group(1) if m else ""


def youtube_extractor_args(bgutil_url: str, use_web_music: bool) -> tuple[str, str | None]:
    # mweb is the recommended client when PO tokens are involved, and it is
    # also the safer fallback when POT is disabled.
    youtube_part = (
        "youtube:player_client=web_music;skip=translated_subs,dash;fetch_pot=auto"
        if use_web_music
        else "youtube:player_client=mweb;skip=translated_subs,dash;fetch_pot=never"
    )
    bgutil_part = f"youtubepot-bgutilhttp:base_url={bgutil_url}" if bgutil_url else None
    return youtube_part, bgutil_part


def load_path_map(path_map_file: str) -> dict[str, str]:
    result: dict[str, str] = {}
    p = Path(path_map_file)
    if not p.exists():
        return result
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or "\t" not in line:
            continue
        video_id, file_path = line.split("\t", 1)
        file_path = file_path.strip()
        if file_path and Path(file_path).exists():
            result[video_id.strip()] = file_path
    return result


def strip_opus_language_tag(file_path: str) -> bool:
    path = Path(file_path)
    if path.suffix.lower() != ".opus" or not path.exists():
        return False
    try:
        from mutagen.oggopus import OggOpus
    except Exception as e:
        logger.info(f"  language tag skip: mutagen unavailable ({e})")
        return False

    try:
        audio = OggOpus(str(path))
        if audio.tags and "language" in audio.tags:
            del audio.tags["language"]
            audio.save()
            logger.info(f"  🧹 language tag removed: {path.name}")
            return True
    except Exception as e:
        logger.warning(f"  language tag skip: {path.name} → {e}")
    return False


def ensure_albumartist_tag(file_path: str) -> bool:
    try:
        import mutagen
    except Exception as e:
        logger.info(f"  albumartist skip: mutagen unavailable ({e})")
        return False

    path = Path(file_path)
    if not path.exists():
        return False

    try:
        audio = mutagen.File(str(path), easy=True)
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()

        tags = audio.tags
        if tags.get("albumartist"):
            return False

        artists = tags.get("artist", [])
        if not artists:
            return False

        tags["albumartist"] = list(artists)
        audio.save()
        logger.info(f"  🏷 albumartist fixed: {path.name}")
        return True
    except Exception as e:
        logger.warning(f"  albumartist skip: {path.name} → {e}")
        return False


def _normalize_mb_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _musicbrainz_lookup(artist: str, title: str, min_interval_sec: float = 1.1) -> dict:
    global _MB_LAST_REQUEST_TS

    key = (_normalize_mb_text(artist), _normalize_mb_text(title))
    cached = _MB_CACHE.get(key)
    if cached is not None:
        return cached

    now = time.monotonic()
    elapsed = now - _MB_LAST_REQUEST_TS
    if elapsed < min_interval_sec:
        time.sleep(min_interval_sec - elapsed)

    query = f'recording:"{title}" AND artist:"{artist}"'
    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
    req = urllib.request.Request(
        f"{MUSICBRAINZ_WS_URL}?{params}",
        headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
            _MB_LAST_REQUEST_TS = time.monotonic()

        recordings = data.get("recordings") or []
        if not recordings:
            _MB_CACHE[key] = {}
            return {}

        recordings = sorted(recordings, key=lambda x: int(x.get("score") or 0), reverse=True)
        best = recordings[0]
        if int(best.get("score") or 0) < 85:
            _MB_CACHE[key] = {}
            return {}
        _MB_CACHE[key] = best
        return best
    except urllib.error.HTTPError as e:
        logger.warning(f"  MusicBrainz HTTP skip: {e}")
    except urllib.error.URLError as e:
        logger.warning(f"  MusicBrainz network skip: {e}")
    except Exception as e:
        logger.warning(f"  MusicBrainz unexpected skip: {e}")

    _MB_CACHE[key] = {}
    return {}


def enrich_tags_from_musicbrainz(file_path: str, min_interval_sec: float = 1.1) -> bool:
    try:
        import mutagen
    except Exception as e:
        logger.info(f"  MusicBrainz skip: mutagen unavailable ({e})")
        return False

    path = Path(file_path)
    if not path.exists():
        return False

    try:
        audio = mutagen.File(str(path), easy=True)
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()

        tags = audio.tags
        if tags.get("musicbrainz_recordingid"):
            return False

        artist = (tags.get("artist", [""]) or [""])[0].strip()
        title = (tags.get("title", [""]) or [""])[0].strip()
        if not artist or not title:
            return False

        rec = _musicbrainz_lookup(artist, title, min_interval_sec=min_interval_sec)
        if not rec or not rec.get("id"):
            return False

        changed = False
        if not tags.get("musicbrainz_recordingid"):
            tags["musicbrainz_recordingid"] = [rec["id"]]
            changed = True

        artists = rec.get("artist-credit") or []
        artist_ids = [a.get("artist", {}).get("id") for a in artists if a.get("artist", {}).get("id")]
        if artist_ids and not tags.get("musicbrainz_artistid"):
            tags["musicbrainz_artistid"] = artist_ids
            changed = True

        releases = rec.get("releases") or []
        if releases:
            rel = releases[0]
            if rel.get("id") and not tags.get("musicbrainz_albumid"):
                tags["musicbrainz_albumid"] = [rel["id"]]
                changed = True
            if rel.get("title") and not tags.get("album"):
                tags["album"] = [rel["title"]]
                changed = True
            if rel.get("date") and not tags.get("date"):
                tags["date"] = [rel["date"]]
                changed = True

        if changed:
            audio.save()
            logger.info(f"  🧠 MusicBrainz enriched: {path.name}")
        return changed
    except Exception as e:
        logger.warning(f"  MusicBrainz skip: {path.name} → {e}")
        return False

def get_playlist_ids(url: str, cookies_file: str | None,
                     bgutil_url: str) -> list[str]:
    if is_single_video_url(url):
        vid = extract_video_id_from_url(url)
        if vid:
            logger.info("  Single video URL detected")
            return [vid]

    youtube_extractor_args_value, bgutil_extractor_args_value = youtube_extractor_args(
        bgutil_url, use_web_music=bool(bgutil_url))
    cmd = ["yt-dlp", "--print", "%(id)s", "--no-warnings",
           "--js-runtimes", "deno", "--remote-components", "ejs:github",
           "--extractor-args", youtube_extractor_args_value]
    if bgutil_extractor_args_value:
        cmd += ["--extractor-args", bgutil_extractor_args_value]
    if not is_single_video_url(url):
        cmd.insert(1, "--flat-playlist")
    cmd += [url]
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Не вдалося отримати список треків: {result.stderr.strip() or result.stdout.strip()}")
    ids = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    logger.info(f"  Треків у плейлісті: {len(ids)}")
    return ids


# ── Disk scan ──────────────────────────────────────────────────────────────────

def scan_files(output_dir: str) -> dict[str, str]:
    """Повертає {video_id: абсолютний шлях} за файлами на диску"""
    result = {}
    p = Path(output_dir)
    if not p.exists():
        return result
    for f in p.iterdir():
        if f.is_file():
            m = VIDEOID_RE.search(f.name)
            if m:
                result[m.group(1)] = str(f)
    return result


# ── Archive validation ─────────────────────────────────────────────────────────

def clean_orphaned_archive(archive_path: str, on_disk: dict[str, str]):
    """
    Видалити з .ytdlp.archive записи де файл не існує на диску.
    Це дозволяє yt-dlp перескачати 'загублені' треки.
    """
    p = Path(archive_path)
    if not p.exists():
        return 0

    lines = p.read_text().splitlines()
    cleaned = []
    removed = 0

    for line in lines:
        # yt-dlp формат: "youtube VIDEOID"
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            vid_id = parts[1].strip()
            if vid_id in on_disk:
                cleaned.append(line)
            else:
                removed += 1
                logger.info(f"  🔧 Archive orphan removed: {vid_id}")
        else:
            cleaned.append(line)

    if removed:
        p.write_text("\n".join(cleaned) + ("\n" if cleaned else ""))
        logger.info(f"  Archive: видалено {removed} orphan записів → буде перескачано")

    return removed


# ── Delete removed ─────────────────────────────────────────────────────────────

def delete_removed(current_ids: list[str], on_disk: dict[str, str]) -> int:
    current_set = set(current_ids)
    deleted = 0
    for vid, fp in list(on_disk.items()):
        if vid not in current_set:
            logger.info(f"  🗑  Видаляю: {Path(fp).name}")
            Path(fp).unlink(missing_ok=True)
            for ext in (".jpg", ".png", ".webp"):
                Path(fp).with_suffix(ext).unlink(missing_ok=True)
            deleted += 1
    return deleted


# ── Download ───────────────────────────────────────────────────────────────────

def download_playlist(cfg: dict, settings: dict) -> tuple[dict, list[str]]:
    name        = cfg["name"]
    url         = cfg["url"]
    output_dir  = cfg["output_dir"]
    fmt         = cfg.get("format", "opus")
    cookies     = settings.get("cookies_file")
    archive_dir = settings["archive_dir"]
    sleep       = settings.get("sleep_interval", 2)
    bgutil_url  = normalize_pot_url(str(settings.get("pot_server_url") or ""))
    mb_enabled  = as_bool(settings.get("musicbrainz_enrich", False))
    mb_min_interval = float(settings.get("musicbrainz_min_interval_sec", 1.1))
    path_map_file = str(Path(archive_dir) / f"{name}.paths.tsv")

    ytdlp_archive = str(Path(archive_dir) / f"{name}.ytdlp.archive")
    if is_single_video_url(url):
        out_template = str(
            Path(output_dir) /
            "%(artist,creator,uploader)s - %(title)s.%(ext)s"
        )
    else:
        out_template = str(
            Path(output_dir) /
            "%(playlist_index)03d - %(artist,creator,uploader)s - %(title)s.%(ext)s"
        )

    ensure_dirs(output_dir)

    logger.info(f"  Отримую список...")
    current_ids = get_playlist_ids(url, cookies, bgutil_url)

    # Стан диску до скачування
    on_disk = load_path_map(path_map_file)

    # ВИПРАВЛЕННЯ: видалити orphan-записи з архіву
    # (треки в архіві, але файл не існує → yt-dlp перескачає)
    clean_orphaned_archive(ytdlp_archive, on_disk)

    deleted = delete_removed(current_ids, on_disk)
    if deleted:
        logger.info(f"  Видалено {deleted} старих треків")

    has_cookies = bool(cookies and Path(cookies).exists())
    single_video = is_single_video_url(url)
    youtube_extractor_args_value, bgutil_extractor_args_value = youtube_extractor_args(
        bgutil_url, use_web_music=bool(bgutil_url))

    metadata_args = [
        "--parse-metadata", "%(artist,creator,uploader)s:%(albumartist)s",
        "--parse-metadata", "artist:^(?P<first_artist>[^,]+)",
        "--parse-metadata", "%(release_year,upload_date>%Y)s:%(meta_date)s",
        "--parse-metadata", "%(upload_date)s:%(meta_upload_date)s",
        "--parse-metadata", "%(album,release_title,playlist_title)s:%(album)s",
    ]
    if not single_video:
        metadata_args += [
            "--parse-metadata", "%(playlist_index)s:%(track_number)s",
        ]

    cmd = [
        "yt-dlp",
        # JS runtime
        "--js-runtimes", "deno",
        "--remote-components", "ejs:github",
        "--quiet",
        "--no-warnings",
        "--no-progress",
        "--extract-audio",
        "--format", "bestaudio[acodec^=opus]/bestaudio/best",
        "--audio-format", fmt,
        "--audio-quality", "0",
        # Метадані
        "--embed-metadata",
        "--ppa", "EmbedMetadata: -metadata:s:a:0 language=",
        "--ppa", "FFmpegExtractAudio: -metadata:s:a:0 language=",
        # Обкладинка
        "--convert-thumbnails", "png",
        "--embed-thumbnail",
        "--ppa", "ThumbnailsConvertor:-vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"",
    ]

    cmd += [
        *metadata_args,
        "--windows-filenames",
        "--output", out_template,
        "--download-archive", ytdlp_archive,
        "--no-video",
        "--extractor-args", youtube_extractor_args_value,
        "--exec", f"after_move:sh -c 'printf \"%s\\t%s\\n\" \"$1\" \"$2\" >> \"$3\"' sh \"%(id)s\" \"%(filepath)s\" \"{path_map_file}\"",
        "--sleep-interval",     str(sleep),
        "--max-sleep-interval", str(sleep * 3),
        "--concurrent-fragments", "1",
        url,
    ]
    
    cmd[cmd.index("--windows-filenames") : cmd.index("--windows-filenames")] = [
        "--ignore-no-formats-error",
        "--no-abort-on-error",
        "--ignore-errors",
    ]

    if bgutil_extractor_args_value:
        cmd[cmd.index("--sleep-interval") : cmd.index("--sleep-interval")] = [
            "--extractor-args", bgutil_extractor_args_value,
        ]

    if has_cookies:
        cmd += ["--cookies", cookies]
    else:
        logger.info(f"  Cookies: не використовуються")

    if bgutil_url:
        logger.info(f"  PO Token: {bgutil_url}")
    else:
        logger.info("  POT disabled: using youtube fallback clients")

    logger.info(f"  Скачую нові треки...")
    result = subprocess.run(cmd)
    if result.returncode not in (0, 1):
        logger.warning(f"  ⚠  yt-dlp код: {result.returncode}")

    on_disk_after = load_path_map(path_map_file)
    fixed_albumartist = 0
    enriched_count = 0
    for file_path in on_disk_after.values():
        strip_opus_language_tag(file_path)
        if ensure_albumartist_tag(file_path):
            fixed_albumartist += 1
        if mb_enabled and enrich_tags_from_musicbrainz(file_path, min_interval_sec=mb_min_interval):
            enriched_count += 1

    if fixed_albumartist:
        logger.info(f"  ✅ albumartist виправлено: {fixed_albumartist}")
    if mb_enabled:
        logger.info(f"  ✅ MusicBrainz enrich: {enriched_count}")

    new_count = len(on_disk_after) - len(on_disk) + deleted
    if new_count > 0:
        logger.info(f"  ✅ Нових треків: {new_count}")

    return on_disk_after, current_ids


# ── m3u ────────────────────────────────────────────────────────────────────────

def generate_m3u(name: str, current_ids: list[str],
                 on_disk: dict[str, str], playlists_dir: str) -> str:
    m3u_path = Path(playlists_dir) / f"{name}.m3u"
    lines = ["#EXTM3U\n"]
    found = missing = 0

    for vid in current_ids:
        fp = on_disk.get(vid)
        if fp and Path(fp).exists():
            rel   = os.path.relpath(fp, playlists_dir)
            # Прибрати ведучий номер і розширення файлу для чистої назви в M3U.
            title = Path(fp).stem
            title = re.sub(r'^\d{3}\s*-\s*', '', title)
            lines += [f"#EXTINF:-1,{title}\n", f"{rel}\n"]
            found += 1
        else:
            missing += 1

    m3u_path.write_text("".join(lines), encoding="utf-8")
    if missing:
        logger.info(f"  📋 {m3u_path.name}: {found} треків, {missing} не знайдено")
    else:
        logger.info(f"  📋 {m3u_path.name}: {found} треків ✅")
    return str(m3u_path)


# ── HA event ───────────────────────────────────────────────────────────────────

def trigger_ha_event():
    ha_url   = os.environ.get("HA_URL", "").rstrip("/")
    ha_token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        return
    try:
        req = urllib.request.Request(
            f"{ha_url}/api/events/ytmusic_sync_done",
            data=json.dumps({"status": "ok"}).encode(),
            headers={"Authorization": f"Bearer {ha_token}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("✅ HA event надіслано")
    except urllib.error.URLError as e:
        logger.warning(f"  HA event network skip: {e}")
    except Exception as e:
        logger.exception(f"  HA event failed unexpectedly")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    sep = "═" * 50
    logger.info(sep)
    logger.info("ytmusic-sync старт")
    logger.info(sep)

    cfg      = load_config()
    settings = cfg.get("settings", {})
    ensure_dirs(settings["playlists_dir"], settings["archive_dir"])

    pot_url = normalize_pot_url(str(settings.get("pot_server_url") or ""))
    check_pot_server(pot_url)

    errors = []
    for playlist in cfg.get("playlists", []):
        logger.info(f"\n▶  {playlist['name']}")
        try:
            on_disk, ids = download_playlist(playlist, settings)
            generate_m3u(playlist["name"], ids, on_disk,
                         settings["playlists_dir"])
        except Exception as e:
            logger.exception(f"  ПОМИЛКА обробки плейліста {playlist['name']}: {e}")
            errors.append(playlist["name"])

    trigger_ha_event()

    logger.info(f"\n{sep}")
    if errors:
        logger.info(f"Завершено з помилками: {', '.join(errors)}")
        sys.exit(1)
    else:
        logger.info("Синхронізація успішно завершена")


if __name__ == "__main__":
    main()

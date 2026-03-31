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
import subprocess
from pathlib import Path
from datetime import datetime


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_config(path: str = "/app/config.yml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


# ── Playlist IDs ───────────────────────────────────────────────────────────────

def get_playlist_ids(url: str, cookies_file: str | None = None,
                     bgutil_url: str = "") -> list[str]:
    """Отримати поточний список video ID без скачування"""
    cmd = [
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--no-warnings",
        "--js-runtimes", "nodejs",
        url,
    ]
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]
    if bgutil_url:
        cmd += ["--extractor-args",
                f"youtubepot-bgutilhttp:base_url={bgutil_url}"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    ids = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    log(f"  Треків у плейлісті: {len(ids)}")
    return ids


# ── File ↔ ID mapping ─────────────────────────────────────────────────────────

VIDEOID_RE = re.compile(r'\[([A-Za-z0-9_-]{11})\]\.(opus|m4a|mp3|ogg)$')


def scan_files(output_dir: str) -> dict[str, str]:
    """Повертає {video_id: абсолютний шлях} за файлами на диску"""
    result = {}
    for f in Path(output_dir).iterdir():
        if f.is_file():
            m = VIDEOID_RE.search(f.name)
            if m:
                result[m.group(1)] = str(f)
    return result


# ── Delete removed ─────────────────────────────────────────────────────────────

def delete_removed(current_ids: list[str], on_disk: dict[str, str]) -> int:
    current_set = set(current_ids)
    deleted = 0
    for vid, fp in list(on_disk.items()):
        if vid not in current_set:
            log(f"  🗑  Видаляю: {Path(fp).name}")
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
    bgutil_url  = (settings.get("pot_server_url") or
                   os.environ.get("POT_SERVER_URL", "")).strip()

    # Окремий архів для yt-dlp (формат "youtube VIDEOID")
    ytdlp_archive = str(Path(archive_dir) / f"{name}.ytdlp.archive")
    out_template  = str(Path(output_dir) /
                        "%(playlist_index)03d - %(title)s [%(id)s].%(ext)s")

    ensure_dirs(output_dir)

    log(f"  Отримую список...")
    current_ids = get_playlist_ids(url, cookies, bgutil_url)

    on_disk = scan_files(output_dir)
    deleted = delete_removed(current_ids, on_disk)
    if deleted:
        log(f"  Видалено {deleted} старих треків")

    # ── Cookies ───────────────────────────────────────────────────────────────
    # Обов'язкові лише для приватних плейлістів.
    # З bgutil PO token публічні плейлісти скачуються без cookies.
    has_cookies = bool(cookies and Path(cookies).exists())

    cmd = [
        "yt-dlp",
        # JS runtime — обов'язково починаючи з yt-dlp 2025.x
        "--js-runtimes", "nodejs",
        "--extract-audio",
        # Формат: bestaudio (opus на YT) з fallback на будь-який аудіо
        "--format", "bestaudio/best",
        "--audio-format", fmt,
        "--audio-quality", "0",
        # Обкладинка
        "--embed-thumbnail",
        "--convert-thumbnails", "jpg",
        # Метадані
        "--embed-metadata",
        # ── Теги для Music Assistant ──────────────────────────────────────────
        "--parse-metadata", "%(playlist_title)s:%(album)s",
        "--parse-metadata", "%(playlist_index)s:%(track_number)s",
        "--parse-metadata", "%(artist,creator,uploader)s:%(artist)s",
        # ALBUMARTIST — критично, без нього всі треки у "Various Artists"
        "--parse-metadata", "%(artist,creator,uploader)s:%(albumartist)s",
        # Очистити DATE — дата завантаження != рік випуску
        "--parse-metadata", ":(?P<meta_date>)",
        # Безпечні імена для SMB шар на Synology
        "--windows-filenames",
        # ── Архів і вихід ────────────────────────────────────────────────────
        "--output", out_template,
        "--download-archive", ytdlp_archive,
        "--no-video",
        # Пропустити недоступні відео (видалені/гео-блок), НЕ зупиняти весь синк
        "--ignore-no-formats-error",
        "--no-abort-on-error",
        # Ігнорувати недоступні треки (але логувати)
        "--ignore-errors",
        "--sleep-interval",     str(sleep),
        "--max-sleep-interval", str(sleep * 3),
        "--concurrent-fragments", "1",
        "--newline",
        url,
    ]

    if has_cookies:
        cmd += ["--cookies", cookies]
        log(f"  Cookies: {cookies}")
    else:
        log(f"  Cookies: не використовуються (тільки для приватних плейлістів)")

    # ── PO Token ──────────────────────────────────────────────────────────────
    if bgutil_url:
        cmd += ["--extractor-args",
                f"youtubepot-bgutilhttp:base_url={bgutil_url}"]
        log(f"  PO Token: {bgutil_url}")
    else:
        log(f"  ⚠  POT_SERVER_URL не вказано — можливі помилки завантаження")

    log(f"  Скачую нові треки...")
    result = subprocess.run(cmd)

    if result.returncode not in (0, 1):
        log(f"  ⚠  yt-dlp завершився з кодом {result.returncode}")

    on_disk_after = scan_files(output_dir)
    new_count = len(on_disk_after) - len(on_disk) + deleted
    if new_count > 0:
        log(f"  ✅ Скачано нових треків: {new_count}")

    return on_disk_after, current_ids


# ── m3u generation ─────────────────────────────────────────────────────────────

def generate_m3u(name: str, current_ids: list[str],
                 on_disk: dict[str, str], playlists_dir: str) -> str:
    m3u_path = Path(playlists_dir) / f"{name}.m3u"
    lines = ["#EXTM3U\n"]
    found = missing = 0

    for vid in current_ids:
        fp = on_disk.get(vid)
        if fp and Path(fp).exists():
            rel   = os.path.relpath(fp, playlists_dir)
            title = re.sub(r'\s*\[[A-Za-z0-9_-]{11}\]$', '', Path(fp).stem)
            title = re.sub(r'^\d{3}\s*-\s*', '', title)
            lines += [f"#EXTINF:-1,{title}\n", f"{rel}\n"]
            found += 1
        else:
            missing += 1

    m3u_path.write_text("".join(lines), encoding="utf-8")
    if missing:
        log(f"  📋 {m3u_path.name}: {found} треків, {missing} недоступних (видалені/гео-блок)")
    else:
        log(f"  📋 {m3u_path.name}: {found} треків ✅")
    return str(m3u_path)


# ── HA event ───────────────────────────────────────────────────────────────────

def trigger_ha_event():
    ha_url   = os.environ.get("HA_URL", "").rstrip("/")
    ha_token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        return
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{ha_url}/api/events/ytmusic_sync_done",
            data=json.dumps({"status": "ok"}).encode(),
            headers={"Authorization": f"Bearer {ha_token}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log("✅ HA event надіслано")
    except Exception as e:
        log(f"  HA event skip: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    sep = "═" * 50
    log(sep)
    log("ytmusic-sync старт")
    log(sep)

    cfg      = load_config()
    settings = cfg.get("settings", {})
    ensure_dirs(settings["playlists_dir"], settings["archive_dir"])

    errors = []
    for playlist in cfg.get("playlists", []):
        log(f"\n▶  {playlist['name']}")
        try:
            on_disk, ids = download_playlist(playlist, settings)
            generate_m3u(playlist["name"], ids, on_disk,
                         settings["playlists_dir"])
        except Exception as e:
            log(f"  ПОМИЛКА: {e}")
            errors.append(playlist["name"])

    trigger_ha_event()

    log(f"\n{sep}")
    if errors:
        log(f"Завершено з помилками: {', '.join(errors)}")
        sys.exit(1)
    else:
        log("Синхронізація успішно завершена")


if __name__ == "__main__":
    main()

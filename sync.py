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


# ── Playlist info ──────────────────────────────────────────────────────────────

def get_playlist_ids(url: str, cookies_file: str | None = None) -> list[str]:
    """Отримати поточний список video ID без скачування"""
    cmd = [
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--no-warnings", url
    ]
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]

    result = subprocess.run(cmd, capture_output=True, text=True)
    ids = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    log(f"  Треків у плейлісті: {len(ids)}")
    return ids


# ── Archive ────────────────────────────────────────────────────────────────────

def load_archive(path: str) -> dict[str, str]:
    """Повертає {video_id: абсолютний шлях до файлу}"""
    archive = {}
    if not Path(path).exists():
        return archive
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                archive[parts[0]] = parts[1]
    return archive


def save_archive(path: str, archive: dict):
    with open(path, "w") as f:
        for vid_id, filepath in archive.items():
            f.write(f"{vid_id}\t{filepath}\n")


def rebuild_archive(output_dir: str, archive_path: str) -> dict[str, str]:
    """Відновити archive зі скачаних файлів по [videoID] в імені"""
    archive = {}
    pattern = re.compile(r'\[([A-Za-z0-9_-]{11})\]\.(opus|m4a|mp3|ogg)$')
    for f in Path(output_dir).iterdir():
        if f.is_file():
            m = pattern.search(f.name)
            if m:
                archive[m.group(1)] = str(f)
    save_archive(archive_path, archive)
    return archive


# ── Delete removed ─────────────────────────────────────────────────────────────

def delete_removed(current_ids: list, archive: dict, output_dir: str) -> int:
    """Видалити файли треків яких більше немає в плейлісті"""
    current_set = set(current_ids)
    to_delete = [vid for vid in list(archive) if vid not in current_set]
    deleted = 0
    for vid in to_delete:
        fp = archive.pop(vid, None)
        if fp and Path(fp).exists():
            log(f"  🗑  Видаляю: {Path(fp).name}")
            Path(fp).unlink(missing_ok=True)
            for ext in (".jpg", ".png", ".webp"):
                Path(fp).with_suffix(ext).unlink(missing_ok=True)
            deleted += 1
    return deleted


# ── Download ───────────────────────────────────────────────────────────────────

def download_playlist(cfg: dict, settings: dict) -> tuple[dict, list]:
    name        = cfg["name"]
    url         = cfg["url"]
    output_dir  = cfg["output_dir"]
    fmt         = cfg.get("format", "opus")
    cookies     = settings.get("cookies_file")
    archive_dir = settings["archive_dir"]
    sleep       = settings.get("sleep_interval", 2)

    archive_path = str(Path(archive_dir) / f"{name}.archive")
    out_template = str(Path(output_dir) /
                       "%(playlist_index)03d - %(title)s [%(id)s].%(ext)s")

    ensure_dirs(output_dir)

    log(f"  Отримую список...")
    current_ids = get_playlist_ids(url, cookies)

    archive = load_archive(archive_path)
    deleted = delete_removed(current_ids, archive, output_dir)
    if deleted:
        log(f"  Видалено {deleted} старих треків")
        save_archive(archive_path, archive)

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", fmt,
        "--audio-quality", "0",
        "--embed-thumbnail",
        "--embed-metadata",
        "--add-metadata",
        "--convert-thumbnails", "jpg",
        "--parse-metadata", "%(playlist_title)s:%(album)s",
        "--parse-metadata", "%(playlist_index)s:%(track_number)s",
        "--parse-metadata", "%(artist,uploader)s:%(artist)s",
        "--output", out_template,
        "--download-archive", archive_path,
        "--no-video",
        "--ignore-errors",
        "--sleep-interval",     str(sleep),
        "--max-sleep-interval", str(sleep * 3),
        "--concurrent-fragments", "1",
        "--newline",
        url,
    ]
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]

    log(f"  Скачую нові треки...")
    subprocess.run(cmd)

    # yt-dlp пише архів у форматі "youtube VIDEOID" — нам потрібен filepath
    archive = rebuild_archive(output_dir, archive_path)
    return archive, current_ids


# ── m3u generation ─────────────────────────────────────────────────────────────

def generate_m3u(name: str, current_ids: list, archive: dict,
                 playlists_dir: str) -> str:
    m3u_path = Path(playlists_dir) / f"{name}.m3u"
    lines = ["#EXTM3U\n"]
    found = missing = 0

    for vid in current_ids:
        fp = archive.get(vid)
        if fp and Path(fp).exists():
            rel = os.path.relpath(fp, playlists_dir)
            title = re.sub(r'\s*\[[A-Za-z0-9_-]{11}\]$', '', Path(fp).stem)
            title = re.sub(r'^\d{3}\s*-\s*', '', title)
            lines += [f"#EXTINF:-1,{title}\n", f"{rel}\n"]
            found += 1
        else:
            missing += 1

    m3u_path.write_text("".join(lines), encoding="utf-8")
    log(f"  📋 {m3u_path.name}: {found} треків"
        + (f", {missing} відсутніх" if missing else ""))
    return str(m3u_path)


# ── MA rescan ──────────────────────────────────────────────────────────────────

def trigger_ma_rescan():
    ha_url   = os.environ.get("HA_URL", "").rstrip("/")
    ha_token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        return

    import urllib.request
    try:
        req = urllib.request.Request(
            f"{ha_url}/api/events/ytmusic_sync_done",
            data=json.dumps({"status": "ok"}).encode(),
            headers={
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log("✅ HA event надіслано → можна тригерити MA rescan")
    except Exception as e:
        log(f"  HA event skip: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log("═" * 50)
    log("ytmusic-sync старт")
    log("═" * 50)

    cfg      = load_config()
    settings = cfg.get("settings", {})
    ensure_dirs(settings["playlists_dir"], settings["archive_dir"])

    errors = []
    for playlist in cfg.get("playlists", []):
        log(f"\n▶  {playlist['name']}")
        try:
            archive, ids = download_playlist(playlist, settings)
            generate_m3u(
                playlist["name"], ids, archive,
                settings["playlists_dir"],
            )
        except Exception as e:
            log(f"  ПОМИЛКА: {e}")
            errors.append(playlist["name"])

    trigger_ma_rescan()

    log("\n═" * 50)
    if errors:
        log(f"Завершено з помилками: {', '.join(errors)}")
        sys.exit(1)
    else:
        log("Синхронізація успішно завершена")


if __name__ == "__main__":
    main()

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
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def normalize_pot_url(raw: str) -> str:
    """Return empty string for placeholder/invalid PO token URLs from examples."""
    value = (raw or "").strip()
    if not value:
        return ""
    if "NAS_IP" in value or "ЗАМІНИТИ" in value:
        return ""
    return value


def get_pot_ping_url(url: str) -> str:
    return f"{url.rstrip('/')}/ping"


def check_pot_server(url: str, timeout: int = 5) -> bool:
    if not url:
        log("POT server: not configured")
        return False

    ping_url = get_pot_ping_url(url)
    req = urllib.request.Request(ping_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                log(f"POT server: reachable ({ping_url}), status=200")
                return True
            log(f"POT server: unexpected status ({ping_url}), status={response.status}")
            return False
    except urllib.error.HTTPError as e:
        log(f"POT server: unreachable ({ping_url}), status={e.code}")
        return False
    except Exception as e:
        log(f"POT server: unreachable ({ping_url}) -> {e}")
        return False


def load_config(path: str = "/app/config.yml") -> dict:
    config_env = os.environ.get("YTMUSIC_CONFIG", "").strip()
    candidates = []
    if config_env:
        candidates.append(config_env)
    if path:
        candidates.append(path)
    candidates.append("/config/config.yml")

    for candidate in candidates:
        if Path(candidate).exists():
            with open(candidate) as f:
                return yaml.safe_load(f)

    raise FileNotFoundError(
        "Config file not found. Checked: " + ", ".join(candidates)
    )


def ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def get_playlist_ids(url: str, cookies_file: str | None = None,
                     bgutil_url: str = "") -> list[str]:
    """Отримати поточний список video ID без скачування"""
    cmd = [
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--no-warnings",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
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


def download_playlist(cfg: dict, settings: dict) -> tuple[dict, list[str]]:
    name        = cfg["name"]
    url         = cfg["url"]
    output_dir  = cfg["output_dir"]
    fmt         = cfg.get("format", "opus")
    cookies     = settings.get("cookies_file")
    archive_dir = settings["archive_dir"]
    sleep       = settings.get("sleep_interval", 2)
    bgutil_url  = normalize_pot_url(settings.get("pot_server_url") or
                                    os.environ.get("POT_SERVER_URL", ""))

    ytdlp_archive = str(Path(archive_dir) / f"{name}.ytdlp.archive")
    out_template  = str(Path(output_dir) /
                        "%(playlist_index)03d - %(first_artist)s - %(title)s [%(id)s].%(ext)s")

    ensure_dirs(output_dir)

    log(f"  Отримую список...")
    current_ids = get_playlist_ids(url, cookies, bgutil_url)

    on_disk = scan_files(output_dir)
    deleted = delete_removed(current_ids, on_disk)
    if deleted:
        log(f"  Видалено {deleted} старих треків")

    # Cookies are needed only for private playlists.
    has_cookies = bool(cookies and Path(cookies).exists())

    cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--extract-audio",
        "--format", "bestaudio[acodec^=opus]/bestaudio/best",
        "--audio-format", fmt,
        "--audio-quality", "0",
        "--embed-thumbnail",
        "--convert-thumbnails", "png",
        "--ppa", "ffmpeg: -vf scale=500:500:force_original_aspect_ratio=decrease,pad=500:500:(ow-iw)/2:(oh-ih)/2",
        "--embed-metadata",
        "--parse-metadata", "%(playlist_title)s:%(album)s",
        "--parse-metadata", "%(playlist_index)s:%(track_number)s",
        "--parse-metadata", "%(artist,creator,uploader)s:%(albumartist)s",
        "--parse-metadata", "artist:^(?P<first_artist>[^,]+)",
        "--parse-metadata", "%(release_year,upload_date>%Y)s:%(meta_date)s",
        "--parse-metadata", "%(upload_date)s:%(meta_upload_date)s",
        "--windows-filenames",
        "--output", out_template,
        "--download-archive", ytdlp_archive,
        "--no-video",
        "--ignore-no-formats-error",
        "--no-abort-on-error",
        "--ignore-errors",
        "--extractor-args", "youtube:player_client=web_mobile",
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

    if bgutil_url:
        cmd += ["--extractor-args",
                f"youtubepot-bgutilhttp:base_url={bgutil_url}"]
        log(f"  PO Token: {bgutil_url}")
    else:
        log(f"  POT_SERVER_URL: не задано")

    log(f"  Скачую нові треки...")
    result = subprocess.run(cmd)

    if result.returncode not in (0, 1):
        log(f"  ⚠  yt-dlp завершився з кодом {result.returncode}")

    on_disk_after = scan_files(output_dir)
    new_count = len(on_disk_after) - len(on_disk) + deleted
    if new_count > 0:
        log(f"  ✅ Скачано нових треків: {new_count}")

    return on_disk_after, current_ids


def generate_m3u(name: str, current_ids: list[str],
                 on_disk: dict[str, str], playlists_dir: str) -> str:
    m3u_path = Path(playlists_dir) / f"{name}.m3u"
    lines = ["#EXTM3U\n"]
    found = missing = 0

    for vid in current_ids:
        fp = on_disk.get(vid)
        if fp and Path(fp).exists():
            rel   = os.path.relpath(fp, playlists_dir)
            title = re.sub(r'\s*\[[A-Za-z0-9_-]{11}\]\.[a-z0-9]+$', '', Path(fp).name)
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


def main():
    sep = "═" * 50
    log(sep)
    log("ytmusic-sync старт")
    log(sep)

    cfg      = load_config()
    settings = cfg.get("settings", {})
    ensure_dirs(settings["playlists_dir"], settings["archive_dir"])
    check_pot_server(normalize_pot_url(
        settings.get("pot_server_url") or os.environ.get("POT_SERVER_URL", "")
    ))

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

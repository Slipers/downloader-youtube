"""Persisted app settings (theme, last download folder, ffmpeg location)."""
import json
from pathlib import Path

APP_DIR = Path.home() / "AppData" / "Local" / "DownloaderYoutubeer"
SETTINGS_FILE = APP_DIR / "settings.json"
FFMPEG_DIR = APP_DIR / "ffmpeg"

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YouTube"

DEFAULTS = {
    "theme": None,  # None => follow OS preference on first run
    "last_download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "ffmpeg_location": None,
    "show_preview": True,
    "last_quality": "1080p",
    "last_fps": "auto",
    "last_export_type": "video_audio",
    "last_output_format": None,
    "confetti_seconds": 5,
    "cookies_file": None,
    "tutorial_seen": False,
}


def _ensure_app_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    _ensure_app_dir()
    if not SETTINGS_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    _ensure_app_dir()
    current = load_settings()
    current.update(settings)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")

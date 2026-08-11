"""Persisted app settings (theme, last download folder, ffmpeg location)."""
import json
import sys
from pathlib import Path

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

APP_DIR = Path.home() / "AppData" / "Local" / "DownloaderYoutubeer"
SETTINGS_FILE = APP_DIR / "settings.json"
FFMPEG_DIR = APP_DIR / "ffmpeg"

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YouTube"

# ---- browser extension ------------------------------------------------
EXTENSION_ID = "fclpcgadpekfhgmjimnekigfhkejhdmk"
LINK_SERVER_PORT = 47990
EXTENSION_SRC_DIR = BASE_DIR / "extension"
EXTENSION_INSTALL_DIR = APP_DIR / "extension"

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
    "paired": False,
    "pairing_token": None,
    "total_downloads": 0,
    "last_seen_version": None,
    "sfx_enabled": True,
    "always_confirm_video": True,
    "last_rating_at": None,
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

"""Sends the mandatory post-update rating/feedback to a Discord webhook."""
import json
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

from . import updater

# Kept out of the (public) repository: backend/keys is never synced to
# GitHub, and the file is bundled into the build next to the other keys.
_WEBHOOK_FILE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "keys" / "feedback_webhook.txt"


def _webhook_url() -> str | None:
    try:
        return _WEBHOOK_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _stars_display(stars: float) -> str:
    full = int(stars)
    has_half = (stars - full) >= 0.5
    line = "⭐" * full + ("✨" if has_half else "")
    return f"{line}  —  {stars}/5"


def send_rating(stars: float, comment: str) -> bool:
    embed = {
        "title": "⭐ Nouvel avis reçu",
        "color": 0xFF3366,
        "fields": [
            {"name": "Note", "value": _stars_display(stars), "inline": True},
            {"name": "Version", "value": f"v{updater.APP_VERSION}", "inline": True},
        ],
        "description": comment,
        "footer": {"text": "Downloader Youtube — avis utilisateur"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    url = _webhook_url()
    if not url:
        return False
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "DownloaderYoutube-Feedback"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

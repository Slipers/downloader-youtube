"""Sends the mandatory post-update rating/feedback to a Discord webhook."""
import json
import urllib.request
from datetime import datetime, timezone

from . import updater

WEBHOOK_URL = "https://discord.com/api/webhooks/1536814364982509679/cydh55JRD-M59ACJTqskAEtVhzcfIJHgIZdbl7Vl1wP8dcbq6halas8343eWajIu5uVS"


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
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "DownloaderYoutube-Feedback"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

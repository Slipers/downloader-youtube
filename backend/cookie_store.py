"""Stores the YouTube cookies the browser extension pushes over the link server.

Why this exists: YouTube increasingly asks apps to "sign in to confirm you're
not a robot" for some videos. yt-dlp can normally read cookies straight out of
an installed browser, but Chrome/Edge 127+ encrypt their cookie database with
App-Bound Encryption, which deliberately stops other processes from decrypting
it -- closing the browser doesn't help, and there's no supported way around it.

The extension sidesteps the problem entirely instead of fighting it: it runs
*inside* the browser, so `chrome.cookies` hands it the cookies already
decrypted, through the browser's own official API. It posts them here and this
module writes them in the Netscape format yt-dlp reads.
"""
import os
import tempfile
from pathlib import Path

from . import config

# Only YouTube/Google auth cookies are worth storing -- the extension already
# filters by domain, but never widen this without good reason: this file holds
# live session credentials.
_ALLOWED_DOMAIN_SUFFIXES = (".youtube.com", "youtube.com", ".google.com", "google.com")


def _is_allowed(domain: str) -> bool:
    domain = (domain or "").lower()
    return any(domain == s or domain.endswith(s) for s in _ALLOWED_DOMAIN_SUFFIXES)


def _format_netscape(cookies: list) -> str:
    lines = [
        "# Netscape HTTP Cookie File",
        "# Written by Downloader Youtube from the browser extension.",
        "",
    ]
    for c in cookies:
        domain = (c.get("domain") or "").strip()
        if not domain or not _is_allowed(domain):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        # A leading dot is what marks a cookie as valid for subdomains too;
        # Chrome reports that separately as hostOnly, so reconstruct it.
        include_subdomains = domain.startswith(".")
        path = (c.get("path") or "/").strip()
        secure = bool(c.get("secure"))
        # Session cookies have no expiry; yt-dlp accepts 0 for those.
        expiry = int(c.get("expirationDate") or 0)
        value = (c.get("value") or "").strip()
        lines.append(
            "\t".join([
                domain,
                "TRUE" if include_subdomains else "FALSE",
                path,
                "TRUE" if secure else "FALSE",
                str(expiry),
                name,
                value,
            ])
        )
    return "\n".join(lines) + "\n"


def save(cookies: list) -> int:
    """Writes the cookies atomically. Returns how many were actually stored."""
    text = _format_netscape(cookies or [])
    # The header lines are always present, so count real entries instead.
    count = sum(1 for line in text.splitlines() if line and not line.startswith("#"))
    if not count:
        return 0

    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    # Written via a temp file in the same directory so a failed/partial write
    # can never leave a truncated cookie file behind for a download to use.
    fd, tmp_path = tempfile.mkstemp(dir=str(config.APP_DIR), prefix=".cookies-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp_path, config.COOKIES_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    # These are live session credentials: keep them readable only by this user.
    try:
        os.chmod(config.COOKIES_FILE, 0o600)
    except OSError:
        pass
    return count


def path_if_present() -> str | None:
    return str(config.COOKIES_FILE) if config.COOKIES_FILE.exists() else None


def clear() -> bool:
    if not config.COOKIES_FILE.exists():
        return False
    config.COOKIES_FILE.unlink(missing_ok=True)
    return True

"""Current app version and update-check configuration."""

CURRENT_VERSION = "1.1"
GITHUB_REPO = "Slipers/downloader-youtube"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALLER_ASSET_NAME = "DownloaderYoutubeSetup.exe"


def parse_version(text: str) -> tuple:
    """'v1.10' / '1.10' -> (1, 10). Non-numeric parts are dropped."""
    cleaned = text.strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote_version: str, local_version: str = CURRENT_VERSION) -> bool:
    return parse_version(remote_version) > parse_version(local_version)

"""Detect an installed FFmpeg, or download+extract a static Windows build on demand."""
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from . import config

FFMPEG_BUILD_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run_version_check(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "-version"],
            capture_output=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_ffmpeg() -> str | None:
    """Return a usable ffmpeg location (directory containing the exe), or None."""
    settings = config.load_settings()
    saved = settings.get("ffmpeg_location")
    if saved and Path(saved, "ffmpeg.exe").exists() and _run_version_check(str(Path(saved, "ffmpeg.exe"))):
        return saved

    on_path = shutil.which("ffmpeg")
    if on_path and _run_version_check(on_path):
        return str(Path(on_path).parent)

    if config.FFMPEG_DIR.exists():
        for root, _dirs, files in os.walk(config.FFMPEG_DIR):
            if "ffmpeg.exe" in files and _run_version_check(str(Path(root, "ffmpeg.exe"))):
                return root

    return None


def is_installed() -> bool:
    return find_ffmpeg() is not None


def is_local_install() -> bool:
    """Whether the app's own auto-downloaded copy (not a system-wide ffmpeg) is present."""
    return config.FFMPEG_DIR.exists() and any(config.FFMPEG_DIR.rglob("ffmpeg.exe"))


def uninstall() -> bool:
    """Remove the app's locally auto-installed FFmpeg. Never touches a system-wide install."""
    removed = False
    if config.FFMPEG_DIR.exists():
        shutil.rmtree(config.FFMPEG_DIR, ignore_errors=True)
        removed = True
    settings = config.load_settings()
    saved = settings.get("ffmpeg_location")
    if saved and str(config.FFMPEG_DIR) in saved:
        config.save_settings({"ffmpeg_location": None})
    return removed


def install(on_progress) -> str:
    """Download the latest static FFmpeg build and extract it locally.

    on_progress(stage, percent) is called with stage in
    {"downloading", "extracting", "done"} and percent in 0..100 (or -1 if unknown).
    Returns the directory containing ffmpeg.exe/ffprobe.exe.
    """
    config.FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = config.FFMPEG_DIR / "ffmpeg_download.zip"

    def _report(block_num, block_size, total_size):
        if total_size > 0:
            percent = min(100, int(block_num * block_size * 100 / total_size))
            on_progress("downloading", percent)
        else:
            on_progress("downloading", -1)

    urllib.request.urlretrieve(FFMPEG_BUILD_URL, zip_path, reporthook=_report)

    on_progress("extracting", -1)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(config.FFMPEG_DIR)
    zip_path.unlink(missing_ok=True)

    bin_dir = None
    for root, _dirs, files in os.walk(config.FFMPEG_DIR):
        if "ffmpeg.exe" in files:
            bin_dir = root
            break

    if bin_dir is None:
        raise RuntimeError("Impossible de localiser ffmpeg.exe après extraction.")

    config.save_settings({"ffmpeg_location": bin_dir})
    on_progress("done", 100)
    return bin_dir

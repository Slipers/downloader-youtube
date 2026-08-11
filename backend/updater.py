"""Checks for a newer app build and swaps the installed files in place before
relaunching -- all without the user having to re-run the installer by hand.

Two update sources are checked, in order:

1. **Local dev build** (`LOCAL_SOURCE_DIR`): while iterating on this exact
   machine, a freshly rebuilt `dist/DownloaderYoutube` folder (with a
   `version.txt` written alongside it) is picked up directly -- no network,
   no hosting needed. This is what makes "click Update in the app" work
   without ever handing over a new installer link.
2. **GitHub Releases** (`UPDATE_REPO`): for real distribution once published.
   Each release's tag is the version (e.g. "v1.2.0") with an asset named
   "*-update.zip" containing the built `dist/DownloaderYoutube` folder
   (see README "Publier une mise à jour"). Inactive until UPDATE_REPO is set.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

APP_VERSION = "1.11"

# This machine's own dev build -- lets "Mettre à jour" work with zero hosting
# while iterating locally. Harmless no-op on any other machine (path won't exist).
LOCAL_SOURCE_DIR = Path(r"C:\Users\pasca\Desktop\Youtube Downloader Suite\dist\DownloaderYoutube")

# Point this at the GitHub repo where releases are published, e.g. "yourname/downloader-youtube".
UPDATE_REPO = "Slipers/downloader-youtube"
RELEASES_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts) or (0,)


def _check_local_source() -> dict | None:
    version_file = LOCAL_SOURCE_DIR / "version.txt"
    if not version_file.exists():
        return None
    try:
        local_version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if parse_version(local_version) <= parse_version(APP_VERSION):
        return None
    return {
        "available": True,
        "checked": True,
        "source": "local",
        "version": local_version,
        "current_version": APP_VERSION,
        "path": str(LOCAL_SOURCE_DIR),
        "notes": "Nouvelle version disponible (build local).",
    }


def _check_github() -> dict:
    if "OWNER/REPO" in UPDATE_REPO:
        return {"available": False, "checked": False, "current_version": APP_VERSION}

    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DownloaderYoutube-Updater"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"available": False, "checked": False, "current_version": APP_VERSION}

    latest_tag = data.get("tag_name", "")
    if parse_version(latest_tag) <= parse_version(APP_VERSION):
        return {"available": False, "checked": True, "current_version": APP_VERSION}

    asset_url = next(
        (a.get("browser_download_url") for a in data.get("assets", [])
         if a.get("name", "").lower().endswith("-update.zip")),
        None,
    )
    if not asset_url:
        return {"available": False, "checked": True, "current_version": APP_VERSION}

    return {
        "available": True,
        "checked": True,
        "source": "github",
        "version": latest_tag.lstrip("vV"),
        "current_version": APP_VERSION,
        "url": asset_url,
        "notes": (data.get("body") or "").strip(),
    }


def check_for_update() -> dict:
    """Returns {available, checked, source, version, current_version, url|path, notes}."""
    return _check_local_source() or _check_github()


def download_update(url: str, on_progress) -> Path:
    """on_progress(percent) with percent in 0..100, or -1 if unknown."""
    dest = Path(tempfile.gettempdir()) / "DownloaderYoutube_update.zip"

    def _report(block_num, block_size, total_size):
        if total_size > 0:
            on_progress(min(100, int(block_num * block_size * 100 / total_size)))
        else:
            on_progress(-1)

    urllib.request.urlretrieve(url, dest, reporthook=_report)
    return dest


def apply_update_and_restart(update_info: dict, on_progress):
    """Prepares the new files (extracting the zip if it's a remote update, or
    using the local dev build directory as-is) and hands off to a detached
    helper script that waits for this process to exit, mirrors the new files
    over the install directory, relaunches the app, then deletes itself."""
    if not is_frozen():
        raise RuntimeError("La mise à jour automatique n'est disponible que depuis la version installée.")

    install_dir = Path(sys.executable).resolve().parent
    exe_path = install_dir / "DownloaderYoutube.exe"
    pid = os.getpid()

    if update_info.get("source") == "local":
        new_files_dir = Path(update_info["path"])
        cleanup_lines = ""  # never delete the dev build folder
        on_progress(100)
    else:
        zip_path = download_update(update_info["url"], on_progress)
        new_files_dir = Path(tempfile.gettempdir()) / "DownloaderYoutube_update_extracted"
        shutil.rmtree(new_files_dir, ignore_errors=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(new_files_dir)
        cleanup_lines = f'rmdir /s /q "{new_files_dir}"\r\ndel "{zip_path}"\r\n'

    log_path = Path(tempfile.gettempdir()) / "DownloaderYoutube_update.log"
    script_path = Path(tempfile.gettempdir()) / "DownloaderYoutube_apply_update.bat"
    # Note: this is written to a .bat FILE and invoked as `cmd /c file.bat`, so
    # it's parsed exactly once by the invoked shell -- redirection operators
    # here must NOT be caret-escaped (that escaping is only needed when a
    # command is passed inline as a single quoted string to `cmd /c "..."`,
    # where an outer parse pass would otherwise consume the operator first).
    script_path.write_text(
        "@echo off\r\n"
        f'echo [%date% %time%] waiting for pid {pid} to exit > "{log_path}"\r\n'
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
        "if %errorlevel%==0 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        # A stray orphaned instance from an earlier session can still be
        # holding the link-server port even though the instance the user
        # actually clicked "Update" from has exited -- if so, the relaunch
        # below silently loses to the single-instance guard and just
        # refocuses that stale (still-outdated) window, making the update
        # look like it "didn't take" and re-prompting forever. Clear out any
        # other copy by image name, not just the one PID we started from.
        f'echo [%date% %time%] clearing any other running copies >> "{log_path}"\r\n'
        'taskkill /F /IM DownloaderYoutube.exe >NUL 2>&1\r\n'
        "timeout /t 1 /nobreak >nul\r\n"
        f'echo [%date% %time%] copying files >> "{log_path}"\r\n'
        f'robocopy "{new_files_dir}" "{install_dir}" /MIR /NFL /NDL /NJH /NJS >> "{log_path}" 2>&1\r\n'
        f'echo [%date% %time%] robocopy exit code %errorlevel% >> "{log_path}"\r\n'
        f'start "" "{exe_path}"\r\n'
        f'echo [%date% %time%] relaunched >> "{log_path}"\r\n'
        f"{cleanup_lines}"
        'del "%~f0"\r\n',
        encoding="utf-8",
    )

    subprocess.Popen(
        ["cmd", "/c", str(script_path)],
        creationflags=_NO_WINDOW,
        close_fds=True,
    )

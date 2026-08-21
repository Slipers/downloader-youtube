"""Manages the JavaScript runtime YouTube extraction now depends on.

Since mid-2026 YouTube requires two things that both need a JS engine:
solving the player's JS challenge (yt-dlp's "EJS"), and minting a PO token
for the streaming URLs. Without them YouTube only hands out tiny formats
(360p and below), which is why this is downloaded on demand rather than
treated as optional. One Deno binary covers both jobs.
"""
import os
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from . import config

# The startup install and a user-triggered fetch can both ask for the runtime;
# without this they'd download over each other into the same directory.
_install_lock = threading.Lock()

DENO_VERSION = "2.9.5"
DENO_URL = (
    f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/"
    "deno-x86_64-pc-windows-msvc.zip"
)
POT_SERVER_URL = (
    "https://github.com/Slipers/downloader-youtube/releases/download/"
    "v1.23/bgutil-pot-server-1.3.2.zip"
)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def deno_path() -> Path:
    return config.JS_RUNTIME_DIR / "deno.exe"


def pot_server_home() -> Path:
    return config.JS_RUNTIME_DIR / "server"


def is_installed() -> bool:
    return deno_path().exists() and (pot_server_home() / "src" / "generate_once.ts").exists()


def _warm_cache():
    """Deno transpiles the provider's TypeScript on first run, which blows past
    the plugin's 15s version-check timeout. Doing it once here means the first
    real download isn't the one that pays for it."""
    server = pot_server_home()
    node_mods = server / "node_modules"
    try:
        subprocess.run(
            [
                str(deno_path()), "run", "--allow-env", "--allow-net",
                f"--allow-ffi={node_mods}",
                f"--allow-read={node_mods},{Path.home() / '.cache' / 'bgutil-ytdlp-pot-provider'}",
                f"--allow-write={Path.home() / '.cache' / 'bgutil-ytdlp-pot-provider'}",
                str(server / "src" / "generate_once.ts"), "--version",
            ],
            capture_output=True,
            timeout=300,
            creationflags=_NO_WINDOW,
            env={**os.environ, "DENO_NO_PROMPT": "1", "DENO_NO_UPDATE_CHECK": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        pass  # a cold cache only costs time on the first fetch, never correctness


def ydl_opts() -> dict:
    """Options that wire yt-dlp to the local runtime. Empty when it isn't
    installed yet, so extraction still runs (just limited to low formats)."""
    if not is_installed():
        return {}
    return {
        "js_runtimes": {"deno": {"path": str(deno_path())}},
        "extractor_args": {
            "youtubepot-bgutilscript": {"server_home": [str(pot_server_home())]},
        },
    }


def _download(url: str, dest: Path, on_progress, stage: str):
    def _report(block_num, block_size, total_size):
        if total_size > 0:
            on_progress(stage, min(100, int(block_num * block_size * 100 / total_size)))
        else:
            on_progress(stage, -1)

    urllib.request.urlretrieve(url, dest, reporthook=_report)


def install(on_progress) -> bool:
    """Download Deno and the PO token server.

    on_progress(stage, percent) with stage in {"deno", "potserver",
    "extracting", "done"} and percent in 0..100 (or -1 if unknown).
    """
    with _install_lock:
        return _install_locked(on_progress)


def _install_locked(on_progress) -> bool:
    if is_installed():
        on_progress("done", 100)
        return True

    config.JS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if not deno_path().exists():
        deno_zip = config.JS_RUNTIME_DIR / "deno_download.zip"
        _download(DENO_URL, deno_zip, on_progress, "deno")
        on_progress("extracting", -1)
        with zipfile.ZipFile(deno_zip, "r") as zf:
            zf.extractall(config.JS_RUNTIME_DIR)
        deno_zip.unlink(missing_ok=True)

    if not (pot_server_home() / "src" / "generate_once.ts").exists():
        pot_zip = config.JS_RUNTIME_DIR / "potserver_download.zip"
        _download(POT_SERVER_URL, pot_zip, on_progress, "potserver")
        on_progress("extracting", -1)
        shutil.rmtree(pot_server_home(), ignore_errors=True)
        with zipfile.ZipFile(pot_zip, "r") as zf:
            zf.extractall(config.JS_RUNTIME_DIR)
        pot_zip.unlink(missing_ok=True)

    if not is_installed():
        raise RuntimeError("Le moteur JavaScript n'a pas pu être installé.")

    on_progress("warming", -1)
    _warm_cache()

    on_progress("done", 100)
    return True


def uninstall() -> bool:
    if not config.JS_RUNTIME_DIR.exists():
        return False
    shutil.rmtree(config.JS_RUNTIME_DIR, ignore_errors=True)
    return True

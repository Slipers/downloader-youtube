"""Manages the JavaScript runtime YouTube extraction now depends on.

Since mid-2026 YouTube requires two things that both need a JS engine:
solving the player's JS challenge (yt-dlp's "EJS"), and minting a PO token
for the streaming URLs. Without them YouTube only hands out tiny formats
(360p and below), which is why this is downloaded on demand rather than
treated as optional.

Both run on one bundled portable Node.js. EJS solving goes through yt-dlp's
own lightweight built-in scripts (fast, no extra setup). The PO token comes
from a small persistent HTTP server (bgutil) started once at app launch and
kept running -- an earlier version spawned a fresh script process per video
instead, which cost ~10 seconds on every single lookup just loading its
dependencies (canvas, jsdom, youtubei.js). A long-lived process pays that
cost once instead of on every video.
"""
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import config

# The startup install and a user-triggered fetch can both ask for the runtime;
# without this they'd download over each other into the same directory.
_install_lock = threading.Lock()
_server_lock = threading.Lock()
_server_process = None

NODE_VERSION = "22.23.2"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"
POT_SERVER_URL = (
    "https://github.com/Slipers/downloader-youtube/releases/download/"
    "v1.25/bgutil-pot-server-node-1.3.2.zip"
)
POT_SERVER_PORT = 4416

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def node_path() -> Path:
    return config.JS_RUNTIME_DIR / "node" / "node.exe"


def pot_server_home() -> Path:
    return config.JS_RUNTIME_DIR / "server"


def _server_entrypoint() -> Path:
    return pot_server_home() / "build" / "main.js"


def is_installed() -> bool:
    return node_path().exists() and _server_entrypoint().exists()


def ydl_opts() -> dict:
    """Options that wire yt-dlp to the local runtime. Empty when it isn't
    installed yet, so extraction still runs (just limited to low formats)."""
    if not is_installed():
        return {}
    return {
        "js_runtimes": {"node": {"path": str(node_path())}},
        "extractor_args": {
            "youtubepot-bgutilhttp": {"base_url": [f"http://127.0.0.1:{POT_SERVER_PORT}"]},
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
    """Download Node.js and the PO token server.

    on_progress(stage, percent) with stage in {"node", "potserver",
    "extracting", "done"} and percent in 0..100 (or -1 if unknown).
    """
    with _install_lock:
        return _install_locked(on_progress)


def _install_locked(on_progress) -> bool:
    if is_installed():
        on_progress("done", 100)
        return True

    # An earlier version bundled Deno + raw TypeScript source in this same
    # directory. Wipe it so stale files from that layout never get mixed in.
    if config.JS_RUNTIME_DIR.exists():
        shutil.rmtree(config.JS_RUNTIME_DIR, ignore_errors=True)

    config.JS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if not node_path().exists():
        node_zip = config.JS_RUNTIME_DIR / "node_download.zip"
        _download(NODE_URL, node_zip, on_progress, "node")
        on_progress("extracting", -1)
        with zipfile.ZipFile(node_zip, "r") as zf:
            zf.extractall(config.JS_RUNTIME_DIR)
        node_zip.unlink(missing_ok=True)
        extracted = next(config.JS_RUNTIME_DIR.glob("node-v*-win-x64"), None)
        if extracted:
            extracted.rename(config.JS_RUNTIME_DIR / "node")

    if not _server_entrypoint().exists():
        pot_zip = config.JS_RUNTIME_DIR / "potserver_download.zip"
        _download(POT_SERVER_URL, pot_zip, on_progress, "potserver")
        on_progress("extracting", -1)
        shutil.rmtree(pot_server_home(), ignore_errors=True)
        pot_server_home().mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(pot_zip, "r") as zf:
            zf.extractall(pot_server_home())
        pot_zip.unlink(missing_ok=True)

    if not is_installed():
        raise RuntimeError("Le moteur JavaScript n'a pas pu être installé.")

    on_progress("done", 100)
    return True


def _server_ready(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{POT_SERVER_PORT}/ping", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_server_running():
    """Starts the persistent PO token server if it isn't already running.
    Idempotent and cheap to call before every video fetch as a safety net --
    it's a single fast /ping check once the server is actually up."""
    global _server_process
    if not is_installed():
        return

    with _server_lock:
        if _server_ready():
            return
        if _server_process and _server_process.poll() is None:
            pass  # already starting from a previous call -- just wait below
        else:
            _server_process = subprocess.Popen(
                [str(node_path()), str(_server_entrypoint()), "--port", str(POT_SERVER_PORT)],
                cwd=str(pot_server_home()),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )

    for _ in range(200):  # up to ~40s -- cold start loads canvas/jsdom/youtubei.js
        if _server_ready():
            return
        time.sleep(0.2)


def stop_server():
    global _server_process
    with _server_lock:
        if _server_process and _server_process.poll() is None:
            _server_process.terminate()
        _server_process = None


def uninstall() -> bool:
    stop_server()
    if not config.JS_RUNTIME_DIR.exists():
        return False
    shutil.rmtree(config.JS_RUNTIME_DIR, ignore_errors=True)
    return True

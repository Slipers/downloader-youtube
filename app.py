"""Entry point: creates the pywebview window and wires the Api bridge."""
import sys
import threading
from pathlib import Path

import webview

from backend.api import Api
from backend.link_server import LinkServer
from backend.window_utils import focus_window

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"
ICON_PATH = BASE_DIR / "assets" / "icon.ico"
WINDOW_TITLE = "Downloader Youtube"


def main():
    api = Api()

    # Single-instance guard: the link server's port doubles as a lock. If
    # another copy is already running, bringing it forward (instead of
    # opening a second window) is what stops orphaned background instances
    # from piling up -- which otherwise silently lock the install directory
    # for future updates/reinstalls.
    try:
        link_server = LinkServer(api)
    except OSError:
        focus_window(WINDOW_TITLE)
        return

    window = webview.create_window(
        WINDOW_TITLE,
        str(FRONTEND_INDEX),
        js_api=api,
        width=1080,
        height=800,
        min_size=(900, 700),
        background_color="#0f1115",
    )
    def on_loaded():
        api.set_window(window)
        threading.Thread(target=api.sync_extension_if_outdated, daemon=True).start()

    window.events.loaded += on_loaded
    threading.Thread(target=link_server.serve_forever, daemon=True).start()
    window.events.closed += link_server.shutdown

    webview.start(icon=str(ICON_PATH) if ICON_PATH.exists() else None)


if __name__ == "__main__":
    main()

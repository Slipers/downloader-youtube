"""Entry point: creates the pywebview window and wires the Api bridge."""
import sys
import threading
from pathlib import Path

import webview

from backend.api import Api
from backend.link_server import LinkServer
from backend.window_utils import focus_window
from backend import js_runtime

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"
ICON_PATH = BASE_DIR / "assets" / "icon.ico"
WINDOW_TITLE = "Downloader Youtube"


def _allow_audio_autoplay():
    """Best-effort: lets the startup chime play unmuted the moment loading
    finishes instead of needing a click first. Chromium (and so WebView2)
    blocks unmuted audio autoplay before any user gesture, and pywebview
    doesn't expose a supported hook for extra WebView2 browser arguments --
    so this wraps its internal EdgeChrome.__init__ to append the flag onto
    the CreationProperties it already builds. Never fatal: if pywebview's
    internals change and this stops matching, the chime just falls back to
    playing on the first click/keypress instead (see frontend/js/app.js),
    exactly as before this existed.
    """
    if sys.platform != "win32":
        return
    try:
        from webview.platforms import edgechromium

        original_init = edgechromium.EdgeChrome.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            try:
                self.webview.CreationProperties.AdditionalBrowserArguments += (
                    " --autoplay-policy=no-user-gesture-required"
                )
            except Exception:
                pass

        edgechromium.EdgeChrome.__init__ = patched_init
    except Exception:
        pass


def main():
    _allow_audio_autoplay()
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

    # Kicked off here rather than from the frontend's init: the PO token server
    # takes a good while to boot (it loads some heavy JS dependencies), and the
    # first video fetch has to wait for it. Starting it the moment the process
    # does -- in parallel with building the window -- buys back every second
    # the UI spends starting up, which is usually enough for it to be ready
    # before the user has finished pasting a link.
    if js_runtime.is_installed():
        threading.Thread(target=js_runtime.ensure_server_running, daemon=True).start()

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
    window.events.closed += js_runtime.stop_server

    webview.start(icon=str(ICON_PATH) if ICON_PATH.exists() else None)


if __name__ == "__main__":
    main()

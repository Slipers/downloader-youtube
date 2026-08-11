"""Entry point: creates the pywebview window and wires the Api bridge."""
import sys
from pathlib import Path

import webview

from backend.api import Api

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"
ICON_PATH = BASE_DIR / "assets" / "icon.ico"


def main():
    api = Api()
    window = webview.create_window(
        "Downloader Youtube",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1080,
        height=800,
        min_size=(960, 720),
        background_color="#0f1115",
    )
    window.events.loaded += lambda: api.set_window(window)
    webview.start(icon=str(ICON_PATH) if ICON_PATH.exists() else None)


if __name__ == "__main__":
    main()

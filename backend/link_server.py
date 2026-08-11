"""Local HTTP server the browser extension talks to (pairing + deep-link open).

Runs on 127.0.0.1 only. CORS is locked to the extension's own origin so that
regular web pages cannot trigger it. See extension/background.js for the client.
"""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

ALLOWED_ORIGIN = f"chrome-extension://{config.EXTENSION_ID}"


class LinkRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
        pass

    # ---- helpers ----------------------------------------------------
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    # ---- routing ------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/ping":
            settings = config.load_settings()
            self._send_json(200, {"ok": True, "app": "ytdl-suite", "paired": bool(settings.get("paired"))})
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):
        data = self._read_json_body()

        if self.path == "/link":
            token = secrets.token_hex(16)
            config.save_settings({"paired": True, "pairing_token": token})
            if self.server.api:
                self.server.api.on_extension_linked()
            self._send_json(200, {"ok": True, "token": token})
            return

        if self.path == "/open-download":
            url = (data.get("url") or "").strip()
            settings = config.load_settings()
            valid = bool(settings.get("paired")) and data.get("token") == settings.get("pairing_token")
            if not url or not valid:
                self._send_json(401, {"ok": False})
                return
            if self.server.api:
                self.server.api.on_open_download(url)
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"ok": False})


class LinkServer(ThreadingHTTPServer):
    daemon_threads = True
    # http.server.HTTPServer sets allow_reuse_address = 1 by default, which
    # lets a second bind on this port silently succeed on Windows. That would
    # defeat app.py's single-instance guard, which relies on the bind
    # failing with OSError when another instance already owns the port --
    # so it's explicitly forced back off here.
    allow_reuse_address = False

    def __init__(self, api):
        super().__init__(("127.0.0.1", config.LINK_SERVER_PORT), LinkRequestHandler)
        self.api = api

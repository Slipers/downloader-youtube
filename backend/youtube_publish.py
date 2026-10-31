"""Publishing to a YouTube channel through the official Data API v3.

Sign-in is Google's own OAuth 2.0 flow for installed apps: the consent page
opens in the user's normal browser (the app never sees a password), with
PKCE and a `state` check, and the answer comes back on a one-shot loopback
server bound to 127.0.0.1. Only the refresh token is kept, encrypted with
Windows DPAPI (readable by this Windows user only); disconnecting revokes it
at Google before deleting it.
"""
import base64
import ctypes
import hashlib
import http.server
import io
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from ctypes import wintypes
from pathlib import Path

import requests

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    # Only to show which channel is connected.
    "https://www.googleapis.com/auth/youtube.readonly",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3"

CLIENT_FILE_NAME = "youtube_oauth.json"
TOKEN_FILE = config.APP_DIR / "youtube_publish.bin"

CONNECT_TIMEOUT = 300
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 5000
UPLOAD_RETRIES = 8


class PublishError(Exception):
    """A failure worth showing to the user as is (already in French)."""


class PublishCancelled(Exception):
    pass


# ---- OAuth client ------------------------------------------------------------

def _client() -> dict | None:
    """The OAuth client of the app's Google Cloud project: the JSON Google
    gives for a "Desktop app" client. Looked up next to the settings first
    (lets one machine override it), then bundled with the app. Kept out of
    the public repository."""
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for path in (config.APP_DIR / CLIENT_FILE_NAME, bundled_root / "keys" / CLIENT_FILE_NAME):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data = data.get("installed") or data
        if data.get("client_id") and data.get("client_secret"):
            return data
    return None


def is_configured() -> bool:
    return _client() is not None


# ---- token storage (DPAPI) -------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), "DownloaderYoutube", None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    if not ok:
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _load() -> dict | None:
    try:
        return json.loads(_dpapi(TOKEN_FILE.read_bytes(), protect=False))
    except (OSError, ValueError):
        return None


def _save(data: dict):
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(_dpapi(json.dumps(data).encode("utf-8"), protect=True))


_access = {"token": None, "expires": 0.0}
_access_lock = threading.Lock()


def _forget():
    _access.update(token=None, expires=0.0)
    TOKEN_FILE.unlink(missing_ok=True)


# ---- sign-in ---------------------------------------------------------------------

_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Downloader Youtube</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:"Segoe UI",system-ui,sans-serif;background:#0b0c10;color:#f5f6fa}}
.card{{text-align:center;padding:44px 52px;border-radius:24px;background:#181b23;border:1px solid #2a2d38;max-width:420px}}
.icon{{width:64px;height:64px;border-radius:50%;margin:0 auto 18px;display:flex;align-items:center;justify-content:center;
font-size:30px;background:{color}22;color:{color}}}h1{{font-size:21px;margin:0 0 10px}}p{{color:#b7bacb;margin:0;line-height:1.5}}</style>
</head><body><div class="card"><div class="icon">{icon}</div><h1>{title}</h1><p>{text}</p></div></body></html>"""

_SUCCESS_PAGE = _PAGE.format(color="#22d3c5", icon="&#10003;", title="Chaîne connectée",
                             text="Vous pouvez fermer cet onglet et revenir dans Downloader Youtube.")
_FAILURE_PAGE = _PAGE.format(color="#ff5470", icon="&#10005;", title="Connexion non effectuée",
                             text="Vous pouvez fermer cet onglet et réessayer depuis Downloader Youtube.")

_connect_cancel = threading.Event()


def cancel_connect():
    _connect_cancel.set()


def connect() -> dict:
    """Runs the whole sign-in and returns the connected channel."""
    client = _client()
    if not client:
        raise PublishError("La publication YouTube n'est pas configurée dans cette version de l'application.")
    _connect_cancel.clear()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    answer = {}
    answered = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if not ({"code", "error", "state"} & query.keys()):
                self.send_response(404)  # favicon and the like
                self.end_headers()
                return
            # A response that doesn't carry our state is someone else's (or
            # forged) and is rejected outright.
            ok = query.get("state", [""])[0] == state and "code" in query
            if ok:
                answer["code"] = query["code"][0]
            else:
                answer["error"] = query.get("error", ["state_mismatch"])[0]
            page = (_SUCCESS_PAGE if ok else _FAILURE_PAGE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            answered.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            # Always ask: shows the account/channel picker, and guarantees a
            # refresh token even on a second connection.
            "prompt": "select_account consent",
        }))
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while not answered.wait(0.3):
            if _connect_cancel.is_set():
                raise PublishCancelled()
            if time.monotonic() > deadline:
                raise PublishError("La connexion a expiré. Réessayez.")
    finally:
        server.shutdown()
        server.server_close()

    if "code" not in answer:
        if answer.get("error") == "access_denied":
            raise PublishError("Connexion refusée : l'autorisation n'a pas été accordée.")
        raise PublishError("La connexion n'a pas abouti. Réessayez.")

    tokens = _token_request({
        "code": answer["code"],
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    if not tokens.get("refresh_token"):
        raise PublishError("Google n'a pas fourni d'accès durable. Réessayez la connexion.")
    granted = set((tokens.get("scope") or "").split())
    if SCOPES[0] not in granted:
        raise PublishError("L'autorisation de mettre en ligne des vidéos n'a pas été cochée. Réessayez en l'acceptant.")
    channel = _fetch_channel(tokens["access_token"])
    _save({"refresh_token": tokens["refresh_token"], "channel": channel})
    with _access_lock:
        _access.update(token=tokens["access_token"], expires=time.time() + int(tokens.get("expires_in", 3600)) - 60)
    return channel


def _token_request(data: dict) -> dict:
    try:
        resp = requests.post(TOKEN_URL, data=data, timeout=30)
    except requests.RequestException:
        raise PublishError("Impossible de joindre Google. Vérifiez votre connexion internet.")
    body = resp.json() if resp.content else {}
    if resp.status_code != 200:
        if body.get("error") == "invalid_grant":
            _forget()
            raise PublishError("L'accès à la chaîne a expiré ou a été révoqué. Reconnectez votre chaîne.")
        raise PublishError(f"Google a refusé la connexion ({body.get('error_description') or body.get('error') or resp.status_code}).")
    return body


def _fetch_channel(access_token: str) -> dict:
    resp = requests.get(f"{API_URL}/channels", params={"part": "snippet", "mine": "true"},
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    _raise_for(resp)
    items = resp.json().get("items") or []
    if not items:
        raise PublishError("Ce compte Google n'a pas encore de chaîne YouTube. Créez-la sur youtube.com, puis reconnectez-vous.")
    snippet = items[0]["snippet"]
    thumbs = snippet.get("thumbnails") or {}
    return {
        "id": items[0]["id"],
        "title": snippet.get("title") or "Ma chaîne",
        "handle": snippet.get("customUrl") or "",
        "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
    }


def _access_token() -> str:
    with _access_lock:
        if _access["token"] and time.time() < _access["expires"]:
            return _access["token"]
        stored = _load()
        client = _client()
        if not stored or not client:
            raise PublishError("Aucune chaîne YouTube n'est connectée.")
        tokens = _token_request({
            "refresh_token": stored["refresh_token"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "refresh_token",
        })
        _access.update(token=tokens["access_token"], expires=time.time() + int(tokens.get("expires_in", 3600)) - 60)
        return _access["token"]


def status() -> dict:
    stored = _load()
    return {
        "configured": is_configured(),
        "connected": bool(stored),
        "channel": stored.get("channel") if stored else None,
    }


def disconnect():
    stored = _load()
    if stored:
        try:
            requests.post(REVOKE_URL, data={"token": stored["refresh_token"]}, timeout=15)
        except requests.RequestException:
            pass  # deleted locally either way
    _forget()


# ---- errors -----------------------------------------------------------------------

_REASONS = {
    "quotaExceeded": "La limite quotidienne d'envois de l'application est atteinte. Réessayez demain.",
    "uploadLimitExceeded": "Votre chaîne a atteint sa limite d'envois pour aujourd'hui. Réessayez demain.",
    "rateLimitExceeded": "Trop d'envois d'un coup. Patientez quelques minutes et réessayez.",
    "invalidPublishAt": "La date de programmation est invalide : elle doit être dans le futur.",
    "invalidTitle": "Le titre est invalide (100 caractères maximum, sans < ni >).",
    "invalidDescription": "La description est invalide (5000 caractères maximum, sans < ni >).",
    "youtubeSignupRequired": "Ce compte Google n'a pas encore de chaîne YouTube.",
    "mediaBodyRequired": "Le fichier vidéo est vide ou illisible.",
    "invalidFilename": "Le nom du fichier vidéo est refusé par YouTube.",
}


def _raise_for(resp: requests.Response):
    if resp.status_code < 300:
        return
    try:
        error = resp.json().get("error") or {}
    except ValueError:
        error = {}
    reason = ((error.get("errors") or [{}])[0]).get("reason") or ""
    if reason in _REASONS:
        raise PublishError(_REASONS[reason])
    if resp.status_code == 401:
        with _access_lock:
            _access.update(token=None, expires=0.0)
        raise PublishError("L'accès à la chaîne a expiré. Reconnectez votre chaîne.")
    raise PublishError(f"YouTube a refusé la demande : {error.get('message') or resp.status_code}")


# ---- publishing ---------------------------------------------------------------------

def clean_title(title: str) -> str:
    # YouTube rejects angle brackets outright.
    title = " ".join((title or "").replace("<", "‹").replace(">", "›").split())
    return title[:TITLE_MAX]


def clean_description(description: str) -> str:
    text = (description or "").replace("<", "‹").replace(">", "›")
    data = text.encode("utf-8")[:DESCRIPTION_MAX_BYTES]
    return data.decode("utf-8", errors="ignore")


def prepare_thumbnail(source: bytes) -> bytes:
    """Any image (webp, png, huge jpg) -> a JPEG YouTube accepts (<= 2 Mo)."""
    from PIL import Image

    image = Image.open(io.BytesIO(source)).convert("RGB")
    if image.width > 1920:
        image = image.resize((1920, round(image.height * 1920 / image.width)), Image.LANCZOS)
    for quality in (92, 85, 75, 65):
        out = io.BytesIO()
        image.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= MAX_THUMBNAIL_BYTES:
            return out.getvalue()
    image.thumbnail((1280, 720))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=80)
    return out.getvalue()


class _ProgressReader:
    """The file from `offset` on, as a sized stream: requests sends it with a
    Content-Length (no chunked encoding) straight from disk, reporting
    progress and honoring cancellation as it goes."""

    def __init__(self, path, offset, size, on_progress, cancel_event):
        self._file = open(path, "rb")
        self._file.seek(offset)
        self._sent = offset
        self._remaining = size - offset
        self._size = size
        self._on_progress = on_progress
        self._cancel = cancel_event

    def __len__(self):
        return self._remaining

    def read(self, n=-1):
        if self._cancel.is_set():
            raise PublishCancelled()
        chunk = self._file.read(n if n and n > 0 else 1024 * 1024)
        self._sent += len(chunk)
        self._on_progress(self._sent, self._size)
        return chunk

    def close(self):
        self._file.close()


def _received_offset(session_url: str, size: int):
    """Asks the upload session how much it already has. Returns the next
    offset, or the finished video resource when the upload is complete."""
    resp = requests.put(session_url, headers={
        "Authorization": f"Bearer {_access_token()}",
        "Content-Length": "0",
        "Content-Range": f"bytes */{size}",
    }, timeout=30)
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 308:
        received = resp.headers.get("Range")  # "bytes=0-12345"
        return int(received.rsplit("-", 1)[1]) + 1 if received else 0
    _raise_for(resp)
    return 0


def upload(path: str, title: str, description: str, privacy: str, publish_at: str | None,
           made_for_kids: bool, thumbnail: bytes | None, on_progress, cancel_event) -> dict:
    """Resumable upload: a dropped connection picks up where it stopped
    instead of starting over. Returns the video id and the thumbnail
    outcome (a thumbnail failure never fails the publication)."""
    if not os.path.isfile(path):
        raise PublishError("Le fichier vidéo est introuvable (déplacé ou supprimé ?).")
    size = os.path.getsize(path)
    status_part = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)}
    if publish_at:
        # Scheduling only exists on private videos: YouTube flips them to
        # public at that time.
        status_part.update(privacyStatus="private", publishAt=publish_at)
    body = {
        "snippet": {"title": clean_title(title), "description": clean_description(description), "categoryId": "22"},
        "status": status_part,
    }
    try:
        init = requests.post(
            f"{UPLOAD_URL}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {_access_token()}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/*",
            },
            data=json.dumps(body),
            timeout=30,
        )
    except requests.RequestException:
        raise PublishError("Impossible de joindre YouTube. Vérifiez votre connexion internet.")
    _raise_for(init)
    session_url = init.headers["Location"]

    offset, video, failures = 0, None, 0
    while video is None:
        reader = _ProgressReader(path, offset, size, on_progress, cancel_event)
        resp = None
        try:
            resp = requests.put(session_url, data=reader, headers={
                "Authorization": f"Bearer {_access_token()}",
                "Content-Type": "video/*",
                "Content-Range": f"bytes {offset}-{size - 1}/{size}" if size else "bytes */0",
            }, timeout=(30, 600))
        except PublishCancelled:
            raise
        except requests.RequestException:
            if cancel_event.is_set():
                raise PublishCancelled()
        finally:
            reader.close()
        if resp is not None and resp.status_code in (200, 201):
            video = resp.json()
            break
        if resp is not None and resp.status_code not in (308, 408, 429, 500, 502, 503, 504):
            _raise_for(resp)
        failures += 1
        if failures > UPLOAD_RETRIES:
            raise PublishError("La connexion à YouTube a été coupée trop de fois. Réessayez.")
        if cancel_event.wait(min(2 ** failures, 30)):
            raise PublishCancelled()
        state = _received_offset(session_url, size)
        if isinstance(state, dict):
            video = state
        else:
            offset = state

    result = {"video_id": video["id"], "thumbnail_error": None}
    if thumbnail:
        try:
            resp = requests.post(
                f"{UPLOAD_URL}/thumbnails/set",
                params={"videoId": video["id"], "uploadType": "media"},
                headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "image/jpeg"},
                data=thumbnail,
                timeout=60,
            )
            if resp.status_code == 403:
                result["thumbnail_error"] = (
                    "La miniature n'a pas pu être ajoutée : YouTube demande de valider votre chaîne "
                    "par téléphone pour utiliser des miniatures personnalisées (youtube.com/verify)."
                )
            else:
                _raise_for(resp)
        except (PublishError, requests.RequestException) as exc:
            result["thumbnail_error"] = result["thumbnail_error"] or f"La miniature n'a pas pu être ajoutée ({exc})."
    return result

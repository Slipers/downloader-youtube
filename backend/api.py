"""Bridge class exposed to the JS frontend via pywebview's js_api."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import webview
from yt_dlp.utils import DownloadCancelled

from . import config, downloader, ffmpeg_manager, version

YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[\w-]+"
)

COOKIES_FILE_PATH = config.APP_DIR / "imported_cookies.txt"


class Api:
    def __init__(self):
        self.window = None
        self._cancel_event = None

    def set_window(self, window):
        self.window = window

    def _push(self, event: str, payload=None):
        if not self.window:
            return
        try:
            self.window.evaluate_js(f"window.__bridge__({json.dumps(event)}, {json.dumps(payload)})")
        except Exception:
            pass

    # ---- settings / theme -------------------------------------------------
    def get_settings(self):
        settings = config.load_settings()
        settings["quality_tiers"] = downloader.QUALITY_TIERS
        settings["recommended_audio_kbps"] = downloader.RECOMMENDED_AUDIO_KBPS
        settings["fps_choices"] = downloader.FPS_CHOICES
        settings["video_containers"] = downloader.VIDEO_CONTAINERS
        settings["audio_formats"] = downloader.AUDIO_FORMATS
        settings["current_version"] = version.CURRENT_VERSION
        return settings

    def mark_tutorial_seen(self):
        config.save_settings({"tutorial_seen": True})
        return True

    def save_theme(self, theme: str):
        config.save_settings({"theme": theme})
        return True

    def save_preference(self, key: str, value):
        allowed = {
            "show_preview", "last_quality", "last_fps", "last_export_type",
            "last_output_format", "confetti_seconds",
        }
        if key in allowed:
            config.save_settings({key: value})
        return True

    # ---- folder picker (native) -------------------------------------------
    def pick_folder(self):
        if not self.window:
            return None
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        folder = result[0] if isinstance(result, (list, tuple)) else result
        config.save_settings({"last_download_dir": folder})
        return folder

    def open_folder(self, path: str):
        try:
            os.startfile(path)
            return True
        except OSError:
            return False

    # ---- cookies.txt import (fallback when browser cookie decryption is blocked) ----
    def get_cookies_file_status(self):
        path = config.load_settings().get("cookies_file")
        return {"imported": bool(path and Path(path).exists())}

    def import_cookies_file(self):
        if not self.window:
            return {"ok": False, "error": "Fenêtre indisponible."}
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Fichiers cookies (*.txt)", "Tous les fichiers (*.*)"),
        )
        if not result:
            return {"ok": False, "error": None}
        src = Path(result[0] if isinstance(result, (list, tuple)) else result)
        try:
            config.APP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, COOKIES_FILE_PATH)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        config.save_settings({"cookies_file": str(COOKIES_FILE_PATH)})
        return {"ok": True}

    def clear_cookies_file(self):
        try:
            COOKIES_FILE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        config.save_settings({"cookies_file": None})
        return True

    # ---- video metadata -------------------------------------------------
    def is_valid_youtube_url(self, url: str):
        return bool(url and YOUTUBE_URL_RE.match(url.strip()))

    def fetch_video_info(self, url: str):
        if not self.is_valid_youtube_url(url):
            return {"ok": False, "error": "Ce lien ne ressemble pas à une URL YouTube valide."}
        try:
            info = downloader.get_video_info(url.strip(), cookies_file=self._cookies_file())
            return {"ok": True, "data": info}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc)}

    def _cookies_file(self):
        path = config.load_settings().get("cookies_file")
        return path if path and Path(path).exists() else None

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if downloader.is_decrypt_blocked_error(message):
            return (
                "Cette vidéo nécessite une connexion à YouTube, et vos navigateurs installés "
                "protègent leurs cookies d'une façon que l'application ne peut pas déchiffrer "
                "automatiquement (fermer le navigateur ne suffit pas dans ce cas). Ouvrez les "
                "Paramètres (⚙) et importez un fichier cookies.txt exporté depuis votre navigateur "
                "pour contourner ce blocage définitivement."
            )
        if downloader.is_bot_check_error(message) or downloader.is_cookie_extraction_error(message):
            return (
                "Cette vidéo nécessite une vérification de connexion à YouTube. "
                "L'application a essayé de s'authentifier automatiquement mais n'y est pas arrivée — "
                "fermez complètement votre navigateur (y compris les processus en arrière-plan) puis "
                "réessayez, ou importez un fichier cookies.txt dans les Paramètres (⚙)."
            )
        return f"Impossible de récupérer la vidéo : {message}"

    def get_storyboard_sprite(self, url: str):
        try:
            return {"ok": True, "data": downloader.fetch_storyboard_sprite(url)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- ffmpeg -------------------------------------------------------------
    def check_ffmpeg(self):
        return ffmpeg_manager.is_installed()

    def install_ffmpeg(self):
        def on_progress(stage, percent):
            self._push("ffmpeg_progress", {"stage": stage, "percent": percent})

        try:
            location = ffmpeg_manager.install(on_progress)
            return {"ok": True, "location": location}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_ffmpeg_status(self):
        return {
            "installed": ffmpeg_manager.is_installed(),
            "local": ffmpeg_manager.is_local_install(),
        }

    def uninstall_ffmpeg(self):
        try:
            removed = ffmpeg_manager.uninstall()
            return {"ok": True, "removed": removed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- auto-update ------------------------------------------------------
    def check_for_update(self):
        try:
            req = urllib.request.Request(
                version.GITHUB_LATEST_RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "DownloaderYoutube"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag = data.get("tag_name", "")
            if not tag or not version.is_newer(tag):
                return {"available": False}

            asset = next(
                (a for a in data.get("assets", []) if a.get("name") == version.INSTALLER_ASSET_NAME),
                None,
            )
            if not asset:
                return {"available": False}

            return {
                "available": True,
                "version": tag.lstrip("vV"),
                "download_url": asset["browser_download_url"],
                "size": asset.get("size"),
                "notes": (data.get("body") or "").strip(),
            }
        except Exception:
            return {"available": False}

    def download_update(self, download_url: str):
        try:
            dest = Path(tempfile.gettempdir()) / version.INSTALLER_ASSET_NAME

            def _report(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(100, int(block_num * block_size * 100 / total_size))
                    self._push("update_download_progress", {"percent": percent})

            urllib.request.urlretrieve(download_url, dest, reporthook=_report)
            return {"ok": True, "path": str(dest)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def install_update(self, installer_path: str):
        if not getattr(sys, "frozen", False):
            return {"ok": False, "error": "La mise à jour automatique n'est disponible que pour la version installée."}
        install_dir = Path(sys.executable).resolve().parent
        try:
            subprocess.Popen(
                [installer_path, "--silent-update", str(install_dir)],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        threading.Timer(0.6, lambda: os._exit(0)).start()
        return {"ok": True}

    # ---- download -------------------------------------------------------
    def start_download(self, url: str, options: dict):
        self._cancel_event = threading.Event()
        config.save_settings(
            {
                "last_quality": options.get("quality"),
                "last_fps": options.get("fps"),
                "last_export_type": options.get("export_type"),
                "last_output_format": options.get("output_format"),
            }
        )
        threading.Thread(target=self._run_download, args=(url, options, self._cancel_event), daemon=True).start()
        return {"started": True}

    def cancel_download(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
        return True

    def _run_download(self, url, options, cancel_event):
        started = time.monotonic()
        try:
            ffmpeg_location = ffmpeg_manager.find_ffmpeg()
            opts = downloader.build_ydl_opts(options, ffmpeg_location)

            def on_progress(payload):
                self._push("download_progress", payload)

            result = downloader.download(
                url, opts, on_progress, cancel_event=cancel_event,
                cookies_browser_hint=options.get("cookies_browser_hint"),
                cookies_file=self._cookies_file(),
            )
            result["elapsed"] = round(time.monotonic() - started, 1)
            config.save_settings({"last_download_dir": options.get("dest_dir")})
            self._push("download_complete", result)
        except DownloadCancelled:
            self._push("download_cancelled", {})
        except Exception as exc:
            self._push("download_error", {"error": self._friendly_error(exc)})

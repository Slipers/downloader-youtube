"""Bridge class exposed to the JS frontend via pywebview's js_api."""
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import webview
from yt_dlp.utils import DownloadCancelled

from . import browsers, config, downloader, extension_installer, ffmpeg_manager, updater, window_utils

YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[\w-]+"
)
TIKTOK_URL_RE = re.compile(r"^https?://(www\.|vm\.|vt\.|m\.)?tiktok\.com/")
INSTAGRAM_URL_RE = re.compile(r"^https?://(www\.)?instagram\.com/(reel|p|tv)/[\w-]+")
SUPPORTED_URL_PATTERNS = (YOUTUBE_URL_RE, TIKTOK_URL_RE, INSTAGRAM_URL_RE)

WINDOW_TITLE = "Downloader Youtube"


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
        return settings

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

    # ---- video metadata -------------------------------------------------
    def is_valid_youtube_url(self, url: str):
        url = (url or "").strip()
        return bool(url and any(pattern.match(url) for pattern in SUPPORTED_URL_PATTERNS))

    def fetch_video_info(self, url: str):
        if not self.is_valid_youtube_url(url):
            return {"ok": False, "error": "Ce lien ne ressemble pas à une URL YouTube, TikTok ou Instagram valide."}
        try:
            info = downloader.get_video_info(url.strip())
            return {"ok": True, "data": info}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc)}

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if downloader.is_decrypt_blocked_error(message):
            return (
                "Cette vidéo nécessite une connexion à YouTube, et vos navigateurs installés "
                "protègent leurs cookies d'une façon que l'application ne peut pas déchiffrer "
                "automatiquement (fermer le navigateur ne suffit pas dans ce cas)."
            )
        if downloader.is_bot_check_error(message) or downloader.is_cookie_extraction_error(message):
            return (
                "Cette vidéo nécessite une vérification de connexion à YouTube. "
                "L'application a essayé de s'authentifier automatiquement mais n'y est pas arrivée — "
                "fermez complètement votre navigateur (y compris les processus en arrière-plan) puis réessayez."
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
            )
            result["elapsed"] = round(time.monotonic() - started, 1)
            total = config.load_settings().get("total_downloads", 0) + 1
            config.save_settings({"last_download_dir": options.get("dest_dir"), "total_downloads": total})
            result["total_downloads"] = total
            self._push("download_complete", result)
        except DownloadCancelled:
            self._push("download_cancelled", {})
        except Exception as exc:
            self._push("download_error", {"error": self._friendly_error(exc)})

    # ---- browser extension ------------------------------------------------
    def get_extension_status(self):
        settings = config.load_settings()
        return {"paired": bool(settings.get("paired"))}

    def list_browsers(self):
        return browsers.detect_browsers()

    def install_extension(self, browser_id: str, mode: str = "manual"):
        return extension_installer.install_extension(browser_id, mode)

    def launch_browser(self, browser_id: str):
        return browsers.launch_browser(browser_id)

    def on_extension_linked(self):
        """Called from the link-server thread when the extension pairs."""
        window_utils.focus_window(WINDOW_TITLE)
        self._push("extension_linked", {})

    def on_open_download(self, url: str):
        """Called from the link-server thread when the extension's download button is clicked."""
        window_utils.focus_window(WINDOW_TITLE)
        self._push("open_download", {"url": url})

    # ---- app / extension updates -------------------------------------------
    def get_app_version(self):
        return updater.APP_VERSION

    def get_changelog(self):
        return updater.get_changelog()

    def check_for_update(self):
        return updater.check_for_update()

    def start_app_update(self, update_info: dict):
        threading.Thread(target=self._run_update, args=(update_info,), daemon=True).start()
        return {"started": True}

    def _run_update(self, update_info: dict):
        try:
            def on_progress(percent):
                self._push("update_progress", {"percent": percent})

            self._push("update_installing", {})
            updater.apply_update_and_restart(update_info, on_progress)
            time.sleep(0.5)
            if self.window:
                self.window.destroy()
        except Exception as exc:
            self._push("update_error", {"error": str(exc)})

    def sync_extension_if_outdated(self):
        """Called once at startup: if this build ships a newer extension than
        what's synced on disk (e.g. right after an app update), refresh it
        silently and let the user know a browser-side reload is needed."""
        extension_installer.cleanup_stale_policies()
        result = self.check_extension_update()
        if result.get("available"):
            extension_installer.sync_only()
            self._push("extension_auto_synced", {"version": result["version"]})

    def check_extension_update(self):
        try:
            bundled_version = json.loads(
                (config.EXTENSION_SRC_DIR / "manifest.json").read_text(encoding="utf-8")
            ).get("version", "0")
            installed_path = config.EXTENSION_INSTALL_DIR / "manifest.json"
            if not installed_path.exists():
                return {"available": False}
            installed_version = json.loads(installed_path.read_text(encoding="utf-8")).get("version", "0")
        except (OSError, json.JSONDecodeError):
            return {"available": False}

        if updater.parse_version(bundled_version) > updater.parse_version(installed_version):
            return {"available": True, "version": bundled_version, "current_version": installed_version}
        return {"available": False}

    def update_extension_files(self):
        return extension_installer.sync_only()

"""Bridge class exposed to the JS frontend via pywebview's js_api."""
import base64
import json
import math
import os
import re
import threading
import time
import webbrowser
from pathlib import Path

import requests
import webview
import yt_dlp
from yt_dlp.utils import DownloadCancelled, sanitize_filename

from . import browsers, clipboard, config, downloader, extension_installer, ffmpeg_manager, js_runtime, updater, window_utils, youtube_publish

YOUTUBE_URL_RE = re.compile(r"^https?://(?:[\w-]+\.)?(?:youtube\.com|youtu\.be)/")
# Per-platform checks live in the frontend catalog; any web page is worth
# handing to yt-dlp, whose generic extractor covers sites it has no rule for.
WEB_URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)

WINDOW_TITLE = "Downloader Youtube"


class Api:
    def __init__(self):
        self.window = None
        self._cancel_event = None
        self._update_lock = threading.Lock()
        self._updating = False

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
            "last_output_format", "confetti_seconds", "last_seen_version",
            "sfx_enabled", "always_confirm_video", "copy_thumbnail",
            "embed_metadata", "on_existing_file", "files_setup", "publish_autofill",
        }
        if key in allowed:
            config.save_settings({key: value})
        return True

    # ---- folder picker (native) -------------------------------------------
    def pick_folder(self, remember=True):
        if not self.window:
            return None
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        folder = result[0] if isinstance(result, (list, tuple)) else result
        if remember:
            config.save_settings({"last_download_dir": folder})
        return folder

    def open_folder(self, path: str):
        try:
            os.startfile(path)
            return True
        except OSError:
            return False

    # ---- video metadata -------------------------------------------------
    def fetch_video_info(self, url: str):
        url = (url or "").strip()
        if not WEB_URL_RE.match(url):
            return {"ok": False, "error": "Ce lien n'est pas une adresse web valide (elle doit commencer par https://)."}

        # There's no real byte-level progress for a metadata fetch (it's one
        # blocking call, not a download), so this reports elapsed time against
        # a typical duration instead -- an asymptotic curve that closes in on
        # 92% but deliberately never claims completion on its own. The actual
        # 100% only ever comes from the real result landing, below.
        #
        # The time constant below is tuned for the common case: a warm PO
        # token server (see js_runtime.py) makes a fetch take ~2-5s. It used
        # to be tuned for the ~15-20s a cold/per-video subprocess spawn used
        # to cost, which meant the real result now lands while this curve is
        # still only around 40-50% -- looking broken rather than just fast.
        # A rare cold-start fetch right after launch (~20s) still just sits
        # near 92% for longer, which is the intended honest behavior.
        stop_ticker = threading.Event()

        def ticker():
            start = time.time()
            while not stop_ticker.wait(0.15):
                elapsed = time.time() - start
                percent = round(92 * (1 - math.exp(-elapsed / 1.3)))
                self._push("video_fetch_progress", {"percent": percent})

        ticker_thread = threading.Thread(target=ticker, daemon=True)
        ticker_thread.start()
        try:
            # Fetching before the runtime lands would silently cap the quality
            # list at 360p, so wait for the startup install to finish rather
            # than show a ladder the video doesn't actually have.
            self.ensure_js_runtime()
            info = downloader.get_video_info(url)
            self._push("video_fetch_progress", {"percent": 100})
            return {"ok": True, "data": info}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc, url)}
        finally:
            stop_ticker.set()
            ticker_thread.join(timeout=1)

    def _friendly_error(self, exc: Exception, url: str = "") -> str:
        message = str(exc)
        lowered = message.lower()
        if isinstance(exc, downloader.QualityCheckFailed):
            return message
        if isinstance(exc, downloader.NoVideoFound) or "unsupported url" in lowered:
            return "Aucune vidéo téléchargeable n'a été trouvée sur cette page. Vérifiez qu'il s'agit bien du lien d'une vidéo."
        if "drm" in lowered:
            return "Cette vidéo est protégée contre la copie (DRM) : elle ne peut pas être téléchargée."
        if "not available in your country" in lowered or "geo restrict" in lowered or "from your location" in lowered:
            return "Cette vidéo n'est pas disponible depuis votre pays."
        if "is not a valid url" in lowered or "getaddrinfo" in lowered or "name or service not known" in lowered:
            return "Ce site est introuvable. Vérifiez le lien et votre connexion internet."
        if "http error 404" in lowered:
            return "Cette page n'existe pas (ou plus). Vérifiez le lien."
        if "private" in lowered:
            return "Cette vidéo est privée : elle n'est accessible qu'à son propriétaire."
        if not YOUTUBE_URL_RE.match(url) and ("login" in lowered or "log in" in lowered or "--cookies" in lowered):
            return ("Cette vidéo nécessite d'être connecté au site. Ouvrez-la dans votre navigateur en étant "
                    "connecté, puis réessayez.")
        # These all mean the same thing to the user: no usable session, which
        # only the browser extension can supply.
        if YOUTUBE_URL_RE.match(url) and (
            downloader.is_decrypt_blocked_error(message)
            or downloader.is_bot_check_error(message)
            or downloader.is_cookie_extraction_error(message)
        ):
            return (
                "Cette vidéo nécessite d'être connecté à YouTube. Installez l'extension "
                "navigateur (Paramètres → Extension) et ouvrez YouTube en étant connecté : "
                "elle transmet votre session automatiquement, puis réessayez."
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

    # ---- javascript runtime (YouTube quality) --------------------------------
    def get_js_runtime_status(self):
        return {"installed": js_runtime.is_installed()}

    def ensure_js_runtime(self):
        """Downloads the JS runtime if missing, and makes sure its PO token
        server is running. Without it YouTube only offers 360p and below, so
        this runs on startup rather than on request."""
        if js_runtime.is_installed():
            js_runtime.ensure_server_running()
            return {"ok": True, "installed": True}

        def on_progress(stage, percent):
            self._push("js_runtime_progress", {"stage": stage, "percent": percent})

        try:
            js_runtime.install(on_progress)
            js_runtime.ensure_server_running()
            self._push("js_runtime_ready", {})
            return {"ok": True, "installed": True}
        except Exception as exc:
            self._push("js_runtime_error", {"error": str(exc)})
            return {"ok": False, "error": str(exc)}

    def start_js_runtime_install(self):
        threading.Thread(target=self.ensure_js_runtime, daemon=True).start()
        return {"started": True}

    # ---- download -------------------------------------------------------
    @staticmethod
    def _files_setup(settings=None) -> dict | None:
        setup = (settings or config.load_settings()).get("files_setup") or {}
        return setup if setup.get("enabled") and setup.get("root_dir") else None

    @staticmethod
    def _write_text_files(setup: dict, folder: Path, base_name: str, result: dict, url: str):
        """One .txt per checked field, or all of them in "<title>.txt" when
        combined. Setups saved before the per-field choice only had "text",
        which meant everything in one file."""
        if "text_title" in setup:
            wanted = [k for k in ("title", "description", "link") if setup.get(f"text_{k}")]
            combined = bool(setup.get("text_combined"))
        else:
            wanted = ["title", "description", "link"] if setup.get("text", True) else []
            combined = True
        values = {
            "title": result.get("title") or "",
            "description": result.get("description") or "",
            "link": result.get("webpage_url") or url,
        }
        if combined and len(wanted) > 1:
            text = "\n\n".join(values[k] for k in wanted) + "\n"
            (folder / f"{base_name}.txt").write_text(text, encoding="utf-8")
            return
        names = {"title": "Titre", "description": "Description", "link": "Lien"}
        for key in wanted:
            (folder / f"{names[key]}.txt").write_text(values[key] + "\n", encoding="utf-8")

    def check_output_exists(self, title: str, options: dict):
        """Whether a download under this title would collide with something
        already on disk -- the file itself, or with the files setup on, the
        per-video folder -- plus the first free "Title (n)" to fall back on."""
        setup = self._files_setup()

        def target(name):
            if setup:
                return Path(setup["root_dir"]) / name
            return downloader.predict_output_path(name, options)

        safe = sanitize_filename(title, restricted=False)
        path = target(safe)
        if not path.exists():
            return {"exists": False}
        n = 1
        while target(f"{safe} ({n})").exists():
            n += 1
        return {"exists": True, "filename": path.name, "numbered_name": f"{safe} ({n})"}

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
        settings = config.load_settings()
        chosen_dir = options.get("dest_dir")
        options = dict(options, embed_metadata=settings.get("embed_metadata", True))
        setup = self._files_setup(settings)
        base_name = options.get("custom_filename") or sanitize_filename(
            options.get("title") or "video", restricted=False
        )
        if setup:
            options.update(
                dest_dir=str(Path(setup["root_dir"]) / base_name),
                write_thumbnail=bool(setup.get("thumbnail")),
                skip_video=not setup.get("video", True),
            )
        try:
            # The token server may have died since the video was fetched;
            # without it mweb drops to 360p. A single /ping when it's up.
            js_runtime.ensure_server_running()
            ffmpeg_location = ffmpeg_manager.find_ffmpeg()
            opts = downloader.build_ydl_opts(options, ffmpeg_location)

            def on_progress(payload):
                self._push("download_progress", payload)

            result = downloader.download(
                url, opts, on_progress, cancel_event=cancel_event,
                cookies_browser_hint=options.get("cookies_browser_hint"),
                # An explicit fps cap can legitimately exclude the tallest
                # formats, so the height guarantee only applies on "auto".
                expected_height=(
                    options.get("expected_height")
                    if options.get("export_type") != "audio_only"
                    and options.get("fps") in (None, "auto")
                    else None
                ),
            )
            result["elapsed"] = round(time.monotonic() - started, 1)
            result["folder"] = options["dest_dir"]
            if setup:
                self._write_text_files(setup, Path(options["dest_dir"]), base_name, result, url)
            if setup and options.get("skip_video"):
                result["filepath"] = options["dest_dir"]
            total = settings.get("total_downloads", 0) + 1
            # The per-video setup folder is not the user's chosen download folder.
            config.save_settings({"last_download_dir": chosen_dir, "total_downloads": total})
            result["total_downloads"] = total
            # Opt-in convenience: never allowed to affect the download itself,
            # hence the always-false-on-error contract in clipboard.py.
            result["thumbnail_copied"] = bool(
                settings.get("copy_thumbnail")
                and clipboard.copy_image_from_url(options.get("thumbnail_url"))
            )
            self._push("download_complete", result)
        except DownloadCancelled:
            self._push("download_cancelled", {})
        except Exception as exc:
            self._push("download_error", {"error": self._friendly_error(exc, url)})

    def clear_cache(self):
        """Settings > "Vider le cache": stale player code or tokens can make
        YouTube serve a stripped quality list, and clearing both is the
        user-facing fix. Settings, sessions and downloads are untouched."""
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            ydl.cache.remove()
        js_runtime.invalidate_caches()
        return {"ok": True}

    # ---- publishing to YouTube ----------------------------------------------
    def get_publish_status(self):
        return youtube_publish.status()

    def connect_publish_channel(self):
        try:
            return {"ok": True, "channel": youtube_publish.connect()}
        except youtube_publish.PublishCancelled:
            return {"ok": False, "cancelled": True}
        except youtube_publish.PublishError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"La connexion a échoué : {exc}"}
        finally:
            # The consent page took the focus away: come back to the app.
            window_utils.focus_window(WINDOW_TITLE)

    def open_youtube_link(self, url: str):
        # Only ever YouTube pages: this must not become a way for page
        # content to launch arbitrary URLs or programs.
        if re.match(r"^https://(?:studio\.youtube\.com|(?:www\.)?youtube\.com|youtu\.be)/", url or ""):
            webbrowser.open(url)
            return True
        return False

    def cancel_publish_connect(self):
        youtube_publish.cancel_connect()
        return True

    def disconnect_publish_channel(self):
        youtube_publish.disconnect()
        return True

    def pick_publish_thumbnail(self):
        if not self.window:
            return None
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Images (*.jpg;*.jpeg;*.png;*.webp)",),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            preview = youtube_publish.prepare_thumbnail(Path(path).read_bytes())
        except Exception:
            return {"ok": False, "error": "Cette image n'a pas pu être lue."}
        return {"ok": True, "path": path,
                "preview": "data:image/jpeg;base64," + base64.b64encode(preview).decode("ascii")}

    def start_publish(self, payload: dict):
        self._publish_cancel = threading.Event()
        threading.Thread(target=self._run_publish, args=(payload, self._publish_cancel), daemon=True).start()
        return {"started": True}

    def cancel_publish(self):
        if getattr(self, "_publish_cancel", None) is not None:
            self._publish_cancel.set()
        return True

    @staticmethod
    def _publish_thumbnail_bytes(thumb: dict) -> bytes | None:
        kind = (thumb or {}).get("kind")
        if kind == "file":
            return youtube_publish.prepare_thumbnail(Path(thumb["path"]).read_bytes())
        if kind == "source" and thumb.get("url"):
            resp = requests.get(thumb["url"], timeout=30, headers={"User-Agent": "DownloaderYoutube"})
            resp.raise_for_status()
            return youtube_publish.prepare_thumbnail(resp.content)
        return None

    def _run_publish(self, payload, cancel_event):
        try:
            try:
                thumbnail = self._publish_thumbnail_bytes(payload.get("thumbnail"))
                thumb_error = None
            except Exception:
                thumbnail, thumb_error = None, "La miniature n'a pas pu être préparée : la vidéo a été envoyée sans."
            roller = downloader._RollingSpeed()
            last_push = [0.0]

            def on_progress(sent, total):
                now = time.monotonic()
                speed, eta = roller.update(sent, total)
                if now - last_push[0] < 0.2 and sent < total:
                    return
                last_push[0] = now
                self._push("publish_progress", {"sent": sent, "total": total, "speed": speed, "eta": eta})

            result = youtube_publish.upload(
                payload["filepath"], payload.get("title") or "", payload.get("description") or "",
                payload.get("privacy") or "private", payload.get("publish_at"),
                bool(payload.get("made_for_kids")), thumbnail, on_progress, cancel_event,
            )
            result["thumbnail_error"] = result["thumbnail_error"] or thumb_error
            self._push("publish_complete", result)
        except youtube_publish.PublishCancelled:
            self._push("publish_cancelled", {})
        except youtube_publish.PublishError as exc:
            self._push("publish_error", {"error": str(exc)})
        except Exception as exc:
            self._push("publish_error", {"error": f"La publication a échoué : {exc}"})

    # ---- browser extension ------------------------------------------------
    def get_extension_status(self):
        settings = config.load_settings()
        return {"paired": bool(settings.get("paired"))}

    def list_browsers(self):
        return browsers.detect_browsers()

    def install_extension(self, browser_id: str):
        return extension_installer.install_extension(browser_id)

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
        # One update at a time, ever. Two overlapping runs each spawn their own
        # detached copy script, and those used to race over the same temp
        # files -- which is how an install could end up being mirrored from an
        # already-cleaned-up source and deleted entirely.
        with self._update_lock:
            if self._updating:
                return {"started": False, "reason": "already_running"}
            self._updating = True
        threading.Thread(target=self._run_update, args=(update_info,), daemon=True).start()
        return {"started": True}

    def _run_update(self, update_info: dict):
        try:
            def on_progress(percent):
                self._push("update_progress", {"percent": percent})
                if percent == 100:
                    self._push("update_installing", {})

            updater.apply_update_and_restart(update_info, on_progress)
            time.sleep(0.5)
            if self.window:
                self.window.destroy()
        except Exception as exc:
            # Only released on failure: on success the app is about to be
            # replaced and restarted, and nothing should be able to start a
            # second copy script in the meantime.
            with self._update_lock:
                self._updating = False
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

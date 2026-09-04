"""Thin wrapper around yt_dlp: fetch metadata, build options, run downloads."""
import base64
import glob
import os
import time
from collections import deque
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled, sanitize_filename

from . import cookie_store, js_runtime
# Registers the bgutil PO token HTTP provider with yt-dlp. Vendored (not a
# real plugin install) because yt-dlp's own plugin discovery doesn't work
# once frozen -- see backend/vendor_pot_provider/__init__.py for why.
from .vendor_pot_provider import getpot_bgutil_http  # noqa: F401

QUALITY_TIERS = {
    "auto": {"height": None, "label": "Auto", "recommended_kbps": None},
    "144p": {"height": 144, "label": "144p", "recommended_kbps": 200},
    "480p": {"height": 480, "label": "480p", "recommended_kbps": 1000},
    "720p": {"height": 720, "label": "720p", "recommended_kbps": 2500},
    "1080p": {"height": 1080, "label": "1080p", "recommended_kbps": 5000},
    "1440p": {"height": 1440, "label": "2K", "recommended_kbps": 10000},
    "2160p": {"height": 2160, "label": "4K", "recommended_kbps": 20000},
}

FPS_CHOICES = [10, 24, 50, 60]
RECOMMENDED_AUDIO_KBPS = 192
CONCURRENT_FRAGMENTS = 16
ROLLING_WINDOW_SECONDS = 5

VIDEO_CONTAINERS = ["mp4", "mkv", "webm"]
AUDIO_FORMATS = ["mp3", "m4a", "wav", "opus"]

# Player clients that avoid YouTube's bot-check for most public videos without any cookies.
# mweb goes first: with a PO token (see js_runtime) it exposes the full ladder up to
# 4K, while web_safari stays as the fallback that still reaches 1080p without one.
DEFAULT_PLAYER_CLIENTS = ["mweb", "web_safari", "tv"]

# Browsers to try automatically (in order) when a video does require real authentication.
# Chrome is tried last: its App-Bound Encryption (since Chrome 127) frequently blocks
# yt-dlp's cookie decryption on Windows even when Chrome is fully closed.
AUTO_COOKIE_ORDER = ["edge", "firefox", "brave", "vivaldi", "opera", "chromium", "chrome"]

_STORYBOARD_TARGET_WIDTH = 320


def is_bot_check_error(message: str) -> bool:
    return "sign in to confirm" in (message or "").lower()


def is_cookie_extraction_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        needle in lowered
        for needle in ("could not copy", "failed to decrypt", "could not find", "cookie database")
    )


def is_decrypt_blocked_error(message: str) -> bool:
    """True when the browser's cookie file was read fine but couldn't be decrypted —
    e.g. Chrome/Edge App-Bound Encryption. Closing the browser again won't help."""
    return "failed to decrypt" in (message or "").lower()


def needs_signed_in_retry(message: str) -> bool:
    """True when an anonymous attempt failed in a way a signed-in session fixes.

    YouTube doesn't only answer "sign in to confirm you're not a bot" any more.
    For some videos it silently withholds the real stream URLs from an
    anonymous client -- the extraction still "succeeds" but the media fetch
    then returns 403, or the only surviving format is the legacy muxed 360p
    one, or the client is pushed onto SABR streaming and the formats come back
    with no URL at all. Measured on a real video: every player client failed
    anonymously, and every one of them succeeded with the session cookies.
    """
    lowered = (message or "").lower()
    return (
        is_bot_check_error(lowered)
        or "http error 403" in lowered
        or "requested format is not available" in lowered
        or "only images are available" in lowered
        or "downloaded file is empty" in lowered
        or "the page needs to be reloaded" in lowered
    )


# Legacy progressive itags: the ones YouTube still hands an anonymous client
# when it withholds the adaptive (real quality) ladder.
_MUXED_FALLBACK_ITAGS = {"18", "22"}


def has_full_quality_ladder(info: dict) -> bool:
    """False when extraction came back stripped down to the legacy muxed
    format(s) only -- i.e. the adaptive ladder was withheld. Retrying such a
    result with cookies is what gets the real qualities back, instead of
    quietly offering the user 360p for a 1080p video."""
    video_formats = [
        f for f in (info.get("formats") or [])
        if f.get("vcodec") not in (None, "none")
    ]
    if not video_formats:
        return False
    return any(str(f.get("format_id")) not in _MUXED_FALLBACK_ITAGS for f in video_formats)


def _cookies_opts(browser: str | None) -> dict:
    return {"cookiesfrombrowser": (browser,)} if browser else {}


def _with_auto_cookies(make_opts, run, hint: str | None = None, cookies_file: str | None = None,
                       accept=None):
    """Runs `run(make_opts(cookie_extra))`, retrying with cookies when an anonymous
    attempt fails (or, via `accept`, succeeds but comes back degraded). Priority: an
    explicitly passed cookies.txt, then `hint` (a browser already known to work), then
    no cookies at all, then the cookies the browser extension synced, then every
    supported browser in turn. Returns (result, source_used) where source_used is
    'file', a browser name, or None."""
    order = []
    if cookies_file:
        order.append(("file", cookies_file))
    if hint:
        order.append(("browser", hint))
    order.append(("none", None))
    # Tried before any browser extraction: these came from the extension via the
    # browser's own cookie API, so they work even on Chrome/Edge builds whose
    # App-Bound Encryption makes direct extraction impossible. Deliberately
    # *after* ("none", None) so ordinary videos never send session cookies at all.
    synced = cookie_store.path_if_present()
    if synced and synced != cookies_file:
        order.append(("file", synced))
    order += [("browser", b) for b in AUTO_COOKIE_ORDER if b != hint]

    last_exc = None
    rejected = None  # a result that worked but came back degraded
    for kind, value in order:
        if kind == "file":
            extra = {"cookiefile": value}
        elif kind == "browser":
            extra = _cookies_opts(value)
        else:
            extra = {}
        opts = make_opts(extra)
        try:
            result = run(opts)
        except Exception as exc:
            last_exc = exc
            if kind == "none" and not needs_signed_in_retry(str(exc)):
                raise
            continue

        source = value if kind != "none" else None
        if accept is None or accept(result):
            return result, source
        # Worked, but the caller says it's not good enough (e.g. the quality
        # ladder was withheld). Keep it as a fallback and try a signed-in
        # source -- never fail outright over it.
        if rejected is None:
            rejected = (result, source)

    if rejected is not None:
        return rejected
    raise last_exc


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": DEFAULT_PLAYER_CLIENTS}},
    }
    runtime = js_runtime.ydl_opts()
    opts["extractor_args"].update(runtime.pop("extractor_args", {}))
    opts.update(runtime)
    return opts


def _pick_storyboard(formats: list) -> dict | None:
    candidates = [f for f in formats if f.get("format_note") == "storyboard" and f.get("fragments")]
    if not candidates:
        return None
    best = min(candidates, key=lambda f: abs((f.get("width") or 0) - _STORYBOARD_TARGET_WIDTH))
    return {
        "fragments": [{"url": fr["url"], "duration": fr.get("duration") or 0} for fr in best["fragments"]],
        "rows": best.get("rows") or 1,
        "columns": best.get("columns") or 1,
        "width": best.get("width") or 160,
        "height": best.get("height") or 90,
        "fps": best.get("fps") or 1,
    }


def get_video_info(url: str, cookies_file: str | None = None) -> dict:
    def make_opts(cookie_extra):
        opts = {**_base_opts(), "noplaylist": True, "skip_download": True}
        opts.update(cookie_extra)
        return opts

    def run(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    info, cookies_browser_used = _with_auto_cookies(
        make_opts, run, cookies_file=cookies_file, accept=has_full_quality_ladder,
    )

    formats = info.get("formats") or []
    video_formats = [f for f in formats if f.get("vcodec") not in (None, "none")]

    heights = {f.get("height") for f in video_formats if f.get("height")}
    if not heights and info.get("height"):
        heights = {info["height"]}

    fps_values = {round(f["fps"]) for f in video_formats if f.get("fps")}

    audio_abrs = [f.get("abr") for f in formats if f.get("acodec") not in (None, "none") and f.get("abr")]
    best_audio_size = max(
        (f.get("filesize") or f.get("filesize_approx") or 0 for f in formats if f.get("acodec") not in (None, "none")),
        default=0,
    )

    size_by_height = {}
    for h in heights:
        candidates = [
            (f.get("filesize") or f.get("filesize_approx") or 0)
            for f in video_formats
            if f.get("height") == h
        ]
        if candidates:
            size_by_height[h] = max(candidates) + best_audio_size

    thumbnail = info.get("thumbnail")
    if not thumbnail and info.get("thumbnails"):
        thumbnail = sorted(info["thumbnails"], key=lambda t: t.get("width") or 0)[-1].get("url")

    return {
        "title": info.get("title") or "Vidéo sans titre",
        "thumbnail": thumbnail,
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "webpage_url": info.get("webpage_url") or url,
        "available_heights": sorted(heights),
        "available_fps": sorted(fps_values),
        "max_fps": max(fps_values) if fps_values else None,
        "max_audio_kbps": round(max(audio_abrs)) if audio_abrs else None,
        "best_audio_size": best_audio_size or None,
        "size_by_height": {str(k): v for k, v in size_by_height.items()},
        "storyboard": _pick_storyboard(formats),
        "cookies_browser_used": cookies_browser_used,
    }


def fetch_storyboard_sprite(url: str) -> str:
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.urlopen(url).read()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _needs_reencode(bitrate_kbps: int, recommended_kbps: int | None) -> bool:
    if not recommended_kbps:
        return False
    return abs(bitrate_kbps - recommended_kbps) / recommended_kbps > 0.15


def _target_extension(options: dict) -> str:
    """Mirrors the extension build_ydl_opts ends up producing, without
    actually building the full opts dict -- used to predict the output
    filename before downloading (see predict_output_path)."""
    output_format = options.get("output_format")
    if options["export_type"] == "audio_only":
        return output_format if output_format in AUDIO_FORMATS else "mp3"
    return output_format if output_format in VIDEO_CONTAINERS else "mp4"


def predict_output_path(title: str, options: dict) -> Path:
    """Predicts the exact file build_ydl_opts' "%(title)s.%(ext)s" template
    (restrictfilenames=False) will produce, so the app can check for an
    existing file *before* starting a real download. Always accurate for
    this app's own UI, which always sends an explicit output_format --
    reusing yt-dlp's own sanitizer keeps it byte-for-byte consistent with
    what a real download would actually write."""
    safe_title = sanitize_filename(title, restricted=False)
    ext = _target_extension(options)
    return Path(options["dest_dir"]) / f"{safe_title}.{ext}"


def build_ydl_opts(options: dict, ffmpeg_location: str | None) -> dict:
    export_type = options["export_type"]  # 'video_audio' | 'audio_only' | 'video_only'
    quality = options["quality"]
    bitrate = int(options["bitrate"])
    fps = options.get("fps", "auto")
    dest_dir = options["dest_dir"]
    output_format = options.get("output_format")

    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    opts: dict = {
        **_base_opts(),
        "noplaylist": True,
        "paths": {"home": dest_dir},
        "outtmpl": {"default": "%(title)s.%(ext)s"},
        "restrictfilenames": False,
        "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
        "retries": 10,
        "fragment_retries": 10,
    }
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location
    # Set when the user resolved a "file already exists" prompt: explicitly
    # overwrite, or save under a different name instead of the video's title.
    if options.get("overwrite"):
        opts["overwrites"] = True
    custom_filename = options.get("custom_filename")
    if custom_filename:
        opts["outtmpl"] = {"default": f"{custom_filename.replace('%', '%%')}.%(ext)s"}

    fps_filter = "" if fps in (None, "auto") else f"[fps<={int(fps)}]"

    if export_type == "audio_only":
        codec = output_format if output_format in AUDIO_FORMATS else "mp3"
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": str(bitrate)}
        ]
        return opts

    container = output_format if output_format in VIDEO_CONTAINERS else "mp4"
    tier = QUALITY_TIERS[quality]
    height = tier["height"]
    height_filter = "" if height is None else f"[height<={height}]"
    reencode = _needs_reencode(bitrate, tier["recommended_kbps"])

    # MP4 is the format people pick specifically to open elsewhere (video
    # editors, older devices) -- but YouTube only offers H.264 up to 1080p;
    # above that (and often at 1080p too) "best" silently means VP9 or AV1
    # muxed into an .mp4 container, which plays fine in a browser or VLC but
    # many NLEs (Premiere Pro included) reject outright as "unsupported
    # compression" since the container name promises H.264 they can decode.
    # Preferring avc1/mp4a first, with the unfiltered format as a fallback
    # for cases where YouTube doesn't offer H.264 at all, keeps the common
    # case genuinely compatible without breaking playback when it can't be.
    codec_filter = "[vcodec^=avc1]" if container == "mp4" else ""
    audio_codec_filter = "[acodec^=mp4a]" if container == "mp4" else ""

    # A trailing unfiltered "best" catches sites like TikTok, where a portrait
    # video's *width* is its short side -- yt-dlp still reports "height" as
    # the long side, so a height<=X tier filter can exclude every available
    # format and fail outright instead of just settling for what exists.
    if export_type == "video_only":
        opts["format"] = (
            f"bestvideo{codec_filter}{height_filter}{fps_filter}/"
            f"bestvideo{height_filter}{fps_filter}/best{height_filter}{fps_filter}/best"
        )
        if reencode or output_format:
            opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": container}]
    else:  # video_audio
        opts["format"] = (
            f"bestvideo{codec_filter}{height_filter}{fps_filter}+bestaudio{audio_codec_filter}/"
            f"bestvideo{height_filter}{fps_filter}+bestaudio/best{height_filter}{fps_filter}/best"
        )
        opts["merge_output_format"] = container

    if reencode:
        opts.setdefault("postprocessors", [{"key": "FFmpegVideoConvertor", "preferedformat": container}])
        opts["postprocessor_args"] = {"default": ["-b:v", f"{bitrate}k"]}

    return opts


class _RollingSpeed:
    """Smooths speed/eta over a trailing time window instead of yt-dlp's instantaneous value."""

    def __init__(self, window_seconds=ROLLING_WINDOW_SECONDS):
        self.window = window_seconds
        self.samples = deque()

    def update(self, downloaded_bytes, total_bytes):
        now = time.monotonic()
        if self.samples and downloaded_bytes < self.samples[-1][1]:
            self.samples.clear()
        self.samples.append((now, downloaded_bytes))
        while len(self.samples) > 1 and now - self.samples[0][0] > self.window:
            self.samples.popleft()

        if len(self.samples) < 2:
            return None, None

        dt = self.samples[-1][0] - self.samples[0][0]
        db = self.samples[-1][1] - self.samples[0][1]
        if dt <= 0 or db <= 0:
            return None, None

        speed = db / dt
        eta = (total_bytes - downloaded_bytes) / speed if total_bytes else None
        return speed, eta


def download(
    url: str, ydl_opts: dict, on_progress, cancel_event=None,
    cookies_browser_hint: str | None = None, cookies_file: str | None = None,
) -> dict:
    roller = _RollingSpeed()
    last_tmpfile = {"path": None}

    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Téléchargement annulé par l'utilisateur.")

        if d.get("tmpfilename"):
            last_tmpfile["path"] = d["tmpfilename"]

        downloaded = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        speed, eta = (None, None)
        if d.get("status") == "downloading":
            speed, eta = roller.update(downloaded, total)

        on_progress(
            {
                "status": d.get("status"),
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "eta": eta if eta is not None else d.get("eta"),
                "speed": speed if speed is not None else d.get("speed"),
                "filename": os.path.basename(d.get("filename") or ""),
            }
        )

    def make_opts(cookie_extra):
        opts = dict(ydl_opts)
        opts.update(cookie_extra)
        opts["progress_hooks"] = [hook]
        return opts

    def run(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl, info, opts

    try:
        (ydl, info, used_opts), _browser = _with_auto_cookies(
            make_opts, run, hint=cookies_browser_hint, cookies_file=cookies_file,
        )
    except DownloadCancelled:
        _cleanup_partial_files(last_tmpfile["path"])
        raise

    final_path = None
    try:
        final_path = ydl.prepare_filename(info)
        target_ext = used_opts.get("merge_output_format")
        if target_ext:
            root, _ = os.path.splitext(final_path)
            merged = f"{root}.{target_ext}"
            if os.path.exists(merged):
                final_path = merged
    except Exception:
        final_path = None

    return {"title": info.get("title"), "filepath": final_path}


def _cleanup_partial_files(tmpfilename):
    if not tmpfilename:
        return
    stem = os.path.splitext(tmpfilename)[0]
    candidates = {tmpfilename, f"{tmpfilename}.part", f"{tmpfilename}.ytdl"}
    candidates.update(glob.glob(f"{stem}*.part"))
    candidates.update(glob.glob(f"{stem}*.ytdl"))
    candidates.update(glob.glob(f"{stem}*.temp.*"))
    for path in candidates:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

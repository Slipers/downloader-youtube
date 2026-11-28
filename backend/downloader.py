"""Thin wrapper around yt_dlp: fetch metadata, build options, run downloads."""
import base64
import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled, ThrottledDownload, sanitize_filename

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

# YouTube throttles a single long-lived connection after an initial burst, so
# fetching the stream as a series of ranged requests keeps it in that faster
# opening window instead. Measured over fresh (non-CDN-cached) videos, this
# roughly doubled the median throughput -- though the spread between videos is
# far larger than the effect, because the real ceiling is YouTube's own
# per-video throttling rather than the connection.
# The size matters: 5MB measured *worse* than no chunking (per-request
# overhead) and 64MB lost the benefit again, so this sits in the middle of the
# band that measured well.
HTTP_CHUNK_SIZE = 10 * 1024 * 1024

# Fresh extractions tried before accepting a lower quality than requested.
DEGRADED_SELECTION_ATTEMPTS = 3

# Below this for 3 s (yt-dlp's own window) a stream counts as throttled:
# YouTube serves a penalized session at ~50-150 KB/s.
THROTTLED_BYTES_PER_SEC = 256 * 1024
# Fresh links fetched for a throttled stream before letting it run as is.
THROTTLE_RETRIES = 3

VIDEO_CONTAINERS = ["mp4", "mkv", "webm"]
AUDIO_FORMATS = ["mp3", "m4a", "wav", "opus"]

# Player clients that avoid YouTube's bot-check for most public videos without any cookies.
# mweb goes first: with a PO token (see js_runtime) it exposes the full ladder up to
# 4K -- but without one (token server not up, or crashed) it gets 360p at most.
# "default" is yt-dlp's own current pick (visionos as of Oct 2026), measured to
# list *and serve* the full ladder with no token at all, so a dead token server
# no longer means a 144p download. web_safari and tv returned nothing by then.
DEFAULT_PLAYER_CLIENTS = ["mweb", "default"]

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
        # yt-dlp's login-required errors on any site: the user's browser
        # session may well be signed in there.
        or "--cookies" in lowered
    )


_VIMEO_PAGE_RE = re.compile(r"^https?://(?:www\.)?vimeo\.com/(\d+)(?:/([0-9a-f]+))?/?(?:[?#].*)?$")


def normalize_url(url: str) -> str:
    """yt-dlp's vimeo.com page client now insists on a login, while the
    player URL of the same public video still works anonymously."""
    match = _VIMEO_PAGE_RE.match(url)
    if match:
        video_id, unlisted_hash = match.groups()
        return f"https://player.vimeo.com/video/{video_id}" + (f"?h={unlisted_hash}" if unlisted_hash else "")
    return url


# Legacy progressive itags: the ones YouTube still hands an anonymous client
# when it withholds the adaptive (real quality) ladder.
_MUXED_FALLBACK_ITAGS = {"18", "22"}


# A YouTube ladder topping out below this is far more likely withheld than
# real. Genuinely low-res uploads exist (old ones), but YouTube's stripped
# responses are what users actually hit -- and those can keep a few low
# adaptive formats (144p, 240p), not only the legacy muxed one.
_SUSPICIOUSLY_LOW_HEIGHT = 480


def _res(f: dict) -> int:
    """A format's quality the way YouTube labels it: its short side, so a
    1080x1920 Short is "1080p", not 1920p. Same rule as yt-dlp's `res`."""
    width, height = f.get("width"), f.get("height")
    return min(width, height) if width and height else (height or 0)


def _max_video_height(info: dict) -> int:
    return max(
        (_res(f) for f in (info.get("formats") or []) if f.get("vcodec") not in (None, "none")),
        default=0,
    )


def has_full_quality_ladder(info: dict) -> bool:
    """False when extraction came back with the quality ladder withheld:
    either only the legacy muxed format(s) survived, or (YouTube) nothing at
    or above 480p did. Retrying such a result is what gets the real qualities
    back, instead of quietly offering the user 144p for a 1080p video."""
    video_formats = [
        f for f in (info.get("formats") or [])
        if f.get("vcodec") not in (None, "none")
    ]
    # Only YouTube withholds its ladder. Anywhere else (audio-only sites, generic
    # pages whose codecs are unknown) a "no video format" answer is the real
    # one, and retrying it would run the whole cookie cascade three times over.
    if info.get("extractor_key") != "Youtube":
        return True
    if not video_formats:
        return False
    if all(str(f.get("format_id")) in _MUXED_FALLBACK_ITAGS for f in video_formats):
        return False
    return _max_video_height(info) >= _SUSPICIOUSLY_LOW_HEIGHT


class DegradedSelection(Exception):
    """The format the download was about to fetch falls short of what the user
    picked, because this particular extraction came back with a stripped-down
    ladder. Raised *before* any bytes are downloaded, so the attempt can be
    retried (fresh extraction, or with the session) instead of quietly saving
    a lower quality than the one chosen on the settings screen."""


def _selected_video_height(info: dict) -> int | None:
    for f in info.get("requested_formats") or [info]:
        if f.get("vcodec") not in (None, "none") and _res(f):
            return _res(f)
    return None


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
    degraded = None  # the real reason, when sources merely came back short
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
        except (DownloadCancelled, ThrottledDownload):
            # The user pressed stop: never carry on to the next cookie source.
            # A throttled stream isn't a cookie problem either: the caller
            # fetches fresh links with the same source.
            raise
        except Exception as exc:
            last_exc = exc
            if isinstance(exc, DegradedSelection):
                degraded = exc
            retryable = isinstance(exc, DegradedSelection) or needs_signed_in_retry(str(exc))
            if kind == "none" and not retryable:
                raise
            continue

        source = value if kind != "none" else None
        if accept is None or accept(result):
            return result, source
        # Worked, but the caller says it's not good enough (e.g. the quality
        # ladder was withheld). Keep the best such result as a fallback and try
        # a signed-in source -- never fail outright over it. (`accept` is only
        # ever used with info dicts, hence the height comparison.)
        if rejected is None or _max_video_height(result) > _max_video_height(rejected[0]):
            rejected = (result, source)

    if rejected is not None:
        return rejected
    # A browser whose cookies can't be read (the usual end of the cascade)
    # must not mask a selection that was only too low: the caller retries
    # those and finally settles, instead of failing on a cookie error.
    raise degraded or last_exc


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        # A page with several videos (generic pages, multi-video posts) comes
        # back as a playlist: only ever take the first one.
        "playlist_items": "1",
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


class NoVideoFound(Exception):
    """The page was read fine but holds nothing downloadable."""


class QualityCheckFailed(Exception):
    """The finished file is below the quality that was targeted. Its message
    is shown to the user as is."""


# The target comes from yt-dlp's real pixel heights (a letterboxed "1080p"
# is 804 on both sides); the margin only absorbs small encoder differences.
_QUALITY_TOLERANCE = 0.9


def _probe_height(path: str | None, ffmpeg_location: str | None) -> int | None:
    """The quality actually encoded in the file (its short side, see _res),
    read by ffprobe -- not what yt-dlp announced. None when it can't be
    measured (no ffprobe, no video)."""
    if not path or not os.path.isfile(path):
        return None
    ffprobe = str(Path(ffmpeg_location, "ffprobe.exe")) if ffmpeg_location else "ffprobe"
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        return min(int(v) for v in out.splitlines()[0].split(",")[:2]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _first_entry(info: dict) -> dict:
    if info.get("_type") != "playlist":
        return info
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        raise NoVideoFound("no entries")
    return entries[0]


def get_video_info(url: str, cookies_file: str | None = None) -> dict:
    url = normalize_url(url)
    def make_opts(cookie_extra):
        opts = {**_base_opts(), "noplaylist": True, "skip_download": True}
        opts.update(cookie_extra)
        return opts

    def run(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return _first_entry(ydl.extract_info(url, download=False))

    # A fresh extraction usually gets the full ladder back, so a few rounds
    # before settling for the best one seen.
    best = None
    for _ in range(DEGRADED_SELECTION_ATTEMPTS):
        info, source = _with_auto_cookies(
            make_opts, run, cookies_file=cookies_file, accept=has_full_quality_ladder,
        )
        if has_full_quality_ladder(info):
            best = (info, source)
            break
        if best is None or _max_video_height(info) > _max_video_height(best[0]):
            best = (info, source)
    info, cookies_browser_used = best

    formats = info.get("formats") or []
    video_formats = [f for f in formats if f.get("vcodec") not in (None, "none")]

    heights = {_res(f) for f in video_formats if _res(f)}
    if not heights and _res(info):
        heights = {_res(info)}

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
            if _res(f) == h
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
        # Still withheld after every retry: the settings screen says so, so a
        # 144p-only list is never mistaken for the video's real quality.
        "ladder_incomplete": not has_full_quality_ladder(info),
        "audio_only": bool(formats) and all(f.get("vcodec") == "none" for f in formats),
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
        "http_chunk_size": HTTP_CHUNK_SIZE,
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
        return _add_extras(opts, options)

    container = output_format if output_format in VIDEO_CONTAINERS else "mp4"
    tier = QUALITY_TIERS[quality]
    height = tier["height"]
    reencode = _needs_reencode(bitrate, tier["recommended_kbps"])

    # MP4 is the format people pick specifically to open elsewhere (video
    # editors, older devices), and many NLEs (Premiere Pro included) reject
    # VP9/AV1 muxed into an .mp4 as "unsupported compression". So H.264/AAC is
    # preferred -- but only as a *tie-breaker* between formats of the same
    # resolution and frame rate. It used to be a hard first choice in the
    # format string, and since YouTube offers no H.264 above 1080p, asking for
    # 2K or 4K in MP4 silently delivered 1080p. The quality the user picked
    # wins; codec compatibility only decides between equals.
    #
    # The tier itself is a sort, not a filter: "res:1080" takes the best
    # format whose *short side* is at most 1080 (else the closest above).
    # A height<=1080 filter read portrait videos by their long side, so a
    # 1080x1920 Short asked in 2K came out 720x1280, and on some sites it
    # could exclude every format.
    opts["format_sort"] = [f"res:{height}" if height else "res", "fps"]
    if container == "mp4":
        opts["format_sort"] += ["vcodec:h264", "acodec:aac"]

    if export_type == "video_only":
        opts["format"] = f"bestvideo{fps_filter}/best{fps_filter}/best"
        if reencode or output_format:
            opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": container}]
    else:  # video_audio
        opts["format"] = f"bestvideo{fps_filter}+bestaudio/best{fps_filter}/best"
        opts["merge_output_format"] = container

    if reencode:
        opts.setdefault("postprocessors", [{"key": "FFmpegVideoConvertor", "preferedformat": container}])
        # Scoped to the converter: under "default" it would also reach the
        # metadata pass below, which only stream-copies.
        opts["postprocessor_args"] = {"videoconvertor": ["-b:v", f"{bitrate}k"]}

    return _add_extras(opts, options)


def _add_extras(opts: dict, options: dict) -> dict:
    """Optional outputs shared by every export type. Appended last so the
    metadata pass runs after any conversion step has produced the final file."""
    if options.get("write_thumbnail"):
        opts["writethumbnail"] = True
        opts.setdefault("postprocessors", []).append(
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}
        )
    if options.get("embed_metadata"):
        # Title, description, upload date, uploader and source URL.
        opts.setdefault("postprocessors", []).append({"key": "FFmpegMetadata", "add_metadata": True})
    if options.get("skip_video"):
        opts["skip_download"] = True
    return opts


# ---------- cutting ----------

# Shorter pieces than this are dropped: a stray click, not a passage.
_CUT_MIN_SECONDS = 0.1


class CutFailed(Exception):
    """ffmpeg couldn't cut the downloaded file; `message` is user-facing."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def cut_settings(options: dict) -> dict | None:
    """The cut the user asked for, with what re-encoding it needs, or None
    for the whole video. `ranges` are [start, end] in seconds; "keep" keeps
    only them (joined in order), "remove" keeps everything else."""
    cut = options.get("cut") or {}
    if cut.get("mode") not in ("keep", "remove") or not cut.get("ranges"):
        return None
    export_type = options.get("export_type")
    bitrate = int(options.get("bitrate") or 0)
    video_bitrate = None
    if export_type != "audio_only":
        tier = QUALITY_TIERS.get(options.get("quality"), QUALITY_TIERS["auto"])
        if _needs_reencode(bitrate, tier["recommended_kbps"]):
            video_bitrate = bitrate
    return {
        "mode": cut["mode"],
        "ranges": [[float(a), float(b)] for a, b in cut["ranges"]],
        "audio_bitrate": bitrate if export_type == "audio_only" and bitrate else RECOMMENDED_AUDIO_KBPS,
        "video_bitrate": video_bitrate,
    }


def segments_to_keep(mode: str, ranges, duration: float) -> list[tuple[float, float]] | None:
    """Turns the user's ranges into the ordered pieces to keep, clamped to
    the video and with overlaps merged. None means "the whole video" (nothing
    to cut); an empty selection is an error, not a silent full download."""
    clean = []
    for a, b in ranges:
        a, b = max(0.0, float(a)), min(float(duration), float(b))
        if b - a >= _CUT_MIN_SECONDS:
            clean.append([a, b])
    clean.sort()
    merged = []
    for a, b in clean:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if mode == "keep":
        keep = merged
    else:
        keep, cursor = [], 0.0
        for a, b in merged:
            if a - cursor >= _CUT_MIN_SECONDS:
                keep.append([cursor, a])
            cursor = b
        if duration - cursor >= _CUT_MIN_SECONDS:
            keep.append([cursor, float(duration)])
    if not keep:
        raise CutFailed("Le découpage ne laisse rien de la vidéo : vérifiez les passages choisis.")
    if len(keep) == 1 and keep[0][0] < _CUT_MIN_SECONDS and duration - keep[0][1] < _CUT_MIN_SECONDS:
        return None
    return [(a, b) for a, b in keep]


def _probe_streams(ffprobe: str, path: str) -> tuple[set, float | None]:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type:stream_disposition=attached_pic:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout
    data = json.loads(out or "{}")
    kinds = {
        s.get("codec_type") for s in data.get("streams", [])
        # A cover picture in an .mp3/.m4a is a "video" stream, not a video.
        if not (s.get("disposition") or {}).get("attached_pic")
    }
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return kinds, duration


def _encoder_args(ext: str, has_video: bool, has_audio: bool, cut: dict) -> list[str]:
    args = []
    if has_video:
        vb = cut.get("video_bitrate")
        if ext == "webm":
            args += ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1"]
            args += ["-b:v", f"{vb}k"] if vb else ["-crf", "31", "-b:v", "0"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
            args += ["-b:v", f"{vb}k"] if vb else ["-crf", "18"]
    if has_audio:
        ab = f"{cut.get('audio_bitrate') or RECOMMENDED_AUDIO_KBPS}k"
        if ext == "wav":
            args += ["-c:a", "pcm_s16le"]
        elif ext in ("webm", "opus", "ogg"):
            args += ["-c:a", "libopus", "-b:a", ab]
        elif ext == "mp3":
            args += ["-c:a", "libmp3lame", "-b:a", ab]
        else:
            args += ["-c:a", "aac", "-b:a", ab]
    if ext in ("mp4", "m4a"):
        args += ["-movflags", "+faststart"]
    return args


def _cut_file(path: str, cut: dict, duration: float | None, ffmpeg_location: str | None,
              on_progress, cancel_event=None) -> float | None:
    """Keeps only the chosen pieces of the downloaded file, in place.
    Each piece is its own input seeked with -ss (fast, then decoded from the
    keyframe before it, so the cut is frame-exact) and the pieces are joined
    with the concat filter: one re-encode, no keyframe-aligned jumps. Returns
    the new duration, or None when there was nothing to cut."""
    ffmpeg = str(Path(ffmpeg_location, "ffmpeg.exe")) if ffmpeg_location else "ffmpeg"
    ffprobe = str(Path(ffmpeg_location, "ffprobe.exe")) if ffmpeg_location else "ffprobe"
    kinds, real_duration = _probe_streams(ffprobe, path)
    duration = real_duration or duration
    if not duration:
        raise CutFailed("Impossible de découper cette vidéo : sa durée est inconnue.")
    keep = segments_to_keep(cut["mode"], cut["ranges"], duration)
    if keep is None:
        return None

    root, ext = os.path.splitext(path)
    ext = ext.lstrip(".").lower()
    has_video = "video" in kinds and ext not in AUDIO_FORMATS
    has_audio = "audio" in kinds
    if not (has_video or has_audio):
        raise CutFailed("Impossible de découper ce fichier : aucune piste audio ou vidéo trouvée.")
    tmp = f"{root}.cut-temp.{ext}"

    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    for a, b in keep:
        cmd += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", path]
    graph, labels = [], ""
    for i in range(len(keep)):
        if has_video:
            graph.append(f"[{i}:v:0]setpts=PTS-STARTPTS[v{i}]")
            labels += f"[v{i}]"
        if has_audio:
            graph.append(f"[{i}:a:0]asetpts=PTS-STARTPTS[a{i}]")
            labels += f"[a{i}]"
    outs = ("[v]" if has_video else "") + ("[a]" if has_audio else "")
    graph.append(f"{labels}concat=n={len(keep)}:v={int(has_video)}:a={int(has_audio)}{outs}")
    cmd += ["-filter_complex", ";".join(graph)]
    if has_video:
        cmd += ["-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]"]
    # Title & co. carry over; chapters would point at the old timeline.
    cmd += ["-map_metadata", "0", "-map_chapters", "-1"]
    cmd += _encoder_args(ext, has_video, has_audio, cut)
    cmd += ["-progress", "pipe:1", "-nostats", tmp]

    total = sum(b - a for a, b in keep)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    errors = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    started = time.monotonic()
    cancelled = False
    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            key, _, value = line.strip().partition("=")
            if key != "out_time_us":
                continue
            try:
                done = max(0.0, int(value) / 1_000_000)
            except ValueError:
                continue
            frac = min(1.0, done / total) if total else 0.0
            elapsed = time.monotonic() - started
            on_progress({
                "status": "cutting",
                "progress": frac,
                "eta": elapsed / frac * (1 - frac) if frac > 0.02 else None,
            })
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=5)
    if cancelled or (cancel_event is not None and cancel_event.is_set()):
        _remove_quietly(tmp)
        raise DownloadCancelled("Téléchargement annulé par l'utilisateur.")
    if proc.returncode != 0 or not os.path.isfile(tmp):
        _remove_quietly(tmp)
        detail = (errors[0] if errors else "").strip().splitlines()
        raise CutFailed(
            "Le découpage de la vidéo a échoué."
            + (f" ({detail[-1][:160]})" if detail else "")
        )
    os.replace(tmp, path)
    return total


def _remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


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
    expected_height: int | None = None, cut: dict | None = None,
) -> dict:
    """`expected_height` is the height the settings screen promised for the
    user's choice (the best available one at or under the picked tier). The
    download re-extracts the video, and YouTube can hand that second
    extraction a stripped ladder even when the first one was complete -- the
    `height<=X` filter then quietly settles for less. The selection is checked
    before anything downloads and retried if it falls short."""
    url = normalize_url(url)
    roller = _RollingSpeed()
    throttle = {"limit": THROTTLED_BYTES_PER_SEC}

    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Téléchargement annulé par l'utilisateur.")

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

    def pp_hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Téléchargement annulé par l'utilisateur.")

    def make_opts(cookie_extra):
        opts = dict(ydl_opts)
        opts.update(cookie_extra)
        opts["progress_hooks"] = [hook]
        # Called before and after each post-processing step (merge, metadata,
        # conversion): "Annuler" during finalisation takes effect at the next
        # one instead of being ignored until the very end.
        opts["postprocessor_hooks"] = [pp_hook]
        if throttle["limit"]:
            opts["throttledratelimit"] = throttle["limit"]
        return opts

    def meets_expectation(info) -> bool:
        # TikTok/Instagram report a portrait video's long side as "height",
        # so the tier math doesn't transfer -- only YouTube is checked.
        if not expected_height or info.get("extractor_key") != "Youtube":
            return True
        height = _selected_video_height(info)
        return height is None or height >= expected_height

    def make_run(strict: bool):
        def run(opts):
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Resolve first, check, *then* download exactly what was
                # resolved -- inside the retry loop, so a 403 on the media
                # fetch still falls back to the signed-in session as before.
                info = ydl.extract_info(url, download=False)
                if strict and not meets_expectation(info):
                    raise DegradedSelection(
                        f"got {_selected_video_height(info)}p, expected {expected_height}p"
                    )
                info = _first_entry(ydl.process_ie_result(info, download=True))
                return ydl, info, opts
        return run

    def resolve_and_download():
        # A retry usually gets the full ladder back, so a few fresh attempts
        # before settling. Only if every one comes back short does the final
        # pass accept what exists -- and the result says so rather than
        # passing it off as the quality that was asked for.
        for _ in range(DEGRADED_SELECTION_ATTEMPTS):
            try:
                return _with_auto_cookies(
                    make_opts, make_run(strict=True),
                    hint=cookies_browser_hint, cookies_file=cookies_file,
                )[0]
            except DegradedSelection:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Téléchargement annulé par l'utilisateur.")
        return _with_auto_cookies(
            make_opts, make_run(strict=False),
            hint=cookies_browser_hint, cookies_file=cookies_file,
        )[0]

    # A throttled stream gets fresh links, and yt-dlp resumes its .part where
    # it stopped. Bounded here (yt-dlp's own re-extract loop isn't, and
    # doesn't cover this resolve-then-download flow anyway); the last pass
    # drops the check so a genuinely slow connection still finishes.
    for attempt in range(THROTTLE_RETRIES + 1):
        if attempt == THROTTLE_RETRIES:
            throttle["limit"] = None
        try:
            result = resolve_and_download()
            break
        except ThrottledDownload:
            continue
    ydl, info, used_opts = result

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
    # After a conversion (audio extraction...) yt-dlp records the real file.
    for candidate in (info.get("filepath"), *[d.get("filepath") for d in info.get("requested_downloads") or []]):
        if candidate and os.path.isfile(candidate) and (not final_path or not os.path.isfile(final_path)):
            final_path = candidate

    cut_duration = None
    if cut and final_path and os.path.isfile(final_path):
        cut_duration = _cut_file(
            final_path, cut, info.get("duration"), ydl_opts.get("ffmpeg_location"),
            on_progress, cancel_event,
        )

    delivered = _selected_video_height(info)
    if expected_height and info.get("extractor_key") == "Youtube":
        measured = _probe_height(final_path, ydl_opts.get("ffmpeg_location"))
        if measured:
            delivered = measured
            if measured < expected_height * _QUALITY_TOLERANCE:
                raise QualityCheckFailed(
                    f"La vidéo n'a été obtenue qu'en {measured}p au lieu de {expected_height}p : "
                    "YouTube a limité la qualité pendant le téléchargement. Le fichier a été gardé, "
                    "mais réessayez dans un moment pour l'avoir en vraie qualité."
                )
    return {
        "title": info.get("title"),
        "description": info.get("description") or "",
        "webpage_url": info.get("webpage_url") or url,
        "filepath": final_path,
        "cut_duration": cut_duration,
        "delivered_height": delivered,
        "quality_downgraded": bool(
            expected_height and delivered and delivered < expected_height
            and info.get("extractor_key") == "Youtube"
        ),
    }

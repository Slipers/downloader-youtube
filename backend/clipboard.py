"""Puts an image on the Windows clipboard.

Windows expects a device-independent bitmap (CF_DIB) for pasted images, which
is simply a BMP without its 14-byte file header -- so the thumbnail is decoded
and re-encoded as BMP, then handed over with the header sliced off.

Note on the ctypes calls below: argtypes/restype are declared explicitly
because handles are pointer-sized. Left to its default int return, ctypes
truncates them on 64-bit Windows and the clipboard call silently fails.
"""
import ctypes
import io
import urllib.request
from ctypes import wintypes

CF_DIB = 8
GMEM_MOVEABLE = 0x0002
_BMP_FILE_HEADER_SIZE = 14

_THUMBNAIL_TIMEOUT = 10
# Generous, but a thumbnail that big means something is wrong -- don't let a
# surprise payload sit in memory.
_MAX_THUMBNAIL_BYTES = 20 * 1024 * 1024


def _bind():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _to_dib(image_bytes: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        # Thumbnails can come back as WebP (and occasionally with an alpha
        # channel). CF_DIB consumers handle plain 24-bit RGB most reliably,
        # so flatten to that rather than gambling on 32-bit alpha support.
        rgb = im.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, "BMP")
    return buffer.getvalue()[_BMP_FILE_HEADER_SIZE:]


def set_image(image_bytes: bytes) -> bool:
    dib = _to_dib(image_bytes)
    user32, kernel32 = _bind()

    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, dib, len(dib))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            return False
        # Ownership passed to the system on success -- freeing it here would
        # hand the next paste a dangling block.
        return True
    finally:
        user32.CloseClipboard()


def copy_image_from_url(url: str) -> bool:
    """Downloads an image and puts it on the clipboard. Never raises: this is a
    convenience on top of a finished download, and must not be able to turn a
    successful download into a failure."""
    if not url:
        return False
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "DownloaderYoutube"})
        with urllib.request.urlopen(request, timeout=_THUMBNAIL_TIMEOUT) as response:
            data = response.read(_MAX_THUMBNAIL_BYTES + 1)
        if not data or len(data) > _MAX_THUMBNAIL_BYTES:
            return False
        return set_image(data)
    except Exception:
        return False

"""Detects installed Chromium-based browsers on Windows for extension install."""
import os
import subprocess
from pathlib import Path

PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
PROGRAM_FILES_X86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
LOCAL_APP_DATA = os.environ.get("LocalAppData", str(Path.home() / "AppData" / "Local"))

# `policy_key` is the "<Vendor>\<Product>" suffix under HKCU\Software\Policies\...
# used by backend.extension_installer for the ExtensionInstallForcelist mechanism.
# `policy_supported` reflects whether that browser reliably honors Chrome
# enterprise policies (Opera/Vivaldi support is inconsistent, so those fall
# back straight to the guided manual install).
BROWSER_DEFS = [
    {
        "id": "chrome",
        "name": "Google Chrome",
        "candidates": [
            rf"{PROGRAM_FILES}\Google\Chrome\Application\chrome.exe",
            rf"{PROGRAM_FILES_X86}\Google\Chrome\Application\chrome.exe",
            rf"{LOCAL_APP_DATA}\Google\Chrome\Application\chrome.exe",
        ],
        "policy_key": r"Google\Chrome",
        "policy_supported": True,
    },
    {
        "id": "edge",
        "name": "Microsoft Edge",
        "candidates": [
            rf"{PROGRAM_FILES_X86}\Microsoft\Edge\Application\msedge.exe",
            rf"{PROGRAM_FILES}\Microsoft\Edge\Application\msedge.exe",
        ],
        "policy_key": r"Microsoft\Edge",
        "policy_supported": True,
    },
    {
        "id": "brave",
        "name": "Brave",
        "candidates": [
            rf"{PROGRAM_FILES}\BraveSoftware\Brave-Browser\Application\brave.exe",
            rf"{LOCAL_APP_DATA}\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "policy_key": r"BraveSoftware\Brave",
        "policy_supported": True,
    },
    {
        "id": "vivaldi",
        "name": "Vivaldi",
        "candidates": [
            rf"{LOCAL_APP_DATA}\Vivaldi\Application\vivaldi.exe",
        ],
        "policy_key": r"Vivaldi",
        "policy_supported": False,
    },
    {
        "id": "opera",
        "name": "Opera",
        "candidates": [
            rf"{LOCAL_APP_DATA}\Programs\Opera\launcher.exe",
            rf"{LOCAL_APP_DATA}\Programs\Opera\opera.exe",
        ],
        "policy_key": r"Opera Software\Opera Stable",
        "policy_supported": False,
    },
    {
        "id": "opera_gx",
        "name": "Opera GX",
        "candidates": [
            rf"{LOCAL_APP_DATA}\Programs\Opera GX\launcher.exe",
            rf"{LOCAL_APP_DATA}\Programs\Opera GX\opera.exe",
        ],
        "policy_key": r"Opera Software\Opera GX Stable",
        "policy_supported": False,
    },
]


def _resolve_exe(candidates):
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def detect_browsers() -> list[dict]:
    found = []
    for definition in BROWSER_DEFS:
        exe = _resolve_exe(definition["candidates"])
        if not exe:
            continue
        found.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "exe": exe,
                "policy_key": definition["policy_key"],
                "policy_supported": definition["policy_supported"],
            }
        )
    return found


def get_browser(browser_id: str) -> dict | None:
    for definition in BROWSER_DEFS:
        if definition["id"] != browser_id:
            continue
        exe = _resolve_exe(definition["candidates"])
        if not exe:
            return None
        return {**definition, "exe": exe}
    return None


EXTENSIONS_PAGE_URL = {
    "chrome": "chrome://extensions/",
    "edge": "edge://extensions/",
    "brave": "chrome://extensions/",
    "vivaldi": "vivaldi://extensions/",
    "opera": "opera://extensions/",
    "opera_gx": "opera://extensions/",
}


def launch_browser(browser_id: str) -> bool:
    """Opens/focuses the browser. Chromium browsers refuse chrome://-style URLs
    passed on the command line (a deliberate security restriction), so this
    can't deep-link straight to the extensions page -- the user is shown that
    page's address to paste in manually (see EXTENSIONS_PAGE_URL)."""
    browser = get_browser(browser_id)
    if not browser:
        return False
    try:
        subprocess.Popen([browser["exe"]])
        return True
    except OSError:
        return False

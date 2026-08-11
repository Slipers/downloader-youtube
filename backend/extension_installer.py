"""Copies the bundled extension into place and hands back a folder ready for
the browser's "Load unpacked" flow.

An earlier version of this module also tried to force-install the extension
via the Chrome ExtensionInstallForcelist policy, serving a signed .crx over
the local link server. That path is gone: it requires the machine to be
enrolled in enterprise/cloud management to have any effect on a real
consumer install (confirmed live via chrome://policy), and the registry
policy it wrote pointed at a .crx that could never actually be built --
its signing key is deliberately never shipped with the app (see README).
Left in place, that broken policy entry is what showed up to users as a
confusing "needs a private key" install error. `cleanup_stale_policies()`
below removes any leftover entries from before this was dropped.

Chrome (137+) also removed the `--load-extension` command-line flag it
used to be possible to auto-load an unpacked extension with, specifically
to stop apps like this one from doing exactly that -- so the browser's own
native "Load unpacked" file-picker click is an unavoidable last step, not
a gap in this code. Everything before it (closing/detecting the browser,
enabling Developer Mode, staging the files, copying the folder path) is
still fully automated by `mode="auto"`.
"""
import json
import shutil
import subprocess
import winreg
from pathlib import Path

from . import browsers, config, crx3


def _sync_extension_files() -> None:
    dest = config.EXTENSION_INSTALL_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for entry in crx3.PACKAGED_ENTRIES:
        shutil.copy2(config.EXTENSION_SRC_DIR / entry, dest / entry)
    icons_dest = dest / "icons"
    icons_dest.mkdir(exist_ok=True)
    for icon in (config.EXTENSION_SRC_DIR / "icons").glob("*.png"):
        shutil.copy2(icon, icons_dest / icon.name)


def _is_process_running(exe_path: str) -> bool:
    exe_name = Path(exe_path).name
    try:
        output = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return exe_name.lower() in output.stdout.lower()


def _remove_policy(policy_key: str) -> None:
    base_path = f"Software\\Policies\\{policy_key}"
    for subkey in ("ExtensionInstallForcelist", "ExtensionInstallSources"):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base_path}\\{subkey}", 0, winreg.KEY_ALL_ACCESS)
        except OSError:
            continue
        try:
            winreg.DeleteValue(key, "1")
        except OSError:
            pass
        finally:
            winreg.CloseKey(key)


def cleanup_stale_policies() -> None:
    """One-time cleanup for installs that ran an earlier version of this
    module: it used to write an ExtensionInstallForcelist registry policy
    pointing at a .crx that could never actually be built (see module
    docstring). Safe to call unconditionally -- a no-op if nothing was ever
    written."""
    for definition in browsers.BROWSER_DEFS:
        if definition["policy_supported"]:
            _remove_policy(definition["policy_key"])


def _enable_dev_mode_in_profiles(user_data_dir: str) -> bool:
    """Best-effort: flips extensions.ui.developer_mode=true directly in each
    local profile's Preferences file, so the user doesn't have to hunt for
    that toggle on the extensions page themselves. Only ever called while the
    browser is confirmed closed (concurrent writes would just get clobbered
    by the running browser anyway). Must never corrupt a real profile, so
    anything unexpected about a given file just gets skipped rather than
    raised."""
    root = Path(user_data_dir)
    if not root.is_dir():
        return False
    changed_any = False
    for profile_dir in [root / "Default", *root.glob("Profile *")]:
        prefs_path = profile_dir / "Preferences"
        if not prefs_path.is_file():
            continue
        try:
            data = json.loads(prefs_path.read_text(encoding="utf-8"))
            ui = data.setdefault("extensions", {}).setdefault("ui", {})
            if ui.get("developer_mode") is not True:
                ui["developer_mode"] = True
                tmp_path = prefs_path.with_name(prefs_path.name + ".ytdls_tmp")
                tmp_path.write_text(json.dumps(data), encoding="utf-8")
                tmp_path.replace(prefs_path)
            changed_any = True
        except (OSError, ValueError):
            continue
    return changed_any


def _copy_to_clipboard(text: str) -> bool:
    try:
        # clip.exe reads stdin in the console's ANSI codepage, not UTF-8.
        subprocess.run(
            ["clip"], input=text.encode("mbcs"), timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW, check=True,
        )
        return True
    except (OSError, subprocess.SubprocessError, UnicodeEncodeError):
        return False


def install_extension(browser_id: str) -> dict:
    """Stages the extension and hands back a folder ready for "Load unpacked".

    Also pre-flips Developer Mode in the browser's own profile (if it's
    closed) and copies the install folder to the clipboard, trimming the
    guided flow down to "paste URL, click Load unpacked, paste path" -- the
    last click can't be automated away (see module docstring).
    """
    browser = browsers.get_browser(browser_id)
    if not browser:
        return {"ok": False, "error": "browser_not_found"}

    try:
        _sync_extension_files()
    except OSError:
        return {"ok": False, "error": "extension_files_missing"}

    running = _is_process_running(browser["exe"])

    dev_mode_set = False
    if not running and browser.get("user_data_dir"):
        dev_mode_set = _enable_dev_mode_in_profiles(browser["user_data_dir"])

    path_copied = _copy_to_clipboard(str(config.EXTENSION_INSTALL_DIR))

    return {
        "ok": True,
        "browser": browser["name"],
        "browser_running": running,
        "dev_mode_set": dev_mode_set,
        "path_copied": path_copied,
        "install_dir": str(config.EXTENSION_INSTALL_DIR),
        "extensions_url": browsers.EXTENSIONS_PAGE_URL.get(browser_id, "chrome://extensions/"),
    }


def sync_only() -> dict:
    """Re-copies the bundled extension files -- used by the "Mettre à jour
    l'extension" flow, which doesn't need to know which browser it's for
    (the user just reloads it themselves)."""
    try:
        _sync_extension_files()
    except OSError:
        return {"ok": False, "error": "extension_files_missing"}
    return {"ok": True, "install_dir": str(config.EXTENSION_INSTALL_DIR)}

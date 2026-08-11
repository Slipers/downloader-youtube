"""Copies the bundled extension into place, packs+signs its .crx, and force-installs
it into the chosen browser via the ExtensionInstallForcelist policy (no admin
rights needed, HKCU only). Falls back to a guided manual "Load unpacked" flow
for browsers that don't reliably honor that policy (Opera, Vivaldi), or if the
policy write fails.
"""
import json
import shutil
import subprocess
import winreg
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from . import browsers, config, crx3

PRIVATE_KEY_PATH = Path(__file__).resolve().parent / "keys" / "extension_signing_key.pem"


def _load_private_key():
    return serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)


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


def _write_policy(policy_key: str) -> bool:
    base_path = f"Software\\Policies\\{policy_key}"
    try:
        force_key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, f"{base_path}\\ExtensionInstallForcelist", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(
            force_key, "1", 0, winreg.REG_SZ,
            f"{config.EXTENSION_ID};http://127.0.0.1:{config.LINK_SERVER_PORT}/update.xml",
        )
        winreg.CloseKey(force_key)

        sources_key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, f"{base_path}\\ExtensionInstallSources", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(sources_key, "1", 0, winreg.REG_SZ, f"http://127.0.0.1:{config.LINK_SERVER_PORT}/*")
        winreg.CloseKey(sources_key)
        return True
    except OSError:
        return False


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


def install_extension(browser_id: str, mode: str = "manual") -> dict:
    """Copies + signs the extension and hands back a folder ready for "Load unpacked".

    ExtensionInstallForcelist (the fully silent route) was tried first during
    development, but Chrome/Edge/Brave all refuse self-hosted (non-Web-Store)
    force-installs unless the machine is enrolled in enterprise/cloud
    management -- confirmed live via chrome://policy, which reports "Cet
    ordinateur n'est pas détecté comme étant géré par une entreprise" and
    blocks the entry. So the policy write is kept as a harmless best-effort
    (it silently helps on the rare managed machine) but the guided
    "Load unpacked" flow is always what's actually shown to the user, since
    it is the only path that reliably works on a regular consumer install.

    `mode="auto"` additionally pre-flips Developer Mode in the browser's own
    profile (if it's closed) and copies the install folder to the clipboard,
    trimming the guided flow down to "paste URL, click Load unpacked, paste
    path". `mode="manual"` leaves the browser profile untouched.
    """
    browser = browsers.get_browser(browser_id)
    if not browser:
        return {"ok": False, "error": "browser_not_found"}

    _sync_extension_files()
    try:
        # Only feeds the (unreliable, best-effort) enterprise-policy route
        # below -- the guided "Load unpacked" flow that's actually shown to
        # the user never touches the .crx. A signing failure (e.g. the
        # private key not being present in this build) must never block the
        # one install path that reliably works.
        build_crx(force=True)
    except Exception:
        pass

    running = _is_process_running(browser["exe"])

    if browser["policy_supported"]:
        _write_policy(browser["policy_key"])

    dev_mode_set = False
    if mode == "auto" and not running and browser.get("user_data_dir"):
        dev_mode_set = _enable_dev_mode_in_profiles(browser["user_data_dir"])

    path_copied = _copy_to_clipboard(str(config.EXTENSION_INSTALL_DIR))

    return {
        "ok": True,
        "method": "manual_fallback",
        "browser": browser["name"],
        "browser_running": running,
        "dev_mode_set": dev_mode_set,
        "path_copied": path_copied,
        "install_dir": str(config.EXTENSION_INSTALL_DIR),
        "extensions_url": browsers.EXTENSIONS_PAGE_URL.get(browser_id, "chrome://extensions/"),
    }


def sync_only() -> dict:
    """Re-copies the bundled extension files without touching browser policy
    -- used by the "Mettre à jour l'extension" flow, which doesn't need to
    know which browser it's for (the user just reloads it themselves)."""
    _sync_extension_files()
    try:
        build_crx(force=True)
    except Exception:
        pass
    return {"ok": True, "install_dir": str(config.EXTENSION_INSTALL_DIR)}


def build_crx(force: bool = False) -> Path:
    if force or not config.EXTENSION_CRX_PATH.exists():
        _sync_extension_files()
        private_key = _load_private_key()
        crx3.build_crx(config.EXTENSION_INSTALL_DIR, private_key, config.EXTENSION_CRX_PATH)
    return config.EXTENSION_CRX_PATH

"""Uninstaller for Downloader Youtube — bundled as uninstall.exe inside the install folder."""
import os
import subprocess
import sys
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import messagebox

APP_NAME = "Downloader Youtube"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DownloaderYoutube"


def remove_shortcut(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def main():
    root = tk.Tk()
    root.withdraw()

    install_dir = Path(sys.executable).resolve().parent
    proceed = messagebox.askyesno(
        f"Désinstaller {APP_NAME}",
        f"Voulez-vous désinstaller {APP_NAME} ?\n\nDossier : {install_dir}",
    )
    if not proceed:
        return

    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "DownloaderYoutube.exe"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        pass

    start_menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / f"{APP_NAME}.lnk"
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop" / f"{APP_NAME}.lnk"
    remove_shortcut(start_menu)
    remove_shortcut(desktop)

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass

    messagebox.showinfo(
        f"Désinstallation de {APP_NAME}",
        "Désinstallation terminée. Le dossier d'installation va être supprimé.",
    )

    # The running uninstall.exe can't delete its own containing folder synchronously,
    # so a short-lived detached script finishes the cleanup after this process exits.
    batch_path = Path(os.environ["TEMP"]) / "downloader_youtube_uninstall.bat"
    batch_path.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak > NUL\r\n"
        f'rmdir /s /q "{install_dir}"\r\n'
        f'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(
        ["cmd", "/c", str(batch_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


if __name__ == "__main__":
    main()

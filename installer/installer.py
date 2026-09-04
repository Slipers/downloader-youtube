"""Standalone GUI installer for Downloader Youtube — built into an .exe via PyInstaller.

Bundles the already-built app folder (dist/DownloaderYoutube, including uninstall.exe)
as embedded data and copies it into a per-user install location, with Start Menu /
Desktop shortcuts and an Add/Remove Programs entry — no admin rights required.

The UI uses plain Tk + hand-drawn Canvas widgets (rounded buttons, toggle switches,
a gradient sidebar) since ttk alone can't match the app's own design language.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import filedialog

APP_NAME = "Downloader Youtube"
APP_VERSION = "1.33"
EXE_NAME = "DownloaderYoutube.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DownloaderYoutube"

BG = "#0e1015"
PANEL = "#15171f"
SURFACE = "#1b1e28"
BORDER = "#2a2d38"
TEXT_0 = "#f5f6fa"
TEXT_1 = "#a9adc1"
ACCENT = "#ff3366"
ACCENT_2 = "#7c5cff"
SIDEBAR_TOP = (255, 51, 102)
SIDEBAR_BOTTOM = (124, 92, 255)


def resource_path(*parts) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def bundled_app_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "app"


def default_install_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME


def close_running_app():
    """A previous instance holding EXE_NAME (or one of its DLLs) open would
    otherwise make the file copy below hang/fail silently -- close it first,
    the same way any well-behaved installer does."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", EXE_NAME],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(0.6)  # let Windows release the file handles
    except OSError:
        pass


def copy_with_retry(src_file: Path, target: Path, attempts=6, delay=0.5):
    last_exc = None
    for _ in range(attempts):
        try:
            shutil.copy2(src_file, target)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc


def create_shortcut(link_path: Path, target: Path, workdir: Path):
    script = (
        f'$s = (New-Object -COM WScript.Shell).CreateShortcut("{link_path}"); '
        f'$s.TargetPath = "{target}"; '
        f'$s.WorkingDirectory = "{workdir}"; '
        f'$s.IconLocation = "{target}"; '
        f'$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def register_uninstall(install_dir: Path, size_kb: int):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(install_dir / EXE_NAME))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{install_dir / "uninstall.exe"}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)


# ---------------------------------------------------------------- widgets --
def _round_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    return canvas.create_polygon(_round_points(x1, y1, x2, y2, radius), smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, width=170, height=42,
                 bg=BG, fg="white", fill=ACCENT, fill_hover=ACCENT_2,
                 font=("Segoe UI Semibold", 11), outline=""):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.command = command
        self.text = text
        self.fg = fg
        self.fill = fill
        self.fill_hover = fill_hover
        self.font = font
        self.outline = outline
        self.w, self.h = width, height
        self._enabled = True
        self._paint(fill)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._enabled and self._paint(fill_hover))
        self.bind("<Leave>", lambda e: self._enabled and self._paint(fill))

    def _paint(self, color):
        self.delete("all")
        round_rect(self, 1, 1, self.w - 1, self.h - 1, self.h / 2, fill=color, outline=self.outline)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=self.fg, font=self.font)

    def _on_click(self, _e):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._paint(self.fill if enabled else BORDER)
        self.configure(cursor="hand2" if enabled else "arrow")


class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, variable: tk.BooleanVar, bg=BG, width=44, height=24):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.variable = variable
        self.w, self.h = width, height
        self.bind("<Button-1>", self._toggle)
        self.variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e=None):
        self.variable.set(not self.variable.get())

    def _draw(self):
        self.delete("all")
        on = self.variable.get()
        track = ACCENT if on else BORDER
        round_rect(self, 1, 1, self.w - 1, self.h - 1, self.h / 2, fill=track, outline="")
        r = (self.h - 8) / 2
        cx = self.w - 4 - r if on else 4 + r
        cy = self.h / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="white", outline="")


class GradientProgress(tk.Canvas):
    def __init__(self, parent, variable: tk.DoubleVar, width=420, height=12, bg=BG):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0)
        self.variable = variable
        self.w, self.h = width, height
        round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=SURFACE, outline=BORDER)
        self._fill = None
        self.variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self):
        if self._fill:
            self.delete(self._fill)
            self._fill = None
        pct = max(0.0, min(100.0, self.variable.get())) / 100
        if pct <= 0:
            return
        w = max(self.h, self.w * pct)
        self._fill = round_rect(self, 0, 0, w, self.h, self.h / 2, fill=ACCENT, outline="")


class Checkrow(tk.Frame):
    """A toggle switch with a label, styled like the app's own settings rows."""
    def __init__(self, parent, text, variable, bg=BG):
        super().__init__(parent, bg=bg)
        ToggleSwitch(self, variable, bg=bg).pack(side="left")
        tk.Label(self, text=text, bg=bg, fg=TEXT_1, font=("Segoe UI", 10)).pack(side="left", padx=(10, 0))


# --------------------------------------------------------------- app -------
class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Installation de {APP_NAME}")
        self.geometry("760x500")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._set_icon()

        self.install_dir = tk.StringVar(value=str(default_install_dir()))
        self.desktop_shortcut = tk.BooleanVar(value=True)
        self.launch_after = tk.BooleanVar(value=True)
        self.progress_value = tk.DoubleVar(value=0)
        self.status_text = tk.StringVar(value="")

        self._build_sidebar()
        self.content = tk.Frame(self, bg=BG)
        self.content.place(x=240, y=0, width=520, height=500)
        self._show_welcome()

    def _set_icon(self):
        try:
            self.iconbitmap(default=str(resource_path("assets", "icon.ico")))
        except tk.TclError:
            pass

    def _build_sidebar(self):
        sidebar = tk.Canvas(self, width=240, height=500, highlightthickness=0, bd=0)
        sidebar.place(x=0, y=0, width=240, height=500)
        steps = 500
        for i in range(steps):
            t = i / (steps - 1)
            r = round(SIDEBAR_TOP[0] + (SIDEBAR_BOTTOM[0] - SIDEBAR_TOP[0]) * t)
            g = round(SIDEBAR_TOP[1] + (SIDEBAR_BOTTOM[1] - SIDEBAR_TOP[1]) * t)
            b = round(SIDEBAR_TOP[2] + (SIDEBAR_BOTTOM[2] - SIDEBAR_TOP[2]) * t)
            sidebar.create_line(0, i, 240, i, fill=f"#{r:02x}{g:02x}{b:02x}")

        try:
            self._logo_img = tk.PhotoImage(file=str(resource_path("assets", "icon.png")))
            self._logo_img = self._logo_img.subsample(4, 4)
            sidebar.create_image(120, 130, image=self._logo_img)
        except tk.TclError:
            pass

        sidebar.create_text(120, 230, text="Downloader", fill="white", font=("Segoe UI Semibold", 17))
        sidebar.create_text(120, 258, text="Youtube", fill="white", font=("Segoe UI Semibold", 17))
        sidebar.create_text(
            120, 300, text="Téléchargez vos vidéos\nYouTube en un clic.",
            fill="#ffe1ea", font=("Segoe UI", 10), justify="center",
        )
        sidebar.create_text(
            120, 470, text=f"v{APP_VERSION}", fill="#f0d3dd", font=("Segoe UI", 9),
        )

    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _heading(self, parent, text, subtitle=None):
        tk.Label(parent, text=text, bg=BG, fg=TEXT_0, font=("Segoe UI Semibold", 17),
                 wraplength=460, justify="left").pack(anchor="w", pady=(0, 6))
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BG, fg=TEXT_1, font=("Segoe UI", 10),
                     wraplength=460, justify="left").pack(anchor="w", pady=(0, 20))

    def _field_label(self, parent, text):
        tk.Label(parent, text=text.upper(), bg=BG, fg=TEXT_1,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 6))

    # ---- screens ----
    def _show_welcome(self):
        self._clear()
        pad = tk.Frame(self.content, bg=BG)
        pad.pack(fill="both", expand=True, padx=34, pady=30)

        self._heading(
            pad, "Bienvenue !",
            "Cet assistant installe Downloader Youtube sur votre ordinateur. "
            "Aucun droit administrateur n'est nécessaire.",
        )

        self._field_label(pad, "Dossier d'installation")
        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x", pady=(0, 22))
        entry_wrap = tk.Frame(row, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        entry_wrap.pack(side="left", fill="x", expand=True, ipady=4)
        tk.Entry(entry_wrap, textvariable=self.install_dir, bg=SURFACE, fg=TEXT_0, insertbackground=TEXT_0,
                  relief="flat", font=("Segoe UI", 10), bd=0).pack(fill="x", padx=10, pady=4)
        tk.Frame(row, width=10, bg=BG).pack(side="left")
        RoundedButton(row, "Parcourir…", self._browse_dir, width=100, height=34,
                      fill=SURFACE, fill_hover=BORDER, font=("Segoe UI", 10)).pack(side="left")

        Checkrow(pad, "Créer un raccourci sur le Bureau", self.desktop_shortcut, bg=BG).pack(anchor="w", pady=6)
        Checkrow(pad, "Lancer l'application après l'installation", self.launch_after, bg=BG).pack(anchor="w", pady=6)

        tk.Frame(pad, bg=BG).pack(fill="both", expand=True)

        actions = tk.Frame(pad, bg=BG)
        actions.pack(fill="x", side="bottom")
        RoundedButton(actions, "Installer  →", self._show_progress, width=140, height=44).pack(side="right")
        RoundedButton(actions, "Annuler", self.destroy, width=100, height=44,
                      fill=SURFACE, fill_hover=BORDER).pack(side="right", padx=(0, 10))

    def _browse_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.install_dir.get())
        if chosen:
            self.install_dir.set(str(Path(chosen) / APP_NAME))

    def _show_progress(self):
        self._clear()
        pad = tk.Frame(self.content, bg=BG)
        pad.pack(fill="both", expand=True, padx=34, pady=30)

        self._heading(pad, "Installation en cours…", "Merci de patienter pendant la copie des fichiers.")

        GradientProgress(pad, self.progress_value, width=460, height=12, bg=BG).pack(anchor="w", pady=(6, 12))
        tk.Label(pad, textvariable=self.status_text, bg=BG, fg=TEXT_1, font=("Segoe UI", 10)).pack(anchor="w")

        threading.Thread(target=self._run_install, daemon=True).start()

    def _run_install(self):
        try:
            self.status_text.set("Fermeture d'une éventuelle instance en cours…")
            close_running_app()

            src = bundled_app_dir()
            dest = Path(self.install_dir.get())
            dest.mkdir(parents=True, exist_ok=True)

            files = [p for p in src.rglob("*") if p.is_file()]
            total = max(1, len(files))
            total_size = 0

            for i, f in enumerate(files, start=1):
                rel = f.relative_to(src)
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                copy_with_retry(f, target)
                total_size += f.stat().st_size
                self.progress_value.set(i / total * 90)
                self.status_text.set(f"Copie des fichiers… {i}/{total}")

            self.status_text.set("Création des raccourcis…")
            exe_path = dest / EXE_NAME
            start_menu_dir = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
            start_menu_dir.mkdir(parents=True, exist_ok=True)
            create_shortcut(start_menu_dir / f"{APP_NAME}.lnk", exe_path, dest)
            if self.desktop_shortcut.get():
                desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
                create_shortcut(desktop / f"{APP_NAME}.lnk", exe_path, dest)
            self.progress_value.set(95)

            self.status_text.set("Enregistrement dans Ajout/Suppression de programmes…")
            register_uninstall(dest, size_kb=total_size // 1024)
            self.progress_value.set(100)

            self.after(300, self._show_done)
        except Exception as exc:
            self.after(0, lambda: self._show_error(str(exc)))

    def _show_error(self, message: str):
        self._clear()
        pad = tk.Frame(self.content, bg=BG)
        pad.pack(fill="both", expand=True, padx=34, pady=30)
        self._heading(pad, "L'installation a échoué", message)
        RoundedButton(pad, "Fermer", self.destroy, width=120, height=40,
                      fill=SURFACE, fill_hover=BORDER).pack(anchor="w")

    def _show_done(self):
        self._clear()
        pad = tk.Frame(self.content, bg=BG)
        pad.pack(fill="both", expand=True, padx=34, pady=30)

        tk.Label(pad, text="✓", bg=BG, fg=ACCENT_2, font=("Segoe UI", 30, "bold")).pack(anchor="w", pady=(0, 4))
        self._heading(pad, f"{APP_NAME} est installé !", f"Installé dans :\n{self.install_dir.get()}")

        tk.Frame(pad, bg=BG).pack(fill="both", expand=True)
        actions = tk.Frame(pad, bg=BG)
        actions.pack(fill="x", side="bottom")
        RoundedButton(actions, "Terminer", self._finish, width=140, height=44).pack(side="right")

    def _finish(self):
        if self.launch_after.get():
            exe_path = Path(self.install_dir.get()) / EXE_NAME
            try:
                subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            except OSError:
                pass
        self.destroy()


if __name__ == "__main__":
    InstallerApp().mainloop()

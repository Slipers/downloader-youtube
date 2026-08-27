"""Checks for a newer app build and swaps the installed files in place before
relaunching -- all without the user having to re-run the installer by hand.

Two update sources are checked, in order:

1. **Local dev build** (`LOCAL_SOURCE_DIR`): while iterating on this exact
   machine, a freshly rebuilt `dist/DownloaderYoutube` folder (with a
   `version.txt` written alongside it) is picked up directly -- no network,
   no hosting needed. This is what makes "click Update in the app" work
   without ever handing over a new installer link.
2. **GitHub Releases** (`UPDATE_REPO`): for real distribution once published.
   Each release's tag is the version (e.g. "v1.2.0") with an asset named
   "*-update.zip" containing the built `dist/DownloaderYoutube` folder
   (see README "Publier une mise à jour"). Inactive until UPDATE_REPO is set.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

APP_VERSION = "1.27"

# Shown in the in-app "Nouveautés" panel. Kept as hand-written structured
# bullets (not the raw GitHub release body) so the changelog UI never has to
# parse markdown -- update this alongside APP_VERSION and the GitHub release
# notes when publishing.
CHANGELOG = [
    {
        "version": "1.27",
        "date": "22 août 2026",
        "bullets": [
            "Le correctif de la version 1.25 ne s'activait en réalité jamais une fois l'application installée (un détail technique liée à l'empaquetage empêchait silencieusement son chargement) — la lenteur et le 144p occasionnel qui persistaient malgré cette mise à jour sont maintenant réellement corrigés.",
            "Les vidéos exportées en MP4 utilisent maintenant systématiquement un codec compatible avec les logiciels de montage (Premiere Pro, etc.) au lieu d'un codec qui pouvait être refusé à l'import (« type de compression non prise en charge »).",
            "Le pourcentage affiché pendant la récupération d'une vidéo est maintenant un anneau de progression autour de la flèche, plus lisible que le texte flottant précédent.",
        ],
    },
    {
        "version": "1.26",
        "date": "22 août 2026",
        "bullets": [
            "La flèche qui tournait pendant la récupération d'une vidéo affiche maintenant un pourcentage de progression.",
        ],
    },
    {
        "version": "1.25",
        "date": "22 août 2026",
        "bullets": [
            "Correction d'un bug important : la récupération d'une vidéo pouvait prendre très longtemps, voire échouer complètement, et ne proposait parfois que du 144p.",
            "Le moteur JavaScript nécessaire pour les hautes résolutions tourne maintenant en arrière-plan en continu au lieu d'être relancé à chaque vidéo — les qualités jusqu'à la 4K reviennent, et la récupération d'une vidéo est nettement plus rapide.",
        ],
    },
    {
        "version": "1.24",
        "date": "21 août 2026",
        "bullets": [
            "Le défilement du panneau « Nouveautés » est maintenant fluide au lieu de sauter par à-coups.",
            "L'application vérifie désormais la présence d'une mise à jour toutes les 20 minutes pendant qu'elle est ouverte, plus seulement au démarrage — la popup peut donc apparaître en cours d'utilisation.",
            "Pendant une mise à jour, l'écran affiche maintenant un vrai pourcentage de progression au lieu d'un rond qui tourne.",
        ],
    },
    {
        "version": "1.23",
        "date": "21 août 2026",
        "bullets": [
            "Correction majeure : seules les qualités « Auto » et « 144p » étaient proposées, même pour les vidéos disponibles en 1080p ou 4K.",
            "YouTube exige désormais un moteur JavaScript pour donner accès aux hautes résolutions : l'application le télécharge et le configure automatiquement au premier lancement.",
            "Toute l'échelle de qualité (jusqu'à la 4K) est de nouveau disponible.",
        ],
    },
    {
        "version": "1.22",
        "date": "21 août 2026",
        "bullets": [
            "Le numéro de version installé s'affiche maintenant discrètement en bas à droite de l'application.",
        ],
    },
    {
        "version": "1.21",
        "date": "21 août 2026",
        "bullets": [
            "Correction d'un échec fréquent au téléchargement de vidéos YouTube (« HTTP Error 403: Forbidden »), causé par un bug côté YouTube touchant un des modes de connexion utilisés par l'application.",
        ],
    },
    {
        "version": "1.20",
        "date": "11 août 2026",
        "bullets": [
            "Avant de télécharger, l'application vérifie maintenant si un fichier du même nom existe déjà dans le dossier de destination.",
            "Si c'est le cas, trois choix : écraser le fichier existant, le renommer (avec un nom suggéré, modifiable), ou annuler.",
        ],
    },
    {
        "version": "1.19",
        "date": "11 août 2026",
        "bullets": [
            "Remplacement du système de notation obligatoire toutes les 2 minutes par un bouton « Donner mon avis » en bas des paramètres, mis en avant après un téléchargement si aucun avis n'a été donné depuis un mois.",
            "Correction du panneau « Nouveautés », devenu illisible avec l'accumulation des versions : il défile maintenant correctement au lieu de rétrécir le texte.",
            "Nouveau toggle « Toujours confirmer la vidéo » directement dans les paramètres, en plus de celui déjà présent sur l'écran de confirmation.",
            "Quand la confirmation vidéo est désactivée, l'écran de confirmation n'apparaît plus du tout — passage direct aux réglages de téléchargement.",
        ],
    },
    {
        "version": "1.18",
        "date": "11 août 2026",
        "bullets": [
            "Le son de démarrage se joue désormais dès la fin du chargement, sans avoir besoin de cliquer d'abord.",
            "Nouveau son de fin de téléchargement, avec un réglage pour désactiver tous les effets sonores.",
            "Nouvelle option « Toujours confirmer si il s'agit bien de la vidéo », discrète en bas de l'écran de confirmation.",
            "L'écran de chargement au démarrage reflète maintenant le vrai avancement au lieu d'une animation minutée.",
            "Nouveau système de notation : après une mise à jour et 2 minutes d'utilisation, un avis (note + commentaire) est demandé.",
        ],
    },
    {
        "version": "1.17",
        "date": "11 août 2026",
        "bullets": [
            "Son de démarrage plus long et plus riche (arpège en accord avec réverbération) au lieu de deux notes simples.",
            "Le son de démarrage se déclenche désormais de façon fiable même si le navigateur bloque la lecture automatique — il joue dès la première interaction si besoin.",
        ],
    },
    {
        "version": "1.16",
        "date": "11 août 2026",
        "bullets": [
            "Écran de démarrage animé au lancement de l'application, avec logo et barre de progression.",
            "Message de bienvenue affiché après chaque mise à jour, indiquant la nouvelle version installée.",
            "L'installation de l'extension est maintenant toujours automatique (le choix manuel/automatique a été retiré, jugé inutile).",
            "Correction de l'alignement du compteur de vidéos téléchargées dans les paramètres.",
        ],
    },
    {
        "version": "1.15",
        "date": "11 août 2026",
        "bullets": [
            "L'installation automatique de l'extension est maintenant un vrai enchaînement étape par étape (navigateur, mode développeur, fichiers, presse-papiers).",
            "Retrait du mécanisme de policy Chrome qui ne fonctionnait jamais et provoquait une erreur « clé privée » déroutante.",
            "Ajout du téléchargement de vidéos Instagram (reels et posts), avec un fond teinté orange et violet.",
            "Le bouton « Nouveautés » est maintenant dans la barre du haut, à côté de Paramètres.",
            "Correction d'une bulle bleue qui restait affichée même en mode YouTube.",
            "Réalignement et restylisation du compteur de vidéos téléchargées dans les paramètres.",
        ],
    },
    {
        "version": "1.14",
        "date": "11 août 2026",
        "bullets": [
            "Correction du bouton d'installation de l'extension qui échouait à chaque tentative (le dossier de l'extension n'était pas inclus dans l'application installée).",
            "Message clair « Veuillez télécharger l'extension avant de mettre à jour » quand l'extension n'est pas encore installée.",
            "La fenêtre de mise à jour affiche désormais un résumé simple, avec un bouton « Nouveautés » pour voir le détail des changements.",
            "Le fond d'écran se teinte de rouge pour YouTube et de bleu pour TikTok selon la plateforme sélectionnée.",
        ],
    },
    {
        "version": "1.13",
        "date": "11 août 2026",
        "bullets": [
            "Correction du bouton d'installation de l'extension qui restait bloqué sur « Préparation… ».",
            "Nouveau choix automatique/manuel pour installer l'extension.",
            "Les paramètres s'adaptent à la taille de la fenêtre au lieu d'afficher une barre de défilement.",
            "Bannière de mise à jour de l'extension plus compacte.",
        ],
    },
    {
        "version": "1.12",
        "date": "11 août 2026",
        "bullets": [
            "Correction du téléchargement de vidéos TikTok.",
            "Refonte des paramètres, avec statistique du nombre de vidéos téléchargées.",
            "Retrait de la vérification anti-robot par cookies.txt.",
            "Les mises à jour de l'application sont désormais obligatoires.",
        ],
    },
    {
        "version": "1.11",
        "date": "11 août 2026",
        "bullets": [
            "Ajout de l'extension navigateur, liée à l'application.",
            "Système de mise à jour automatique intégré, avec publication sur GitHub.",
            "Prise en charge du téléchargement de vidéos TikTok.",
        ],
    },
    {
        "version": "1.1",
        "date": "11 août 2026",
        "bullets": [
            "L'interface s'adapte correctement à la taille de la fenêtre.",
            "Tutoriel de bienvenue : espacement corrigé.",
            "Suppression de l'effet d'inclinaison 3D au survol du panneau de réglages.",
        ],
    },
    {
        "version": "1.0",
        "date": "11 août 2026",
        "bullets": [
            "Première version publique de Downloader Youtube.",
            "Téléchargement de vidéos YouTube avec choix de qualité, fps et format.",
            "Détection et installation automatique de FFmpeg.",
            "Aperçu en direct pendant le téléchargement, thème jour/nuit, confettis de fin.",
        ],
    },
]

# This machine's own dev build -- lets "Mettre à jour" work with zero hosting
# while iterating locally. Harmless no-op on any other machine (path won't exist).
LOCAL_SOURCE_DIR = Path(r"C:\Users\pasca\Desktop\Youtube Downloader Suite\dist\DownloaderYoutube")

# Point this at the GitHub repo where releases are published, e.g. "yourname/downloader-youtube".
UPDATE_REPO = "Slipers/downloader-youtube"
RELEASES_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts) or (0,)


def get_changelog() -> dict:
    return {"installed_version": APP_VERSION, "entries": CHANGELOG}


def _check_local_source() -> dict | None:
    version_file = LOCAL_SOURCE_DIR / "version.txt"
    if not version_file.exists():
        return None
    try:
        local_version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if parse_version(local_version) <= parse_version(APP_VERSION):
        return None
    return {
        "available": True,
        "checked": True,
        "source": "local",
        "version": local_version,
        "current_version": APP_VERSION,
        "path": str(LOCAL_SOURCE_DIR),
        "notes": "Nouvelle version disponible (build local).",
    }


def _check_github() -> dict:
    if "OWNER/REPO" in UPDATE_REPO:
        return {"available": False, "checked": False, "current_version": APP_VERSION}

    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DownloaderYoutube-Updater"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"available": False, "checked": False, "current_version": APP_VERSION}

    latest_tag = data.get("tag_name", "")
    if parse_version(latest_tag) <= parse_version(APP_VERSION):
        return {"available": False, "checked": True, "current_version": APP_VERSION}

    asset_url = next(
        (a.get("browser_download_url") for a in data.get("assets", [])
         if a.get("name", "").lower().endswith("-update.zip")),
        None,
    )
    if not asset_url:
        return {"available": False, "checked": True, "current_version": APP_VERSION}

    return {
        "available": True,
        "checked": True,
        "source": "github",
        "version": latest_tag.lstrip("vV"),
        "current_version": APP_VERSION,
        "url": asset_url,
        "notes": (data.get("body") or "").strip(),
    }


def check_for_update() -> dict:
    """Returns {available, checked, source, version, current_version, url|path, notes}."""
    return _check_local_source() or _check_github()


def download_update(url: str, on_progress) -> Path:
    """on_progress(percent) with percent in 0..100, or -1 if unknown."""
    dest = Path(tempfile.gettempdir()) / "DownloaderYoutube_update.zip"

    def _report(block_num, block_size, total_size):
        if total_size > 0:
            on_progress(min(100, int(block_num * block_size * 100 / total_size)))
        else:
            on_progress(-1)

    urllib.request.urlretrieve(url, dest, reporthook=_report)
    return dest


def apply_update_and_restart(update_info: dict, on_progress):
    """Prepares the new files (extracting the zip if it's a remote update, or
    using the local dev build directory as-is) and hands off to a detached
    helper script that waits for this process to exit, mirrors the new files
    over the install directory, relaunches the app, then deletes itself."""
    if not is_frozen():
        raise RuntimeError("La mise à jour automatique n'est disponible que depuis la version installée.")

    install_dir = Path(sys.executable).resolve().parent
    exe_path = install_dir / "DownloaderYoutube.exe"
    pid = os.getpid()

    if update_info.get("source") == "local":
        new_files_dir = Path(update_info["path"])
        cleanup_lines = ""  # never delete the dev build folder
        on_progress(100)
    else:
        zip_path = download_update(update_info["url"], on_progress)
        new_files_dir = Path(tempfile.gettempdir()) / "DownloaderYoutube_update_extracted"
        shutil.rmtree(new_files_dir, ignore_errors=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(new_files_dir)
        cleanup_lines = f'rmdir /s /q "{new_files_dir}"\r\ndel "{zip_path}"\r\n'

    log_path = Path(tempfile.gettempdir()) / "DownloaderYoutube_update.log"
    script_path = Path(tempfile.gettempdir()) / "DownloaderYoutube_apply_update.bat"
    # Note: this is written to a .bat FILE and invoked as `cmd /c file.bat`, so
    # it's parsed exactly once by the invoked shell -- redirection operators
    # here must NOT be caret-escaped (that escaping is only needed when a
    # command is passed inline as a single quoted string to `cmd /c "..."`,
    # where an outer parse pass would otherwise consume the operator first).
    script_path.write_text(
        "@echo off\r\n"
        f'echo [%date% %time%] waiting for pid {pid} to exit > "{log_path}"\r\n'
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
        "if %errorlevel%==0 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        # A stray orphaned instance from an earlier session can still be
        # holding the link-server port even though the instance the user
        # actually clicked "Update" from has exited -- if so, the relaunch
        # below silently loses to the single-instance guard and just
        # refocuses that stale (still-outdated) window, making the update
        # look like it "didn't take" and re-prompting forever. Clear out any
        # other copy by image name, not just the one PID we started from.
        f'echo [%date% %time%] clearing any other running copies >> "{log_path}"\r\n'
        'taskkill /F /IM DownloaderYoutube.exe >NUL 2>&1\r\n'
        "timeout /t 1 /nobreak >nul\r\n"
        f'echo [%date% %time%] copying files >> "{log_path}"\r\n'
        f'robocopy "{new_files_dir}" "{install_dir}" /MIR /NFL /NDL /NJH /NJS >> "{log_path}" 2>&1\r\n'
        f'echo [%date% %time%] robocopy exit code %errorlevel% >> "{log_path}"\r\n'
        f'start "" "{exe_path}"\r\n'
        f'echo [%date% %time%] relaunched >> "{log_path}"\r\n'
        f"{cleanup_lines}"
        'del "%~f0"\r\n',
        encoding="utf-8",
    )

    subprocess.Popen(
        ["cmd", "/c", str(script_path)],
        creationflags=_NO_WINDOW,
        close_fds=True,
    )

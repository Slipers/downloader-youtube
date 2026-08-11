# Downloader Youtube

Application desktop (Windows) pour télécharger des vidéos YouTube via [yt-dlp](https://github.com/yt-dlp/yt-dlp), avec une interface graphique en plusieurs étapes (fenêtre native pywebview + HTML/CSS/JS).

## Installation (utilisateur final)

Lancez `DownloaderYoutubeSetup.exe` : il installe l'application (aucun droit administrateur requis), crée les raccourcis Menu Démarrer / Bureau, et s'enregistre dans Ajout/Suppression de programmes (désinstallation propre incluse).

## Développement

```bash
pip install -r requirements.txt
python app.py
```

## Reconstruire l'exécutable et l'installeur

```bash
pip install pyinstaller pillow
python installer/generate_icon.py  # régénère assets/icon.ico si besoin

pyinstaller app.py --name "DownloaderYoutube" --windowed --noconfirm --clean --icon "assets/icon.ico" --add-data "frontend;frontend" --add-data "assets;assets"
pyinstaller installer/uninstall.py --name "uninstall" --onefile --windowed --noconfirm --clean --icon "assets/icon.ico" --distpath dist_uninstall
cp dist_uninstall/uninstall.exe dist/DownloaderYoutube/uninstall.exe
pyinstaller installer/installer.py --name "DownloaderYoutubeSetup" --onefile --windowed --noconfirm --clean --icon "assets/icon.ico" --add-data "dist/DownloaderYoutube;app" --add-data "assets;assets" --distpath dist_installer
```

Le résultat final est `dist_installer/DownloaderYoutubeSetup.exe`. L'installeur a sa propre interface (barre latérale dégradée, boutons et interrupteurs dessinés à la main) définie dans `installer/installer.py`, indépendante du CSS de l'app.

## Fonctionnement

1. Écran d'accueil → bouton **Démarrer**.
2. Collez un lien YouTube (bouton de collage rapide depuis le presse-papiers).
3. Les informations sont récupérées étape par étape (titre, chaîne, miniature, infos générales), puis la vidéo s'affiche pour confirmation avec une transition en flip.
4. Réglages (mise en page compacte sur deux colonnes, sans défilement) : qualité (Auto / 144p → 4K, résolutions indisponibles grisées), images par seconde (Auto / 10 / 24 / 50 / 60 / manuel, avec débit recommandé qui s'adapte à la qualité ET au fps choisis), format du fichier (MP4/MKV/WebM ou MP3/M4A/WAV/OPUS selon l'export), type d'export (vidéo+audio / audio seul / vidéo seule), dossier de destination via l'explorateur Windows, et estimation de la taille finale.
5. Le téléchargement démarre (petite animation de lancement) : détection de FFmpeg (installation automatique proposée si absent), initialisation, vérification de la vidéo, puis téléchargement accéléré (fragments en parallèle) avec barre de progression, vitesse et temps restant estimé (moyenne glissante sur 5 s). Un bouton **Arrêter** annule à tout moment et supprime les fichiers temporaires.
6. Un aperçu défile en direct pendant le téléchargement : les vignettes réelles de la vidéo (extraites des storyboards YouTube) s'affichent en fonction de la portion actuellement téléchargée.
7. À la fin : coche verte animée, temps écoulé affiché, et confettis (durée réglable dans les paramètres, 5 s par défaut).

## Autres fonctionnalités

- **Thème jour/nuit** réglable via le bouton en haut à droite, mémorisé entre les sessions.
- **Paramètres** (icône engrenage) : activer/désactiver l'aperçu vidéo pendant le téléchargement, régler la durée des confettis, désinstaller le FFmpeg installé automatiquement par l'application (sans toucher à une installation système existante), importer un fichier `cookies.txt` en secours quand la vérification anti-robot YouTube est requise.
- **Authentification YouTube 100% automatique** : quand une vidéo nécessite une connexion, l'app tente d'abord des clients YouTube sans cookies, puis essaie seule les cookies de chaque navigateur installé (Edge, Firefox, Chrome, Brave…), sans aucune action de l'utilisateur. Si le navigateur protège ses cookies d'une façon indéchiffrable (Chrome/Edge « App-Bound Encryption », de plus en plus courant), l'app le signale clairement et propose d'importer un fichier `cookies.txt` (exporté via une extension navigateur) comme solution fiable de secours.
- Les derniers réglages (qualité, fps, type d'export, format, dossier) sont mémorisés d'une session à l'autre.
- Le panneau de réglages s'incline légèrement en suivant le curseur (effet tilt 3D).
- Bouton « Copier le chemin » du fichier téléchargé sur l'écran de fin.

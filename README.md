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

pyinstaller app.py --name "DownloaderYoutube" --windowed --noconfirm --clean --icon "assets/icon.ico" --add-data "frontend;frontend" --add-data "assets;assets" --add-data "extension;extension"
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
- Bouton « Copier le chemin » du fichier téléchargé sur l'écran de fin.

## Extension navigateur

Le dossier `extension/` contient une extension Chromium (Chrome, Edge, Brave, Opera…) qui ajoute un bouton **Télécharger** à côté du bouton S'abonner sur les pages vidéo YouTube. Un clic ouvre l'app avec le lien déjà rempli, prêt pour les réglages.

- **Liaison** : dans le popup de l'extension, le bouton **Lier** détecte si l'app tourne (petit serveur local sur `127.0.0.1:47990`, démarré avec l'app), puis affiche une pop-up « Extension liée avec succès » côté app.
- **Installation depuis l'app** : Paramètres → section « Extension navigateur » → choisir un navigateur détecté sur la machine → **Installer**. Une fenêtre dans l'app affiche alors les 4 étapes exactes avec deux boutons **Copier** (adresse `chrome://extensions/` à coller + chemin du dossier `%LocalAppData%\DownloaderYoutubeer\extension` à coller) — un navigateur ne peut pas être ouvert automatiquement sur une de ses pages internes depuis une autre application (restriction de sécurité), donc ce flux guidé est la vraie méthode pour un usage personnel.
  - Une tentative d'installation 100 % silencieuse (policy `ExtensionInstallForcelist` auto-hébergée, avec `.crx` signé) est faite en arrière-plan à chaque installation : elle ne prend effet que sur un poste géré en entreprise (confirmé via `chrome://policy` : refusée sur une installation grand public non managée).
  - Le sélecteur du bouton « Télécharger » a un repli par texte (« S'abonner »/« Subscribe ») en plus des sélecteurs structurels, pour rester robuste aux variations de mise en page de YouTube selon le navigateur.
  - **Après toute mise à jour de l'extension**, il faut recharger son entrée dans la page des extensions du navigateur (icône ↻) puis actualiser les onglets YouTube ouverts — Chrome ne recharge jamais tout seul une extension non empaquetée.
- La clé de signature de l'extension vit dans `backend/keys/extension_signing_key.pem` (générée par `extension/build_keys.py`, à ne jamais redistribuer) et donne un identifiant d'extension stable, indépendant du chemin d'installation.

## Mises à jour automatiques

L'app vérifie au démarrage si une nouvelle version est publiée (`backend/updater.py`) et propose un bouton **Mettre à jour** avec téléchargement + installation + redémarrage automatiques, sans repasser par l'installeur.

- **Configuration** : `UPDATE_REPO` dans `backend/updater.py` pointe vers [Slipers/downloader-youtube](https://github.com/Slipers/downloader-youtube). Les releases y sont publiées avec des tags courts (`v1.11`, `v1.12`, …) plutôt qu'un semver complet.
- **Publier une mise à jour** :
  1. Montez `APP_VERSION` dans `backend/updater.py` (et `APP_VERSION` dans `installer/installer.py` pour cohérence), ex. `"1.12"`.
  2. Reconstruisez (`pyinstaller app.py ...` comme ci-dessus).
  3. Créez une *release* GitHub avec le tag correspondant (`gh release create v1.12 ...`), et joignez-y un zip du dossier `dist/DownloaderYoutube` nommé `*-update.zip` (ex. `python -c "import shutil; shutil.make_archive('DownloaderYoutube-v1.12-update', 'zip', 'dist/DownloaderYoutube')"`). Joignez aussi `DownloaderYoutubeSetup.exe` pour les installations neuves.
  4. Au prochain lancement, l'app détecte le tag plus récent, télécharge ce zip, remplace les fichiers en place et relance — le tout piloté par un petit script généré à la volée qui attend la fermeture du processus avant de copier (impossible d'écraser son propre .exe en cours d'exécution sous Windows).
- **Extension** : sa version suit celle de l'app (elle est embarquée dans le build). Si la copie déjà chargée dans un navigateur est plus ancienne que celle livrée avec l'app installée, un bandeau « Mettre à jour » apparaît dans Paramètres → Extension navigateur.

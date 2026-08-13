<div align="center">

# Downloader Youtube

Téléchargez des vidéos YouTube, TikTok et Instagram en quelques clics — qualité, format et dossier de destination choisis à l'avance, aucune ligne de commande.

[**⬇ Télécharger pour Windows**](https://github.com/Slipers/downloader-youtube/releases/latest/download/DownloaderYoutubeSetup.exe) · [Releases](https://github.com/Slipers/downloader-youtube/releases)

</div>

## Ce que ça fait

Downloader Youtube est une application Windows native (pywebview + [yt-dlp](https://github.com/yt-dlp/yt-dlp)) qui télécharge des vidéos YouTube, TikTok et Instagram : collez un lien, confirmez que c'est la bonne vidéo, choisissez qualité/format/dossier, et c'est parti — avec un aperçu en direct des vignettes réelles pendant le téléchargement. Une extension de navigateur compagnon ajoute un bouton **Télécharger** directement sur les pages YouTube.

## Pourquoi pas juste `yt-dlp` en ligne de commande ?

`yt-dlp` reste l'outil le plus puissant, mais il demande un terminal, des flags à mémoriser et une gestion manuelle de FFmpeg. Downloader Youtube encapsule tout ça dans une interface graphique : détection et installation automatique de FFmpeg, authentification YouTube automatique (cookies des navigateurs installés) quand une vidéo l'exige, prévisualisation avant de lancer quoi que ce soit, et mises à jour livrées automatiquement dans l'app.

## Fonctionnalités

- 🎯 **YouTube, TikTok et Instagram** — un seul champ de lien, l'app détecte la source
- 🖼️ **Confirmation visuelle** — miniature, titre et chaîne affichés avant de télécharger quoi que ce soit, avec une option pour la désactiver
- 🎚️ **Qualité et format au choix** — 144p → 4K, fps personnalisé, MP4/MKV/WebM ou MP3/M4A/WAV/OPUS, export vidéo+audio / audio seul / vidéo seule
- ⚡ **Téléchargement accéléré** — fragments en parallèle, vitesse et temps restant en direct, aperçu des vignettes réelles au fil du téléchargement
- 🧩 **FFmpeg géré automatiquement** — détecté et installé si absent, sans toucher à une éventuelle installation système
- 🔐 **Authentification YouTube automatique** — cookies des navigateurs installés essayés en silence, avec repli guidé (`cookies.txt`) si nécessaire
- 🧭 **Extension navigateur** — bouton **Télécharger** à côté de S'abonner sur YouTube, ouvre l'app avec le lien déjà rempli
- 🗂️ **Gestion des conflits de fichiers** — proposition d'écraser, renommer ou annuler si le fichier existe déjà
- 🔄 **Mises à jour automatiques** — détection, téléchargement et installation en un clic, avec changelog intégré
- 🌗 **Thème clair / sombre**, mémorisé entre les sessions
- 🔔 **Effets sonores optionnels** et confettis à la fin d'un téléchargement, désactivables dans les paramètres

## Pour commencer

1. [Téléchargez `DownloaderYoutubeSetup.exe`](https://github.com/Slipers/downloader-youtube/releases/latest/download/DownloaderYoutubeSetup.exe) et lancez-le — aucun droit administrateur requis, désinstallation propre incluse.
2. Collez un lien YouTube, TikTok ou Instagram dans le champ dédié (ou utilisez le bouton de collage rapide).
3. Confirmez qu'il s'agit bien de la vidéo attendue, réglez qualité / format / dossier de destination, puis lancez le téléchargement.

Pour télécharger sans quitter YouTube, installez l'extension navigateur depuis **Paramètres → Extension navigateur** : un bouton **Télécharger** apparaît alors à côté de S'abonner sur chaque page vidéo.

## Comment ça marche

Sous le capot, l'app pilote [yt-dlp](https://github.com/yt-dlp/yt-dlp) et FFmpeg pour l'extraction et le remuxage. Aucun serveur distant n'est impliqué dans le téléchargement lui-même : tout se passe en local. Un petit serveur HTTP interne (`127.0.0.1`) sert uniquement de pont avec l'extension navigateur, pour transmettre le lien d'une page YouTube ouverte vers l'app.

## Prérequis

- Windows 10/11

## Développement

```bash
pip install -r requirements.txt
python app.py
```

### Reconstruire l'exécutable et l'installeur

```bash
pip install pyinstaller pillow
python installer/generate_icon.py  # régénère assets/icon.ico si besoin

pyinstaller app.py --name "DownloaderYoutube" --windowed --noconfirm --clean --icon "assets/icon.ico" --add-data "frontend;frontend" --add-data "assets;assets" --add-data "extension;extension"
pyinstaller installer/uninstall.py --name "uninstall" --onefile --windowed --noconfirm --clean --icon "assets/icon.ico" --distpath dist_uninstall
cp dist_uninstall/uninstall.exe dist/DownloaderYoutube/uninstall.exe
pyinstaller installer/installer.py --name "DownloaderYoutubeSetup" --onefile --windowed --noconfirm --clean --icon "assets/icon.ico" --add-data "dist/DownloaderYoutube;app" --add-data "assets;assets" --distpath dist_installer
```

Le résultat final est `dist_installer/DownloaderYoutubeSetup.exe`. L'installeur a sa propre interface (barre latérale dégradée, boutons et interrupteurs dessinés à la main) définie dans `installer/installer.py`, indépendante du CSS de l'app.

## Extension navigateur

Le dossier `extension/` contient une extension Chromium (Chrome, Edge, Brave, Opera…) qui ajoute un bouton **Télécharger** à côté du bouton S'abonner sur les pages vidéo YouTube.

- **Liaison** : dans le popup de l'extension, le bouton **Lier** détecte si l'app tourne (petit serveur local sur `127.0.0.1:47990`, démarré avec l'app), puis affiche une pop-up « Extension liée avec succès » côté app.
- **Installation depuis l'app** : Paramètres → section « Extension navigateur » → choisir un navigateur détecté sur la machine → **Installer**. L'app affiche les étapes exactes avec les éléments à copier (adresse `chrome://extensions/` et chemin du dossier de l'extension) — un navigateur ne peut pas être ouvert automatiquement sur une de ses pages internes depuis une autre application, donc ce flux guidé est la vraie méthode pour un usage personnel.
- **Après toute mise à jour de l'extension**, il faut recharger son entrée dans la page des extensions du navigateur (icône ↻) puis actualiser les onglets YouTube ouverts — Chrome ne recharge jamais tout seul une extension non empaquetée.
- La clé de signature de l'extension vit dans `backend/keys/extension_signing_key.pem` (générée par `extension/build_keys.py`, à ne jamais redistribuer) et donne un identifiant d'extension stable, indépendant du chemin d'installation.

## Mises à jour automatiques

L'app vérifie au démarrage si une nouvelle version est publiée (`backend/updater.py`) et propose un bouton **Mettre à jour** avec téléchargement + installation + redémarrage automatiques, sans repasser par l'installeur.

- **Configuration** : `UPDATE_REPO` dans `backend/updater.py` pointe vers [Slipers/downloader-youtube](https://github.com/Slipers/downloader-youtube). Les releases y sont publiées avec des tags courts (`v1.20`, `v1.21`, …) plutôt qu'un semver complet.
- **Publier une mise à jour** :
  1. Montez `APP_VERSION` dans `backend/updater.py` (et `APP_VERSION` dans `installer/installer.py` pour cohérence), ex. `"1.21"`.
  2. Reconstruisez (`pyinstaller app.py ...` comme ci-dessus).
  3. Créez une *release* GitHub avec le tag correspondant (`gh release create v1.21 ...`), et joignez-y un zip du dossier `dist/DownloaderYoutube` nommé `*-update.zip` (ex. `python -c "import shutil; shutil.make_archive('DownloaderYoutube-v1.21-update', 'zip', 'dist/DownloaderYoutube')"`). Joignez aussi `DownloaderYoutubeSetup.exe` pour les installations neuves.
  4. Au prochain lancement, l'app détecte le tag plus récent, télécharge ce zip, remplace les fichiers en place et relance — le tout piloté par un petit script généré à la volée qui attend la fermeture du processus avant de copier (impossible d'écraser son propre .exe en cours d'exécution sous Windows).
- **Extension** : sa version suit celle de l'app (elle est embarquée dans le build). Si la copie déjà chargée dans un navigateur est plus ancienne que celle livrée avec l'app installée, un bandeau « Mettre à jour » apparaît dans Paramètres → Extension navigateur.

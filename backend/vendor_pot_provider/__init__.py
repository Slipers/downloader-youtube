# Vendored from bgutil-ytdlp-pot-provider 1.3.2 (getpot_bgutil.py and
# getpot_bgutil_http.py only, from yt_dlp_plugins/extractor/ in that package).
#
# Why vendored instead of just pip-installed as a real yt-dlp plugin: yt-dlp's
# plugin system finds plugins by walking real filesystem directories under the
# `yt_dlp_plugins` virtual namespace package (see yt_dlp/plugins.py), which
# does not work once the app is frozen with PyInstaller -- confirmed by
# building a minimal frozen test that imported it normally and got an empty
# provider registry. Importing these two files directly (a plain relative
# import of an ordinary package) sidesteps that discovery mechanism entirely
# and works the same whether frozen or not.
#
# Only the HTTP provider is vendored (talks to the persistent server started
# by backend/js_runtime.py) -- the script-mode providers aren't used, so
# they're left out.
#
# To update: replace these two files with the new version's copies and
# re-apply the single import fix in getpot_bgutil_http.py (it imports
# BgUtilPTPBase from a sibling module here instead of the `yt_dlp_plugins`
# namespace it ships with).

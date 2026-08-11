/* Bridge to the Python backend exposed by pywebview (window.pywebview.api). */

const apiReady = new Promise((resolve) => {
  if (window.pywebview && window.pywebview.api) {
    resolve();
    return;
  }
  window.addEventListener("pywebviewready", () => resolve());
});

const bridgeListeners = {};

window.__bridge__ = function (event, payload) {
  (bridgeListeners[event] || []).forEach((fn) => fn(payload));
};

function on(event, fn) {
  (bridgeListeners[event] = bridgeListeners[event] || []).push(fn);
}

function off(event, fn) {
  if (!bridgeListeners[event]) return;
  bridgeListeners[event] = bridgeListeners[event].filter((f) => f !== fn);
}

const Api = {
  on,
  off,
  async getSettings() {
    await apiReady;
    return window.pywebview.api.get_settings();
  },
  async saveTheme(theme) {
    await apiReady;
    return window.pywebview.api.save_theme(theme);
  },
  async savePreference(key, value) {
    await apiReady;
    return window.pywebview.api.save_preference(key, value);
  },
  async openFolder(path) {
    await apiReady;
    return window.pywebview.api.open_folder(path);
  },
  async pickFolder() {
    await apiReady;
    return window.pywebview.api.pick_folder();
  },
  async getCookiesFileStatus() {
    await apiReady;
    return window.pywebview.api.get_cookies_file_status();
  },
  async importCookiesFile() {
    await apiReady;
    return window.pywebview.api.import_cookies_file();
  },
  async clearCookiesFile() {
    await apiReady;
    return window.pywebview.api.clear_cookies_file();
  },
  async fetchVideoInfo(url) {
    await apiReady;
    return window.pywebview.api.fetch_video_info(url);
  },
  async getStoryboardSprite(url) {
    await apiReady;
    return window.pywebview.api.get_storyboard_sprite(url);
  },
  async checkFfmpeg() {
    await apiReady;
    return window.pywebview.api.check_ffmpeg();
  },
  async installFfmpeg() {
    await apiReady;
    return window.pywebview.api.install_ffmpeg();
  },
  async getFfmpegStatus() {
    await apiReady;
    return window.pywebview.api.get_ffmpeg_status();
  },
  async uninstallFfmpeg() {
    await apiReady;
    return window.pywebview.api.uninstall_ffmpeg();
  },
  async startDownload(url, options) {
    await apiReady;
    return window.pywebview.api.start_download(url, options);
  },
  async cancelDownload() {
    await apiReady;
    return window.pywebview.api.cancel_download();
  },
  async checkForUpdate() {
    await apiReady;
    return window.pywebview.api.check_for_update();
  },
  async downloadUpdate(url) {
    await apiReady;
    return window.pywebview.api.download_update(url);
  },
  async installUpdate(path) {
    await apiReady;
    return window.pywebview.api.install_update(path);
  },
  async markTutorialSeen() {
    await apiReady;
    return window.pywebview.api.mark_tutorial_seen();
  },
};

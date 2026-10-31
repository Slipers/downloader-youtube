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
  async pickFolder(remember = true) {
    await apiReady;
    return window.pywebview.api.pick_folder(remember);
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
  async checkOutputExists(title, options) {
    await apiReady;
    return window.pywebview.api.check_output_exists(title, options);
  },
  async getPublishStatus() {
    await apiReady;
    return window.pywebview.api.get_publish_status();
  },
  async connectPublishChannel() {
    await apiReady;
    return window.pywebview.api.connect_publish_channel();
  },
  async cancelPublishConnect() {
    await apiReady;
    return window.pywebview.api.cancel_publish_connect();
  },
  async disconnectPublishChannel() {
    await apiReady;
    return window.pywebview.api.disconnect_publish_channel();
  },
  async pickPublishThumbnail() {
    await apiReady;
    return window.pywebview.api.pick_publish_thumbnail();
  },
  async startPublish(payload) {
    await apiReady;
    return window.pywebview.api.start_publish(payload);
  },
  async openYoutubeLink(url) {
    await apiReady;
    return window.pywebview.api.open_youtube_link(url);
  },
  async cancelPublish() {
    await apiReady;
    return window.pywebview.api.cancel_publish();
  },
  async startDownload(url, options) {
    await apiReady;
    return window.pywebview.api.start_download(url, options);
  },
  async cancelDownload() {
    await apiReady;
    return window.pywebview.api.cancel_download();
  },
  async getExtensionStatus() {
    await apiReady;
    return window.pywebview.api.get_extension_status();
  },
  async listBrowsers() {
    await apiReady;
    return window.pywebview.api.list_browsers();
  },
  async installExtension(browserId) {
    await apiReady;
    return window.pywebview.api.install_extension(browserId);
  },
  async launchBrowser(browserId) {
    await apiReady;
    return window.pywebview.api.launch_browser(browserId);
  },
  async getAppVersion() {
    await apiReady;
    return window.pywebview.api.get_app_version();
  },
  async getYoutubeSessionStatus() {
    await apiReady;
    return window.pywebview.api.get_youtube_session_status();
  },
  async openYoutubeLogin() {
    await apiReady;
    return window.pywebview.api.open_youtube_login();
  },
  async signOutYoutube() {
    await apiReady;
    return window.pywebview.api.sign_out_youtube();
  },
  async getJsRuntimeStatus() {
    await apiReady;
    return window.pywebview.api.get_js_runtime_status();
  },
  async startJsRuntimeInstall() {
    await apiReady;
    return window.pywebview.api.start_js_runtime_install();
  },
  async getChangelog() {
    await apiReady;
    return window.pywebview.api.get_changelog();
  },
  async checkForUpdate() {
    await apiReady;
    return window.pywebview.api.check_for_update();
  },
  async startAppUpdate(updateInfo) {
    await apiReady;
    return window.pywebview.api.start_app_update(updateInfo);
  },
  async checkExtensionUpdate() {
    await apiReady;
    return window.pywebview.api.check_extension_update();
  },
  async updateExtensionFiles() {
    await apiReady;
    return window.pywebview.api.update_extension_files();
  },
};

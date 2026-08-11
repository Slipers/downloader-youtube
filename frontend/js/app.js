/* Screen state machine + UI wiring for Downloader Youtube. */

const QUALITY_ORDER = ["auto", "144p", "480p", "720p", "1080p", "1440p", "2160p"];
const YT_URL_RE = /^https?:\/\/(www\.)?(youtube\.com\/(watch\?v=|shorts\/)|youtu\.be\/)[\w-]+/i;
const TIKTOK_URL_RE = /^https?:\/\/(www\.|vm\.|vt\.|m\.)?tiktok\.com\//i;
const INSTAGRAM_URL_RE = /^https?:\/\/(www\.)?instagram\.com\/(reel|p|tv)\/[\w-]+/i;

const PLATFORM_URL_RE = { youtube: YT_URL_RE, tiktok: TIKTOK_URL_RE, instagram: INSTAGRAM_URL_RE };
const PLATFORM_PLACEHOLDER = {
  youtube: "https://www.youtube.com/watch?v=...",
  tiktok: "https://www.tiktok.com/@utilisateur/video/...",
  instagram: "https://www.instagram.com/reel/...",
};
const PLATFORM_SUBTITLE = {
  youtube: "Copiez l'URL YouTube de la vidéo que vous souhaitez télécharger.",
  tiktok: "Copiez l'URL TikTok de la vidéo que vous souhaitez télécharger.",
  instagram: "Copiez l'URL Instagram de la vidéo (reel ou post) que vous souhaitez télécharger.",
};

const state = {
  settings: null,
  qualityTiers: {},
  fpsChoices: [10, 24, 50, 60],
  videoContainers: ["mp4", "mkv", "webm"],
  audioFormats: ["mp3", "m4a", "wav", "opus"],
  recommendedAudioKbps: 192,
  confettiSeconds: 5,
  url: "",
  platform: "youtube",
  videoInfo: null,
  quality: "1080p",
  fps: "auto",
  fpsIsManual: false,
  exportType: "video_audio",
  outputFormat: "mp4",
  bitrate: 0,
  destDir: "",
  showPreview: true,
  viaExtension: false,
};

let cancelRequested = false;

/* ---------- helpers ---------- */
function $(id) { return document.getElementById(id); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "";
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return "--:--";
  return formatDuration(seconds);
}

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec) return "";
  const mb = bytesPerSec / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} Mo/s`;
  return `${(bytesPerSec / 1024).toFixed(0)} Ko/s`;
}

function formatBytes(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} Go`;
  return `${mb.toFixed(1)} Mo`;
}

function animateValue(from, to, duration, onUpdate) {
  if (from === to) { onUpdate(to); return; }
  const start = performance.now();
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    onUpdate(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* ---------- screens ---------- */
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((el) => {
    if (el.id === id) {
      el.classList.add("active");
      el.classList.remove("leaving");
    } else if (el.classList.contains("active")) {
      el.classList.add("leaving");
      el.classList.remove("active");
    }
  });
}

const MODAL_FIT_MIN_SCALE = 0.65;

function fitModalToViewport(overlayId) {
  const overlay = $(overlayId);
  const modal = overlay && overlay.querySelector(".modal");
  if (!modal) return;
  // `zoom` changes the element's own rendered size from its parent's point
  // of view (unlike `transform: scale`, which only affects paint -- the
  // overlay's scrollable area would stay unchanged). But a zoomed element
  // reports its OWN scrollHeight/offsetHeight in its own (zoomed-local)
  // coordinate space, so there's no reliable formula from "natural size at
  // zoom:1" straight to "the zoom factor that makes it fit". Binary-search
  // it instead, measuring the overlay's real scrollHeight -- ground truth --
  // after each attempt. Note scrollHeight can never read below clientHeight
  // (that's its definition), so "fits" is exactly scrollHeight <= clientHeight
  // -- not some margin below it, which would be an unreachable target.
  modal.style.zoom = "1";
  if (overlay.scrollHeight <= overlay.clientHeight) return;

  let lo = MODAL_FIT_MIN_SCALE;
  let hi = 1;
  for (let i = 0; i < 12; i++) {
    const mid = (lo + hi) / 2;
    modal.style.zoom = String(mid);
    if (overlay.scrollHeight > overlay.clientHeight) {
      hi = mid;
    } else {
      lo = mid;
    }
  }
  // lo is the largest tested scale confirmed to fit; back off a hair more
  // as a sub-pixel-rounding safety margin.
  modal.style.zoom = String(lo * 0.99);
}

function openModal(id) {
  $(id).classList.add("active");
  fitModalToViewport(id);
}
function closeModal(id) { $(id).classList.remove("active"); }

window.addEventListener("resize", () => {
  document.querySelectorAll(".modal-overlay.active").forEach((overlay) => fitModalToViewport(overlay.id));
});

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function initTheme(savedTheme) {
  const theme = savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
  $("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    Api.saveTheme(next);
  });
}

/* ---------- settings modal ---------- */
function initSettingsModal() {
  $("settings-toggle").addEventListener("click", () => openModal("modal-settings"));
  $("settings-close").addEventListener("click", () => closeModal("modal-settings"));

  const toggle = $("toggle-preview");
  toggle.addEventListener("click", () => {
    state.showPreview = !state.showPreview;
    toggle.classList.toggle("on", state.showPreview);
    toggle.setAttribute("aria-checked", String(state.showPreview));
    Api.savePreference("show_preview", state.showPreview);
  });

  const sfxToggle = $("toggle-sfx");
  sfxToggle.addEventListener("click", () => {
    state.sfxEnabled = !state.sfxEnabled;
    sfxToggle.classList.toggle("on", state.sfxEnabled);
    sfxToggle.setAttribute("aria-checked", String(state.sfxEnabled));
    Api.savePreference("sfx_enabled", state.sfxEnabled);
  });

  const confettiInput = $("confetti-seconds-input");
  confettiInput.addEventListener("change", () => {
    const value = Math.max(1, Math.min(30, Number(confettiInput.value) || 5));
    confettiInput.value = value;
    state.confettiSeconds = value;
    Api.savePreference("confetti_seconds", value);
  });

  $("settings-toggle").addEventListener("click", refreshFfmpegStatus);
  $("btn-uninstall-ffmpeg").addEventListener("click", async () => {
    const btn = $("btn-uninstall-ffmpeg");
    btn.disabled = true;
    await Api.uninstallFfmpeg();
    await refreshFfmpegStatus();
    btn.disabled = false;
  });

  $("settings-toggle").addEventListener("click", refreshExtensionSettings);
  $("btn-update-extension").addEventListener("click", async () => {
    const btn = $("btn-update-extension");
    btn.disabled = true;
    btn.textContent = "Mise à jour…";
    try {
      const result = await Api.updateExtensionFiles();
      if (result.ok) {
        $("extension-update-row").hidden = true;
        fitModalToViewport("modal-settings");
        showToast("Extension mise à jour — rechargez-la (icône ↻ dans la page des extensions) puis actualisez YouTube.");
      } else {
        showToast("Échec de la mise à jour de l'extension.");
      }
    } catch (err) {
      showToast("Échec de la mise à jour de l'extension.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Mettre à jour";
    }
  });

  $("settings-toggle").addEventListener("click", refreshStats);
}

function refreshStats() {
  const total = state.settings.total_downloads || 0;
  $("stat-total-downloads").textContent = total;
  $("stat-total-downloads-label").textContent = total === 1 ? "vidéo téléchargée" : "vidéos téléchargées";
}

async function refreshFfmpegStatus() {
  const statusText = $("ffmpeg-status-text");
  const btn = $("btn-uninstall-ffmpeg");
  statusText.textContent = "Vérification…";
  btn.hidden = true;

  const status = await Api.getFfmpegStatus();
  if (!status.installed) {
    statusText.textContent = "Non installé.";
  } else if (status.local) {
    statusText.textContent = "Installé automatiquement par l'application.";
    btn.hidden = false;
  } else {
    statusText.textContent = "Détecté sur le système (non géré par l'application).";
  }
  fitModalToViewport("modal-settings");
}

/* ---------- toast ---------- */
let toastTimer = null;
function showToast(text, durationMs = 3200) {
  const toast = $("toast");
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), durationMs);
}

/* ---------- extension settings ---------- */
async function refreshExtensionSettings() {
  const statusText = $("extension-status-text");
  const list = $("browser-list");
  statusText.textContent = "Vérification…";

  const [status, browserList, extUpdate] = await Promise.all([
    Api.getExtensionStatus(), Api.listBrowsers(), Api.checkExtensionUpdate(),
  ]);
  statusText.textContent = status.paired
    ? "Extension liée ✓"
    : "Non liée — installez l'extension puis cliquez « Lier » dans son menu.";

  const updateRow = $("extension-update-row");
  const updateBtn = $("btn-update-extension");
  if (extUpdate.available && status.paired) {
    $("extension-update-text").textContent = `Nouvelle version de l'extension disponible (v${extUpdate.version}).`;
    updateBtn.hidden = false;
    updateRow.hidden = false;
  } else if (extUpdate.available && !status.paired) {
    $("extension-update-text").textContent = "Veuillez télécharger l'extension avant de mettre à jour.";
    updateBtn.hidden = true;
    updateRow.hidden = false;
  } else {
    updateRow.hidden = true;
  }

  list.innerHTML = "";
  if (!browserList.length) {
    const empty = document.createElement("p");
    empty.className = "hint-text";
    empty.textContent = "Aucun navigateur Chromium détecté sur cet ordinateur.";
    list.appendChild(empty);
    fitModalToViewport("modal-settings");
    return;
  }

  browserList.forEach((browser) => {
    const row = document.createElement("div");
    row.className = "browser-row";
    row.innerHTML = `
      <div class="browser-row-icon">${browser.name.charAt(0)}</div>
      <div class="browser-row-name">${browser.name}</div>
    `;
    const btn = document.createElement("button");
    btn.className = "btn-secondary";
    btn.textContent = "Installer";
    btn.addEventListener("click", () => onInstallBrowser(browser, btn));
    row.appendChild(btn);
    list.appendChild(row);
  });
  fitModalToViewport("modal-settings");
}

async function onInstallBrowser(browser, btn) {
  $("ext-choice-browser-name").textContent = browser.name;
  document.querySelectorAll("#ext-auto-steps .fetch-step").forEach((el) => el.classList.remove("active", "done"));
  openModal("modal-extension-install-choice");

  let result;
  try {
    result = await runFetchStagesAnimation(Api.installExtension(browser.id), "ext-auto-steps");
  } catch (err) {
    result = { ok: false };
  }

  closeModal("modal-extension-install-choice");

  if (!result.ok) {
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.textContent = "Échec";
    showToast(
      result.error === "extension_files_missing"
        ? "Fichiers de l'extension introuvables — réinstallez l'application."
        : "Échec de l'installation de l'extension.",
    );
    setTimeout(() => { btn.disabled = false; btn.textContent = originalLabel; }, 3000);
    return;
  }

  $("ext-install-browser-name").textContent = result.browser;
  $("ext-install-url").textContent = result.extensions_url;
  $("ext-install-path").textContent = result.install_dir;
  $("ext-install-auto-note").hidden = !result.dev_mode_set;
  $("ext-install-step-devmode").hidden = result.dev_mode_set;
  $("modal-extension-install").dataset.browserId = browser.id;
  openModal("modal-extension-install");
  Api.launchBrowser(browser.id);

  btn.disabled = false;
  btn.textContent = "Réinstaller";
}

/* ---------- app update ---------- */
let pendingUpdateInfo = null;

function initAppUpdateModal() {
  // Deliberately no way to dismiss the "update available" state (no decline
  // button, no backdrop-click handler anywhere in this app) -- an available
  // update blocks the app until installed. The error state still gets a
  // close button so a transient failure (e.g. no internet) doesn't brick
  // the app permanently; it'll just ask again next launch.
  $("update-error-close").addEventListener("click", () => closeModal("modal-app-update"));
  $("update-accept").addEventListener("click", onAcceptUpdate);
}

let changelogLoaded = false;

async function openChangelogModal() {
  openModal("modal-changelog");
  if (changelogLoaded) return;
  try {
    const { installed_version, entries } = await Api.getChangelog();
    $("changelog-installed-version").textContent = `Version installée : v${installed_version}`;
    const list = $("changelog-list");
    list.innerHTML = "";
    entries.forEach((entry, i) => {
      const item = document.createElement("div");
      item.className = "changelog-entry";
      const isNewest = i === 0;
      item.innerHTML = `
        <div class="changelog-entry-marker${isNewest ? " newest" : ""}"></div>
        <div class="changelog-entry-body">
          <div class="changelog-entry-head">
            <span class="changelog-entry-version">Version ${entry.version}</span>
            ${isNewest ? '<span class="changelog-entry-badge">Nouveau</span>' : ""}
            <span class="changelog-entry-date">${entry.date}</span>
          </div>
          <ul>${entry.bullets.map((b) => `<li>${b}</li>`).join("")}</ul>
        </div>
      `;
      list.appendChild(item);
    });
    changelogLoaded = true;
    fitModalToViewport("modal-changelog");
  } catch (err) { /* leave the modal open with whatever loaded, if anything */ }
}

function initChangelogModal() {
  $("btn-open-changelog").addEventListener("click", openChangelogModal);
  $("update-changelog-btn").addEventListener("click", openChangelogModal);
  $("changelog-close").addEventListener("click", () => closeModal("modal-changelog"));
}

async function checkForUpdateOnStartup() {
  let result;
  try {
    result = await Api.checkForUpdate();
  } catch (err) {
    return;
  }
  if (!result?.available) return;

  pendingUpdateInfo = result;
  $("update-ask").hidden = false;
  $("update-downloading").hidden = true;
  $("update-installing").hidden = true;
  $("update-error").hidden = true;
  $("update-version-label").textContent = `v${result.version}`;
  openModal("modal-app-update");
}

async function onAcceptUpdate() {
  if (!pendingUpdateInfo) return;
  $("update-ask").hidden = true;
  $("update-downloading").hidden = false;
  $("update-progress-fill").style.width = "0%";
  $("update-progress-label").textContent = "0%";

  const progressHandler = (payload) => {
    if (payload.percent >= 0) {
      $("update-progress-fill").style.width = `${payload.percent}%`;
      $("update-progress-label").textContent = `${payload.percent}%`;
    }
  };
  const installingHandler = () => {
    $("update-downloading").hidden = true;
    $("update-installing").hidden = false;
  };
  const errorHandler = (payload) => {
    Api.off("update_progress", progressHandler);
    Api.off("update_installing", installingHandler);
    Api.off("update_error", errorHandler);
    $("update-downloading").hidden = true;
    $("update-installing").hidden = true;
    $("update-error").hidden = false;
    $("update-error-text").textContent = payload.error;
  };
  Api.on("update_progress", progressHandler);
  Api.on("update_installing", installingHandler);
  Api.on("update_error", errorHandler);

  await Api.startAppUpdate(pendingUpdateInfo);
}

function initExtensionInstallModal() {
  $("ext-install-close").addEventListener("click", () => closeModal("modal-extension-install"));
  $("ext-install-open-browser").addEventListener("click", () => {
    const browserId = $("modal-extension-install").dataset.browserId;
    if (browserId) Api.launchBrowser(browserId);
  });
  document.querySelectorAll(".btn-copy-small").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = $(btn.dataset.copyTarget);
      try {
        await navigator.clipboard.writeText(target.textContent);
        const original = btn.textContent;
        btn.textContent = "Copié !";
        setTimeout(() => { btn.textContent = original; }, 1500);
      } catch (err) { /* ignore */ }
    });
  });
}

/* ---------- post-update welcome ---------- */
function initWelcomeModal() {
  $("welcome-close").addEventListener("click", () => closeModal("modal-welcome"));
}

async function checkWelcomeMessage() {
  let appVersion;
  try {
    appVersion = await Api.getAppVersion();
  } catch (err) {
    return;
  }
  state.appVersion = appVersion;
  const lastSeen = state.settings.last_seen_version;
  // Only announce on the launch right after an update -- a brand new
  // install has no "previous version" to welcome back from, so lastSeen
  // being unset (first ever launch) is deliberately not announced.
  if (lastSeen && lastSeen !== appVersion) {
    $("welcome-version").textContent = `v${appVersion}`;
    openModal("modal-welcome");
  }
  if (lastSeen !== appVersion) {
    Api.savePreference("last_seen_version", appVersion);
  }
}

/* ---------- mandatory post-update rating ---------- */
const RATING_DELAY_MS = 2 * 60 * 1000;
const RATING_MIN_CHARS = 100;
let ratingSelectedStars = 0;

function updateStarDisplay(rating) {
  document.querySelectorAll("#star-rating .star-btn").forEach((btn) => {
    const starIndex = Number(btn.dataset.star);
    let fill = 0;
    if (rating >= starIndex) fill = 100;
    else if (rating >= starIndex - 0.5) fill = 50;
    btn.style.setProperty("--fill", `${fill}%`);
  });
}

function starsFromPointer(e, btn) {
  const rect = btn.getBoundingClientRect();
  const starIndex = Number(btn.dataset.star);
  const isLeftHalf = e.clientX - rect.left < rect.width / 2;
  return isLeftHalf ? starIndex - 0.5 : starIndex;
}

function initRatingModal() {
  document.querySelectorAll("#star-rating .star-btn").forEach((btn) => {
    btn.addEventListener("mousemove", (e) => updateStarDisplay(starsFromPointer(e, btn)));
    btn.addEventListener("mouseleave", () => updateStarDisplay(ratingSelectedStars));
    btn.addEventListener("click", (e) => {
      ratingSelectedStars = starsFromPointer(e, btn);
      updateStarDisplay(ratingSelectedStars);
      $("star-rating-value").textContent = `${ratingSelectedStars} / 5`;
      $("rating-continue").disabled = ratingSelectedStars <= 0;
    });
  });

  $("rating-continue").addEventListener("click", () => {
    $("rating-step-stars").hidden = true;
    $("rating-step-comment").hidden = false;
    fitModalToViewport("modal-rating");
    $("rating-comment").focus();
  });

  const commentInput = $("rating-comment");
  const charCount = $("rating-char-count");
  const submitBtn = $("rating-submit");
  commentInput.addEventListener("input", () => {
    const len = commentInput.value.trim().length;
    charCount.textContent = `${len} / ${RATING_MIN_CHARS}`;
    charCount.classList.toggle("ok", len >= RATING_MIN_CHARS);
    submitBtn.disabled = len < RATING_MIN_CHARS;
  });

  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;
    const originalLabel = submitBtn.textContent;
    submitBtn.textContent = "Envoi…";
    try {
      await Api.submitRating(ratingSelectedStars, commentInput.value.trim());
    } catch (err) { /* the modal still closes -- nothing more the user can do about a failed send */ }
    submitBtn.textContent = originalLabel;
    $("rating-step-comment").hidden = true;
    $("rating-step-done").hidden = false;
    fitModalToViewport("modal-rating");
  });

  $("rating-close").addEventListener("click", () => closeModal("modal-rating"));
}

function openRatingModal() {
  ratingSelectedStars = 0;
  $("rating-step-stars").hidden = false;
  $("rating-step-comment").hidden = true;
  $("rating-step-done").hidden = true;
  updateStarDisplay(0);
  $("star-rating-value").textContent = "Survolez pour noter";
  $("rating-continue").disabled = true;
  $("rating-comment").value = "";
  $("rating-char-count").textContent = `0 / ${RATING_MIN_CHARS}`;
  $("rating-char-count").classList.remove("ok");
  $("rating-submit").disabled = true;
  openModal("modal-rating");
}

function startRatingFlowIfDue() {
  const appVersion = state.appVersion;
  const ratedVersion = state.settings.rated_version;
  if (!appVersion || ratedVersion === appVersion) return;
  setTimeout(openRatingModal, RATING_DELAY_MS);
}

/* ---------- start -> url ---------- */
function initStartScreen() {
  $("btn-start").addEventListener("click", () => {
    setPlatform(state.platform);
    showScreen("screen-url");
    setTimeout(() => $("url-input").focus(), 250);
  });
}

function setPlatform(platform) {
  state.platform = platform;
  // `.hidden` as a JS property is unreliable on <svg> elements in some engines
  // (only the HTML-specific mixin reliably supports it) -- toggleAttribute
  // works on any Element and correctly reflects to the [hidden] CSS selector.
  $("platform-icon-youtube").toggleAttribute("hidden", platform !== "youtube");
  $("platform-icon-tiktok").toggleAttribute("hidden", platform !== "tiktok");
  $("platform-icon-instagram").toggleAttribute("hidden", platform !== "instagram");
  $("url-input").placeholder = PLATFORM_PLACEHOLDER[platform];
  $("url-screen-subtitle").textContent = PLATFORM_SUBTITLE[platform];
  document.querySelectorAll(".platform-option").forEach((opt) => {
    opt.classList.toggle("active", opt.dataset.platform === platform);
  });
  $("app").classList.toggle("platform-youtube", platform === "youtube");
  $("app").classList.toggle("platform-tiktok", platform === "tiktok");
  $("app").classList.toggle("platform-instagram", platform === "instagram");
  $("url-input").dispatchEvent(new Event("input"));
}

function initPlatformPicker() {
  const btn = $("platform-picker-btn");
  const menu = $("platform-picker-menu");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
  });
  document.querySelectorAll(".platform-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      setPlatform(opt.dataset.platform);
      menu.hidden = true;
    });
  });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) menu.hidden = true;
  });
}

function initUrlScreen() {
  const input = $("url-input");
  const nextBtn = $("btn-url-next");
  input.addEventListener("input", () => {
    $("url-error").hidden = true;
    nextBtn.disabled = !PLATFORM_URL_RE[state.platform].test(input.value.trim());
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !nextBtn.disabled) nextBtn.click();
  });
  nextBtn.addEventListener("click", () => {
    state.url = input.value.trim();
    state.viaExtension = false;
    openConfirmModal(state.url, { autoConfirm: !state.alwaysConfirmVideo });
  });

  $("btn-paste").addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = text.trim();
        input.dispatchEvent(new Event("input"));
      }
    } catch (err) {
      /* clipboard unavailable — ignore silently */
    }
  });

  initPlatformPicker();

  document.querySelectorAll('[data-back]').forEach((btn) => {
    btn.addEventListener("click", () => showScreen(btn.dataset.back));
  });
}

/* ---------- confirmation modal ---------- */
function resetConfirmModal() {
  $("modal-loading").hidden = false;
  $("modal-content").hidden = true;
  $("modal-error").hidden = true;
  $("modal-confirm").querySelector(".modal").classList.remove("flip-out");
  document.querySelectorAll(".fetch-step").forEach((el) => el.classList.remove("active", "done"));
}

async function runFetchStagesAnimation(promise, stepsContainerId = "fetch-steps") {
  const stepEls = Array.from($(stepsContainerId).querySelectorAll(".fetch-step"));
  let i = 0;
  const activateNext = () => {
    if (i > 0) stepEls[i - 1].classList.replace("active", "done");
    if (i < stepEls.length) {
      stepEls[i].classList.add("active");
      i++;
    }
  };
  activateNext();
  const interval = setInterval(activateNext, 380);
  const minDelay = sleep(stepEls.length * 380);
  const [result] = await Promise.all([promise, minDelay]);
  clearInterval(interval);
  stepEls.forEach((el) => { el.classList.remove("active"); el.classList.add("done"); });
  return result;
}

async function openConfirmModal(url, options = {}) {
  resetConfirmModal();
  openModal("modal-confirm");

  const result = await runFetchStagesAnimation(Api.fetchVideoInfo(url));
  $("modal-loading").hidden = true;

  if (!result.ok) {
    $("modal-error").hidden = false;
    $("modal-error-text").textContent = result.error;
    return;
  }

  state.videoInfo = result.data;
  $("modal-thumb").src = result.data.thumbnail || "";
  $("modal-title").textContent = result.data.title;
  const meta = [result.data.uploader, formatDuration(result.data.duration)].filter(Boolean).join(" • ");
  $("modal-meta").textContent = meta;
  $("modal-content").hidden = false;

  if (options.autoConfirm) {
    await sleep(550);
    proceedToOptions();
  }
}

function proceedToOptions() {
  const modalEl = $("modal-confirm").querySelector(".modal");
  modalEl.classList.add("flip-out");
  setTimeout(() => {
    closeModal("modal-confirm");
    populateOptionsScreen();
    showScreen("screen-options");
    const card = $("options-card");
    card.classList.remove("flip-in-playing");
    void card.offsetWidth; // restart animation
    card.classList.add("flip-in-playing");
    card.addEventListener("animationend", () => card.classList.remove("flip-in-playing"), { once: true });
  }, 360);
}

function initConfirmModal() {
  $("modal-cancel").addEventListener("click", () => closeModal("modal-confirm"));
  $("modal-error-back").addEventListener("click", () => closeModal("modal-confirm"));
  $("modal-confirm-btn").addEventListener("click", proceedToOptions);

  const alwaysConfirmToggle = $("toggle-always-confirm");
  alwaysConfirmToggle.addEventListener("click", () => {
    state.alwaysConfirmVideo = !state.alwaysConfirmVideo;
    alwaysConfirmToggle.classList.toggle("on", state.alwaysConfirmVideo);
    alwaysConfirmToggle.setAttribute("aria-checked", String(state.alwaysConfirmVideo));
    Api.savePreference("always_confirm_video", state.alwaysConfirmVideo);
  });
}

/* ---------- external "open + download" requests (browser extension) ---------- */
function handleExternalDownload(url) {
  closeModal("modal-settings");
  showScreen("screen-url");
  setPlatform("youtube");
  $("url-input").value = url;
  $("url-input").dispatchEvent(new Event("input"));
  state.url = url;
  state.viaExtension = true;
  openConfirmModal(url, { autoConfirm: true });
}

/* ---------- options screen ---------- */
function maxAvailableHeight() {
  const heights = state.videoInfo?.available_heights || [];
  return heights.length ? Math.max(...heights) : Infinity;
}

function pickDefaultQuality() {
  const maxH = maxAvailableHeight();
  const remembered = state.settings.last_quality;
  if (remembered && state.qualityTiers[remembered]) {
    const h = state.qualityTiers[remembered].height;
    if (remembered === "auto" || h <= maxH) return remembered;
  }
  let best = "auto";
  for (const q of QUALITY_ORDER) {
    if (q === "auto") continue;
    const h = state.qualityTiers[q].height;
    if (h <= maxH && h <= 1080) best = q;
  }
  return best;
}

function renderQualityGrid() {
  const grid = $("quality-grid");
  grid.innerHTML = "";
  const maxH = maxAvailableHeight();
  QUALITY_ORDER.forEach((q) => {
    const tier = state.qualityTiers[q];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pill-btn";
    btn.textContent = tier.label;
    btn.dataset.value = q;
    const disabled = q !== "auto" && tier.height > maxH;
    btn.disabled = disabled;
    if (q === state.quality) btn.classList.add("active");
    btn.addEventListener("click", () => {
      state.quality = q;
      grid.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      syncBitrateForQuality(true);
      updateSizeEstimate();
    });
    grid.appendChild(btn);
  });
}

function renderFpsGrid() {
  const grid = $("fps-grid");
  grid.innerHTML = "";
  const maxFps = state.videoInfo?.max_fps || null;
  const choices = ["auto", ...state.fpsChoices, "manual"];

  choices.forEach((val) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pill-btn";
    btn.dataset.value = val;
    btn.textContent = val === "auto" ? "Auto" : val === "manual" ? "Manuel" : `${val} fps`;

    if (typeof val === "number" && maxFps && val > maxFps + 1) btn.disabled = true;

    const isActive = val === "manual" ? state.fpsIsManual : (!state.fpsIsManual && String(state.fps) === String(val));
    if (isActive) btn.classList.add("active");

    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      grid.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (val === "manual") {
        state.fpsIsManual = true;
        $("fps-manual-row").hidden = false;
        $("fps-manual-input").focus();
        state.fps = Number($("fps-manual-input").value) || 30;
      } else {
        state.fpsIsManual = false;
        $("fps-manual-row").hidden = true;
        state.fps = val;
      }
      syncBitrateForQuality(true);
    });
    grid.appendChild(btn);
  });

  $("fps-manual-row").hidden = !state.fpsIsManual;
}

function renderFormatGrid() {
  const grid = $("format-grid");
  grid.innerHTML = "";
  const choices = state.exportType === "audio_only" ? state.audioFormats : state.videoContainers;
  if (!choices.includes(state.outputFormat)) {
    state.outputFormat = choices[0];
  }
  choices.forEach((fmt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pill-btn";
    btn.textContent = fmt.toUpperCase();
    btn.dataset.value = fmt;
    if (fmt === state.outputFormat) btn.classList.add("active");
    btn.addEventListener("click", () => {
      state.outputFormat = fmt;
      grid.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
    grid.appendChild(btn);
  });
}

/* Approximate fps-aware bitrate multiplier (higher fps needs more bits for the same perceived quality). */
function fpsFactor() {
  let fps = state.fps === "auto" ? (state.videoInfo?.max_fps || 30) : Number(state.fps);
  if (!fps || Number.isNaN(fps)) fps = 30;
  return Math.min(2, Math.max(0.6, fps / 30));
}

function currentSliderPercent() {
  const slider = $("bitrate-slider");
  const min = Number(slider.min), max = Number(slider.max), val = Number(slider.value);
  return max > min ? (val - min) / (max - min) : 0.5;
}

function syncBitrateForQuality(animate) {
  const slider = $("bitrate-slider");
  const isAuto = state.quality === "auto";
  slider.disabled = isAuto;

  if (isAuto) {
    $("bitrate-hint").textContent = "Débit automatique : la meilleure qualité disponible sera utilisée.";
    $("bitrate-hint").classList.remove("warn");
    $("bitrate-value").textContent = "Auto";
    return;
  }

  const prevPercent = currentSliderPercent();

  let newMin, newMax, newStep, target;
  if (state.exportType === "audio_only") {
    newMin = 64; newMax = 320; newStep = 8;
    target = state.recommendedAudioKbps;
  } else {
    const rec = Math.round(state.qualityTiers[state.quality].recommended_kbps * fpsFactor());
    newMin = Math.round(rec * 0.3);
    newMax = Math.round(rec * 2);
    newStep = Math.max(10, Math.round(rec * 0.02));
    target = rec;
  }

  slider.min = newMin;
  slider.max = newMax;
  slider.step = newStep;
  state.bitrate = target;

  if (animate) {
    const startValue = newMin + prevPercent * (newMax - newMin);
    slider.value = startValue;
    updateBitrateDisplay();
    animateValue(startValue, target, 350, (v) => {
      slider.value = v;
      updateBitrateDisplay();
    });
  } else {
    slider.value = target;
    updateBitrateDisplay();
  }
}

function updateBitrateDisplay() {
  const slider = $("bitrate-slider");
  if (state.quality === "auto") return;
  const min = Number(slider.min), max = Number(slider.max), val = Number(slider.value);
  const pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
  slider.style.setProperty("--fill", `${pct}%`);
  $("bitrate-value").textContent = `${Math.round(val)} kbps`;
  state.bitrate = Math.round(val);

  const hint = $("bitrate-hint");
  if (state.exportType === "audio_only") {
    hint.textContent = "Débit audio cible pour l'export.";
    hint.classList.remove("warn");
  } else {
    const rec = Math.round(state.qualityTiers[state.quality].recommended_kbps * fpsFactor());
    const deviates = Math.abs(val - rec) / rec > 0.15;
    if (deviates) {
      hint.textContent = "Cette valeur nécessitera un réencodage (plus lent).";
      hint.classList.add("warn");
    } else {
      hint.textContent = `Débit recommandé pour ${state.qualityTiers[state.quality].label} à ce fps : ${rec} kbps.`;
      hint.classList.remove("warn");
    }
  }
}

function updateSizeEstimate() {
  const el = $("size-estimate");
  const info = state.videoInfo;
  if (!info) { el.textContent = ""; return; }

  if (state.exportType === "audio_only") {
    el.textContent = info.best_audio_size ? `Taille estimée : ~${formatBytes(info.best_audio_size)}` : "";
    return;
  }
  if (state.quality === "auto") {
    const sizes = Object.values(info.size_by_height || {});
    const max = sizes.length ? Math.max(...sizes) : null;
    el.textContent = max ? `Taille estimée : ~${formatBytes(max)}` : "";
    return;
  }
  const height = state.qualityTiers[state.quality].height;
  const size = (info.size_by_height || {})[String(height)];
  el.textContent = size ? `Taille estimée : ~${formatBytes(size)}` : "";
}

function setExportType(type) {
  state.exportType = type;
  document.querySelectorAll("#export-type .export-card").forEach((b) => {
    b.classList.toggle("active", b.dataset.value === type);
  });
  $("quality-grid").closest(".option-block").hidden = type === "audio_only";
  $("fps-block").hidden = type === "audio_only";
  renderFormatGrid();
  syncBitrateForQuality(false);
  updateSizeEstimate();
}

function populateOptionsScreen() {
  const info = state.videoInfo;
  $("recap-thumb").src = info.thumbnail || "";
  $("recap-title").textContent = info.title;
  $("recap-meta").textContent = formatDuration(info.duration);

  state.quality = pickDefaultQuality();
  // Clicking "Télécharger" on a YouTube video means the video -- ignore a
  // remembered "audio only" from a previous, unrelated manual download so
  // quality/fps controls aren't unexpectedly hidden.
  state.exportType = state.viaExtension ? "video_audio" : (state.settings.last_export_type || "video_audio");
  state.outputFormat = state.settings.last_output_format || "mp4";
  const rememberedFps = state.settings.last_fps;
  if (rememberedFps && rememberedFps !== "auto" && !isNaN(Number(rememberedFps))) {
    state.fps = Number(rememberedFps);
    state.fpsIsManual = !state.fpsChoices.includes(state.fps);
  } else {
    state.fps = "auto";
    state.fpsIsManual = false;
  }

  renderQualityGrid();
  renderFpsGrid();
  setExportType(state.exportType);

  if (!$("dest-input").value) {
    $("dest-input").value = state.destDir;
  }
}

function initOptionsScreen() {
  document.querySelectorAll("#export-type .export-card").forEach((btn) => {
    btn.addEventListener("click", () => setExportType(btn.dataset.value));
  });

  $("bitrate-slider").addEventListener("input", updateBitrateDisplay);
  $("fps-manual-input").addEventListener("input", (e) => {
    state.fps = Number(e.target.value) || 30;
    syncBitrateForQuality(true);
  });

  $("btn-browse").addEventListener("click", async () => {
    const folder = await Api.pickFolder();
    if (folder) {
      state.destDir = folder;
      $("dest-input").value = folder;
    }
  });

  $("btn-options-next").addEventListener("click", () => {
    if (!state.destDir) {
      state.destDir = $("dest-input").value || state.settings.last_download_dir;
    }
    beginDownloadProcess();
  });
}

/* ---------- ffmpeg modal ---------- */
function askInstallFfmpeg() {
  return new Promise((resolve) => {
    $("ffmpeg-ask").hidden = false;
    $("ffmpeg-installing").hidden = true;
    $("ffmpeg-manual").hidden = true;
    openModal("modal-ffmpeg");

    const onAccept = async () => {
      $("ffmpeg-ask").hidden = true;
      $("ffmpeg-installing").hidden = false;
      $("ffmpeg-progress-fill").style.width = "0%";
      $("ffmpeg-progress-label").textContent = "Téléchargement…";

      const progressHandler = (payload) => {
        if (payload.stage === "downloading" && payload.percent >= 0) {
          $("ffmpeg-progress-fill").style.width = `${payload.percent}%`;
          $("ffmpeg-progress-label").textContent = `Téléchargement… ${payload.percent}%`;
        } else if (payload.stage === "extracting") {
          $("ffmpeg-progress-fill").style.width = "100%";
          $("ffmpeg-progress-label").textContent = "Extraction…";
        }
      };
      Api.on("ffmpeg_progress", progressHandler);

      const result = await Api.installFfmpeg();
      Api.off("ffmpeg_progress", progressHandler);

      if (result.ok) {
        closeModal("modal-ffmpeg");
        resolve(true);
      } else {
        $("ffmpeg-installing").hidden = true;
        $("ffmpeg-manual").hidden = false;
        $("ffmpeg-manual").querySelector(".modal-meta").textContent =
          `L'installation automatique a échoué (${result.error}). Installez FFmpeg manuellement puis réessayez.`;
      }
    };

    const onDecline = () => {
      $("ffmpeg-ask").hidden = true;
      $("ffmpeg-manual").hidden = false;
    };

    const onRetry = async () => {
      const installed = await Api.checkFfmpeg();
      if (installed) {
        closeModal("modal-ffmpeg");
        resolve(true);
      } else {
        $("ffmpeg-manual").hidden = true;
        $("ffmpeg-ask").hidden = false;
      }
    };

    $("ffmpeg-accept").onclick = onAccept;
    $("ffmpeg-decline").onclick = onDecline;
    $("ffmpeg-retry").onclick = onRetry;
  });
}

/* ---------- live scrubbing preview (yt-dlp storyboards) ---------- */
const spriteCache = {};
const spritePending = new Set();

function findStoryboardTile(storyboard, timestamp) {
  const fragments = storyboard.fragments;
  let cumulative = 0;
  for (const frag of fragments) {
    const dur = frag.duration || 0;
    if (timestamp < cumulative + dur || frag === fragments[fragments.length - 1]) {
      const localTime = Math.max(0, timestamp - cumulative);
      const tilesPerFragment = storyboard.rows * storyboard.columns;
      let tileInFragment = Math.floor(localTime * storyboard.fps);
      tileInFragment = Math.max(0, Math.min(tilesPerFragment - 1, tileInFragment));
      const row = Math.floor(tileInFragment / storyboard.columns);
      const col = tileInFragment % storyboard.columns;
      return { url: frag.url, row, col };
    }
    cumulative += dur;
  }
  return null;
}

function renderStoryboardTile(tile) {
  const wrap = $("preview-image-wrap");
  const frame = $("preview-frame");
  const w = wrap.clientWidth || 320;
  const h = wrap.clientHeight || 180;
  const sb = state.videoInfo.storyboard;
  frame.style.backgroundImage = `url("${spriteCache[tile.url]}")`;
  frame.style.backgroundSize = `${sb.columns * w}px ${sb.rows * h}px`;
  frame.style.backgroundPosition = `-${tile.col * w}px -${tile.row * h}px`;
  frame.hidden = false;
}

function updatePreviewFrame(progressFraction) {
  const info = state.videoInfo;
  const sb = info?.storyboard;
  if (!sb || !info.duration) return;

  const timestamp = Math.max(0, Math.min(info.duration, progressFraction * info.duration));
  const tile = findStoryboardTile(sb, timestamp);
  if (!tile) return;

  if (spriteCache[tile.url]) {
    renderStoryboardTile(tile);
    return;
  }
  if (spritePending.has(tile.url)) return;
  spritePending.add(tile.url);
  Api.getStoryboardSprite(tile.url).then((res) => {
    spritePending.delete(tile.url);
    if (res.ok) {
      spriteCache[tile.url] = res.data;
      renderStoryboardTile(tile);
    }
  });
}

/* ---------- progress screen ---------- */
function setStep(name, status) {
  const li = document.querySelector(`.step[data-step="${name}"]`);
  li.classList.remove("active", "done");
  if (status) li.classList.add(status);
}

function resetProgressScreen() {
  ["ffmpeg", "init", "probe", "download"].forEach((s) => setStep(s, null));
  $("progress-bar-fill").style.width = "0%";
  $("progress-percent").textContent = "0%";
  $("progress-speed").textContent = "";
  $("progress-eta").textContent = "";
  $("progress-title").textContent = "Téléchargement en cours";
  const stopBtn = $("btn-stop");
  stopBtn.hidden = false;
  stopBtn.disabled = false;
  stopBtn.lastChild.textContent = " Arrêter le téléchargement";

  const stepsEl = $("progress-steps");
  stepsEl.classList.remove("steps-enter");
  void stepsEl.offsetWidth;
  stepsEl.classList.add("steps-enter");

  $("preview-frame").hidden = true;
  $("preview-frame").style.backgroundImage = "";
}

function showPreviewPanel() {
  const panel = $("preview-panel");
  if (!state.showPreview || !state.videoInfo) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("preview-image").src = state.videoInfo.thumbnail || "";
  $("preview-title").textContent = state.videoInfo.title || "";
}

function abortToOptions() {
  showScreen("screen-options");
}

async function beginDownloadProcess() {
  cancelRequested = false;
  resetProgressScreen();
  showPreviewPanel();
  showScreen("screen-progress");

  setStep("ffmpeg", "active");
  const hasFfmpeg = await Api.checkFfmpeg();
  if (cancelRequested) return abortToOptions();
  if (!hasFfmpeg) {
    const installed = await askInstallFfmpeg();
    if (cancelRequested) return abortToOptions();
    if (!installed) {
      showResult("error", "Installation annulée", "FFmpeg est requis pour continuer le téléchargement.");
      return;
    }
  }
  setStep("ffmpeg", "done");

  setStep("init", "active");
  await sleep(300);
  if (cancelRequested) return abortToOptions();
  setStep("init", "done");

  setStep("probe", "active");
  await sleep(250);
  if (cancelRequested) return abortToOptions();
  setStep("probe", "done");

  setStep("download", "active");
  runDownload();
}

function runDownload() {
  let settled = false;
  const downloadStart = performance.now();

  const progressHandler = (payload) => {
    if (payload.status === "downloading") {
      const total = payload.total_bytes;
      const downloaded = payload.downloaded_bytes || 0;
      const pct = total ? Math.min(100, Math.round((downloaded / total) * 100)) : 0;
      $("progress-bar-fill").style.width = `${pct}%`;
      $("progress-percent").textContent = total ? `${pct}%` : formatBytes(downloaded);
      $("progress-speed").textContent = formatSpeed(payload.speed);
      $("progress-eta").textContent = payload.eta !== null && payload.eta !== undefined ? `ETA ${formatEta(payload.eta)}` : "";
      if (total) updatePreviewFrame(downloaded / total);
    } else if (payload.status === "finished") {
      $("progress-bar-fill").style.width = "100%";
      $("progress-percent").textContent = "100%";
      $("progress-eta").textContent = "Finalisation…";
    }
  };

  const completeHandler = (payload) => {
    if (settled) return;
    settled = true;
    cleanup();
    setStep("download", "done");
    const elapsed = payload.elapsed !== undefined ? payload.elapsed : (performance.now() - downloadStart) / 1000;
    showResult("success", "Téléchargement terminé", `Terminé en ${elapsed.toFixed(1)} s`, payload.filepath);
    state.viaExtension = false;
    if (payload.total_downloads !== undefined) state.settings.total_downloads = payload.total_downloads;
  };

  const errorHandler = (payload) => {
    if (settled) return;
    settled = true;
    cleanup();
    showResult("error", "Échec du téléchargement", payload.error);
    state.viaExtension = false;
  };

  const cancelledHandler = () => {
    if (settled) return;
    settled = true;
    cleanup();
    showResult("cancelled", "Téléchargement annulé", "Les fichiers temporaires ont été supprimés.");
    state.viaExtension = false;
  };

  function cleanup() {
    Api.off("download_progress", progressHandler);
    Api.off("download_complete", completeHandler);
    Api.off("download_error", errorHandler);
    Api.off("download_cancelled", cancelledHandler);
  }

  Api.on("download_progress", progressHandler);
  Api.on("download_complete", completeHandler);
  Api.on("download_error", errorHandler);
  Api.on("download_cancelled", cancelledHandler);

  Api.startDownload(state.url, {
    quality: state.quality,
    fps: state.fps,
    export_type: state.exportType,
    bitrate: state.bitrate,
    dest_dir: state.destDir,
    output_format: state.outputFormat,
    cookies_browser_hint: state.videoInfo?.cookies_browser_used || null,
  });
}

function initStopButton() {
  $("btn-stop").addEventListener("click", async () => {
    cancelRequested = true;
    $("btn-stop").disabled = true;
    $("btn-stop").lastChild.textContent = " Annulation…";
    const downloadActive = document.querySelector('.step[data-step="download"]').classList.contains("active");
    if (downloadActive) {
      await Api.cancelDownload();
    } else {
      showScreen("screen-options");
    }
  });
}

/* ---------- confetti ---------- */
function runConfetti(durationSeconds) {
  const canvas = $("confetti-canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  canvas.hidden = false;

  const colors = ["#ff3366", "#7c5cff", "#22d3c5", "#ffb648", "#ffffff"];
  const particles = Array.from({ length: 140 }, () => ({
    x: Math.random() * canvas.width,
    y: -20 - Math.random() * canvas.height * 0.15,
    r: 4 + Math.random() * 5,
    color: colors[Math.floor(Math.random() * colors.length)],
    vy: 0.6 + Math.random() * 1,
    vx: (Math.random() - 0.5) * 1,
    rotation: Math.random() * 360,
    vr: (Math.random() - 0.5) * 5,
    shape: Math.random() > 0.5 ? "rect" : "circle",
  }));

  const start = performance.now();
  const spawnMs = durationSeconds * 1000;
  const fadeMs = 900;
  let stopped = false;

  function frame(now) {
    if (stopped) return;
    const elapsed = now - start;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const fadeStart = spawnMs;
    const globalAlpha = elapsed < fadeStart ? 1 : Math.max(0, 1 - (elapsed - fadeStart) / fadeMs);

    particles.forEach((p) => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.008;
      p.vy = Math.min(p.vy, 2.2);
      p.rotation += p.vr;
      if (p.y > canvas.height + 20) {
        p.y = -20;
        p.x = Math.random() * canvas.width;
      }
      ctx.save();
      ctx.globalAlpha = globalAlpha;
      ctx.translate(p.x, p.y);
      ctx.rotate((p.rotation * Math.PI) / 180);
      ctx.fillStyle = p.color;
      if (p.shape === "rect") {
        ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 1.6);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, p.r / 2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    });

    if (elapsed < spawnMs + fadeMs) {
      requestAnimationFrame(frame);
    } else {
      canvas.hidden = true;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }
  requestAnimationFrame(frame);

  return () => { stopped = true; canvas.hidden = true; };
}

/* ---------- result screen ---------- */
const CHECK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.5l5.5 5.5L20 6"/></svg>';

function showResult(kind, title, text, filepath) {
  $("btn-stop").hidden = true;
  showScreen("screen-result");
  const icon = $("result-icon");
  icon.className = `result-icon ${kind}`;
  if (kind === "success") {
    icon.innerHTML = CHECK_ICON;
    runConfetti(state.confettiSeconds);
    if (state.sfxEnabled) playDownloadCompleteSfx();
  } else {
    icon.textContent = kind === "cancelled" ? "!" : "✕";
  }
  $("result-title").textContent = title;
  $("result-text").textContent = text;

  const actions = $("result-actions");
  actions.innerHTML = "";

  if (kind === "success") {
    const openBtn = document.createElement("button");
    openBtn.className = "btn-secondary";
    openBtn.textContent = "Ouvrir le dossier";
    openBtn.addEventListener("click", () => Api.openFolder(state.destDir));
    actions.appendChild(openBtn);

    if (filepath) {
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn-secondary";
      copyBtn.textContent = "Copier le chemin";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(filepath);
          const original = copyBtn.textContent;
          copyBtn.textContent = "Copié !";
          setTimeout(() => { copyBtn.textContent = original; }, 1500);
        } catch (err) { /* ignore */ }
      });
      actions.appendChild(copyBtn);
    }
  }

  const restartBtn = document.createElement("button");
  restartBtn.className = "btn-primary";
  restartBtn.textContent = "Télécharger une autre vidéo";
  restartBtn.addEventListener("click", () => {
    state.url = "";
    state.videoInfo = null;
    $("url-input").value = "";
    $("btn-url-next").disabled = true;
    showScreen("screen-url");
  });
  actions.appendChild(restartBtn);
}

/* ---------- startup splash ---------- */
function createReverbImpulse(ctx, duration = 1.6, decay = 2.4) {
  const rate = ctx.sampleRate;
  const length = Math.floor(rate * duration);
  const impulse = ctx.createBuffer(2, length, rate);
  for (let ch = 0; ch < 2; ch++) {
    const data = impulse.getChannelData(ch);
    for (let i = 0; i < length; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, decay);
    }
  }
  return impulse;
}

function renderStartupChime(ctx) {
  const now = ctx.currentTime;
  const master = ctx.createGain();
  master.gain.value = 1;
  master.connect(ctx.destination);

  // Reverb send: gives the tail a sense of space instead of stopping dead
  // the instant each note's envelope ends, which is most of what makes this
  // read as "one longer sound" rather than a handful of separate beeps.
  const convolver = ctx.createConvolver();
  convolver.buffer = createReverbImpulse(ctx);
  const wetGain = ctx.createGain();
  wetGain.gain.value = 0.35;
  convolver.connect(wetGain).connect(master);

  const dryGain = ctx.createGain();
  dryGain.connect(master);
  dryGain.connect(convolver);

  // Ascending arpeggio (C4-E4-G4-C5) that builds into a held chord rather
  // than firing as separate notes.
  [
    { freq: 261.63, start: 0.0, dur: 1.6, gain: 0.11 },
    { freq: 329.63, start: 0.14, dur: 1.5, gain: 0.11 },
    { freq: 392.0, start: 0.28, dur: 1.4, gain: 0.12 },
    { freq: 523.25, start: 0.42, dur: 1.3, gain: 0.14 },
  ].forEach(({ freq, start, dur, gain }) => {
    // Warm sine fundamental.
    const osc1 = ctx.createOscillator();
    osc1.type = "sine";
    osc1.frequency.value = freq;
    const g1 = ctx.createGain();
    g1.gain.setValueAtTime(0.0001, now + start);
    g1.gain.linearRampToValueAtTime(gain, now + start + 0.08);
    g1.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
    osc1.connect(g1).connect(dryGain);
    osc1.start(now + start);
    osc1.stop(now + start + dur + 0.1);

    // Quieter octave-up triangle layer for a bit of texture/brightness.
    const osc2 = ctx.createOscillator();
    osc2.type = "triangle";
    osc2.frequency.value = freq * 2;
    const g2 = ctx.createGain();
    g2.gain.setValueAtTime(0.0001, now + start);
    g2.gain.linearRampToValueAtTime(gain * 0.28, now + start + 0.08);
    g2.gain.exponentialRampToValueAtTime(0.0001, now + start + dur * 0.8);
    osc2.connect(g2).connect(dryGain);
    osc2.start(now + start);
    osc2.stop(now + start + dur + 0.1);
  });
}

function playStartupChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    let played = false;
    const start = () => {
      if (played) return;
      played = true;
      renderStartupChime(ctx);
    };

    if (ctx.state === "running") {
      start();
      return;
    }
    // Autoplay is blocked until a user gesture in some environments --
    // try resuming right away (harmless if ignored), and otherwise fall
    // back to the first click/keypress so the chime still lands right as
    // the app becomes interactive instead of never playing at all.
    ctx.resume().then(() => { if (ctx.state === "running") start(); }).catch(() => {});
    const onFirstGesture = () => {
      document.removeEventListener("pointerdown", onFirstGesture);
      document.removeEventListener("keydown", onFirstGesture);
      ctx.resume().finally(start);
    };
    document.addEventListener("pointerdown", onFirstGesture, { once: true });
    document.addEventListener("keydown", onFirstGesture, { once: true });
  } catch (err) { /* Web Audio unavailable -- a missing chime is harmless */ }
}

function playDownloadCompleteSfx() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;
    const master = ctx.createGain();
    master.gain.value = 1;
    master.connect(ctx.destination);

    // Bright ascending flourish (E5-G#5-B5-E6) with a sparkly octave-up
    // layer on each note -- an upbeat "done!" cue, not a long fanfare.
    [
      { freq: 659.25, start: 0.0, dur: 0.22, gain: 0.16 },
      { freq: 830.61, start: 0.09, dur: 0.22, gain: 0.16 },
      { freq: 987.77, start: 0.18, dur: 0.28, gain: 0.17 },
      { freq: 1318.51, start: 0.3, dur: 0.55, gain: 0.2 },
    ].forEach(({ freq, start, dur, gain }) => {
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.value = freq;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, now + start);
      g.gain.linearRampToValueAtTime(gain, now + start + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
      osc.connect(g).connect(master);
      osc.start(now + start);
      osc.stop(now + start + dur + 0.05);

      const sparkle = ctx.createOscillator();
      sparkle.type = "sine";
      sparkle.frequency.value = freq * 2;
      const gs = ctx.createGain();
      gs.gain.setValueAtTime(0.0001, now + start);
      gs.gain.linearRampToValueAtTime(gain * 0.35, now + start + 0.02);
      gs.gain.exponentialRampToValueAtTime(0.0001, now + start + dur * 0.6);
      sparkle.connect(gs).connect(master);
      sparkle.start(now + start);
      sparkle.stop(now + start + dur + 0.05);
    });
  } catch (err) { /* Web Audio unavailable -- a missing sfx is harmless */ }
}

function setSplashProgress(pct) {
  $("splash-progress-fill").style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function hideSplashScreen() {
  $("splash-screen").classList.add("hidden");
}

/* ---------- init ---------- */
async function init() {
  // The window itself is already visible with the splash on top by the time
  // this runs -- the bar below is driven by real init milestones completing
  // (not a fixed timer), so it never claims progress that hasn't happened.
  setSplashProgress(4);

  initStartScreen();
  initUrlScreen();
  initConfirmModal();
  initOptionsScreen();
  initSettingsModal();
  initExtensionInstallModal();
  initAppUpdateModal();
  initChangelogModal();
  initWelcomeModal();
  initRatingModal();
  initStopButton();
  setSplashProgress(15);

  const settings = await Api.getSettings();
  state.settings = settings;
  state.qualityTiers = settings.quality_tiers;
  state.fpsChoices = settings.fps_choices;
  state.videoContainers = settings.video_containers;
  state.audioFormats = settings.audio_formats;
  state.recommendedAudioKbps = settings.recommended_audio_kbps;
  state.destDir = settings.last_download_dir;
  state.showPreview = settings.show_preview !== false;
  state.confettiSeconds = settings.confetti_seconds || 5;
  state.sfxEnabled = settings.sfx_enabled !== false;
  state.alwaysConfirmVideo = settings.always_confirm_video !== false;
  setSplashProgress(45);

  const previewToggle = $("toggle-preview");
  previewToggle.classList.toggle("on", state.showPreview);
  previewToggle.setAttribute("aria-checked", String(state.showPreview));
  $("confetti-seconds-input").value = state.confettiSeconds;
  const sfxToggle = $("toggle-sfx");
  sfxToggle.classList.toggle("on", state.sfxEnabled);
  sfxToggle.setAttribute("aria-checked", String(state.sfxEnabled));
  const alwaysConfirmToggle = $("toggle-always-confirm");
  alwaysConfirmToggle.classList.toggle("on", state.alwaysConfirmVideo);
  alwaysConfirmToggle.setAttribute("aria-checked", String(state.alwaysConfirmVideo));

  initTheme(settings.theme);

  Api.on("extension_linked", () => showToast("Extension liée avec succès"));
  Api.on("open_download", (payload) => handleExternalDownload(payload.url));
  Api.on("extension_auto_synced", (payload) =>
    showToast(`Extension mise à jour (v${payload.version}) — rechargez-la (icône ↻ dans la page des extensions) puis actualisez vos onglets YouTube.`, 12000)
  );

  if (state.sfxEnabled) playStartupChime();
  setSplashProgress(55);

  try {
    await Api.getFfmpegStatus();
  } catch (err) { /* non-fatal -- settings screen re-checks this on its own */ }
  setSplashProgress(75);

  await checkWelcomeMessage();
  setSplashProgress(88);

  await checkForUpdateOnStartup();
  setSplashProgress(100);

  hideSplashScreen();
  startRatingFlowIfDue();
}

document.addEventListener("DOMContentLoaded", init);

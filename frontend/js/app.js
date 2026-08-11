/* Screen state machine + UI wiring for Downloader Youtube. */

const QUALITY_ORDER = ["auto", "144p", "480p", "720p", "1080p", "1440p", "2160p"];
const YT_URL_RE = /^https?:\/\/(www\.)?(youtube\.com\/(watch\?v=|shorts\/)|youtu\.be\/)[\w-]+/i;

const state = {
  settings: null,
  qualityTiers: {},
  fpsChoices: [10, 24, 50, 60],
  videoContainers: ["mp4", "mkv", "webm"],
  audioFormats: ["mp3", "m4a", "wav", "opus"],
  recommendedAudioKbps: 192,
  confettiSeconds: 5,
  url: "",
  videoInfo: null,
  quality: "1080p",
  fps: "auto",
  fpsIsManual: false,
  exportType: "video_audio",
  outputFormat: "mp4",
  bitrate: 0,
  destDir: "",
  showPreview: true,
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

function openModal(id) { $(id).classList.add("active"); }
function closeModal(id) { $(id).classList.remove("active"); }

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

  $("settings-toggle").addEventListener("click", refreshCookiesFileStatus);
  $("btn-import-cookies").addEventListener("click", async () => {
    const btn = $("btn-import-cookies");
    btn.disabled = true;
    const result = await Api.importCookiesFile();
    if (!result.ok && result.error) {
      $("cookies-file-status").textContent = `Échec de l'import : ${result.error}`;
    }
    await refreshCookiesFileStatus();
    btn.disabled = false;
  });
  $("btn-clear-cookies").addEventListener("click", async () => {
    await Api.clearCookiesFile();
    await refreshCookiesFileStatus();
  });
}

async function refreshCookiesFileStatus() {
  const statusText = $("cookies-file-status");
  const clearBtn = $("btn-clear-cookies");
  const status = await Api.getCookiesFileStatus();
  if (status.imported) {
    statusText.textContent = "Fichier cookies.txt importé et actif.";
    clearBtn.hidden = false;
  } else {
    statusText.textContent = "Aucun fichier importé.";
    clearBtn.hidden = true;
  }
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
}

/* ---------- start -> url ---------- */
function initStartScreen() {
  $("btn-start").addEventListener("click", () => {
    showScreen("screen-url");
    setTimeout(() => $("url-input").focus(), 250);
  });
}

function initUrlScreen() {
  const input = $("url-input");
  const nextBtn = $("btn-url-next");
  input.addEventListener("input", () => {
    $("url-error").hidden = true;
    nextBtn.disabled = !YT_URL_RE.test(input.value.trim());
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !nextBtn.disabled) nextBtn.click();
  });
  nextBtn.addEventListener("click", () => {
    state.url = input.value.trim();
    openConfirmModal(state.url);
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

async function runFetchStagesAnimation(promise) {
  const stepEls = Array.from(document.querySelectorAll(".fetch-step"));
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

async function openConfirmModal(url) {
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
}

function initConfirmModal() {
  $("modal-cancel").addEventListener("click", () => closeModal("modal-confirm"));
  $("modal-error-back").addEventListener("click", () => closeModal("modal-confirm"));
  $("modal-confirm-btn").addEventListener("click", () => {
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
  });
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
  state.exportType = state.settings.last_export_type || "video_audio";
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
  };

  const errorHandler = (payload) => {
    if (settled) return;
    settled = true;
    cleanup();
    showResult("error", "Échec du téléchargement", payload.error);
  };

  const cancelledHandler = () => {
    if (settled) return;
    settled = true;
    cleanup();
    showResult("cancelled", "Téléchargement annulé", "Les fichiers temporaires ont été supprimés.");
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

/* ---------- tutorial (first run only) ---------- */
function initTutorial() {
  const slides = Array.from(document.querySelectorAll(".tutorial-slide"));
  const dotsWrap = $("tutorial-dots");
  let index = 0;

  dotsWrap.innerHTML = "";
  slides.forEach((_, i) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "tutorial-dot";
    dot.addEventListener("click", () => goTo(i));
    dotsWrap.appendChild(dot);
  });
  const dots = Array.from(dotsWrap.children);

  function render() {
    slides.forEach((el, i) => el.classList.toggle("active", i === index));
    dots.forEach((el, i) => el.classList.toggle("active", i === index));
    $("tutorial-next").textContent = index === slides.length - 1 ? "Commencer" : "Suivant";
  }

  function goTo(i) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    render();
  }

  return function showTutorial() {
    return new Promise((resolve) => {
      index = 0;
      render();
      openModal("modal-tutorial");

      const finish = () => {
        Api.markTutorialSeen();
        closeModal("modal-tutorial");
        $("tutorial-next").onclick = null;
        $("tutorial-skip").onclick = null;
        resolve();
      };

      $("tutorial-next").onclick = () => {
        if (index === slides.length - 1) {
          finish();
        } else {
          goTo(index + 1);
        }
      };
      $("tutorial-skip").onclick = finish;
    });
  };
}

/* ---------- auto-update ---------- */
let pendingUpdate = null;

function resetUpdateModal() {
  $("update-ask").hidden = false;
  $("update-downloading").hidden = true;
  $("update-restarting").hidden = true;
  $("update-failed").hidden = true;
  $("update-progress-fill").style.width = "0%";
  $("update-progress-label").textContent = "0%";
  $("update-install").disabled = false;
}

function initUpdateModal() {
  $("update-later").addEventListener("click", () => closeModal("modal-update"));
  $("update-failed-close").addEventListener("click", () => closeModal("modal-update"));

  $("update-install").addEventListener("click", async () => {
    if (!pendingUpdate) return;
    $("update-install").disabled = true;
    $("update-ask").hidden = true;
    $("update-downloading").hidden = false;

    const progressHandler = (payload) => {
      const pct = payload.percent || 0;
      $("update-progress-fill").style.width = `${pct}%`;
      $("update-progress-label").textContent = `${pct}%`;
    };
    Api.on("update_download_progress", progressHandler);

    const dl = await Api.downloadUpdate(pendingUpdate.download_url);
    Api.off("update_download_progress", progressHandler);

    if (!dl.ok) {
      $("update-downloading").hidden = true;
      $("update-failed").hidden = false;
      $("update-error-text").textContent = dl.error || "Erreur inconnue lors du téléchargement.";
      return;
    }

    $("update-downloading").hidden = true;
    $("update-restarting").hidden = false;

    const install = await Api.installUpdate(dl.path);
    if (!install.ok) {
      $("update-restarting").hidden = true;
      $("update-failed").hidden = false;
      $("update-error-text").textContent = install.error || "Erreur inconnue lors de l'installation.";
    }
    /* on success the app process exits itself; nothing left to do here */
  });
}

async function checkForUpdateOnStartup() {
  const result = await Api.checkForUpdate();
  if (!result.available) return;
  pendingUpdate = result;
  resetUpdateModal();
  $("update-version-text").textContent = `Version ${result.version} disponible.`;
  $("update-notes").textContent = result.notes || "";
  openModal("modal-update");
}

/* ---------- init ---------- */
async function init() {
  initStartScreen();
  initUrlScreen();
  initConfirmModal();
  initOptionsScreen();
  initSettingsModal();
  initStopButton();
  initUpdateModal();
  const showTutorial = initTutorial();

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

  const toggle = $("toggle-preview");
  toggle.classList.toggle("on", state.showPreview);
  toggle.setAttribute("aria-checked", String(state.showPreview));
  $("confetti-seconds-input").value = state.confettiSeconds;

  initTheme(settings.theme);

  if (!settings.tutorial_seen) {
    await showTutorial();
  }
  checkForUpdateOnStartup();
}

document.addEventListener("DOMContentLoaded", init);

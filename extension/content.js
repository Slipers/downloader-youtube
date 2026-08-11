// Injects a "Télécharger" button next to the Subscribe button on YouTube watch/shorts pages.
const BUTTON_ID = "ytdls-download-btn";

const DOWNLOAD_ICON = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 19h16"/></svg>`;

const SUBSCRIBE_SELECTORS = [
  "ytd-watch-metadata #subscribe-button",
  "ytd-watch-metadata ytd-subscribe-button-renderer",
  "#below #subscribe-button",
  "#top-row #subscribe-button",
  "#subscribe-button",
];

const SUBSCRIBE_LABEL_RE = /^s['’]abonner|^subscribe/i;

function isVisible(el) {
  return !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
}

function isOnVideoPage() {
  return /\/(watch|shorts\/)/.test(location.pathname);
}

// Structural IDs/tag names first (fast, precise); if YouTube's markup for
// this layout/experiment/browser doesn't match any of those, fall back to
// finding whatever control is actually labelled "Subscribe" -- far more
// resilient to markup churn than chasing exact selectors.
function findSubscribeAnchor() {
  if (!isOnVideoPage()) return null;

  for (const selector of SUBSCRIBE_SELECTORS) {
    for (const el of document.querySelectorAll(selector)) {
      if (isVisible(el)) return el;
    }
  }

  const candidates = document.querySelectorAll(
    "button, yt-button-shape, tp-yt-paper-button, ytd-subscribe-button-renderer, a"
  );
  for (const el of candidates) {
    const label = (el.getAttribute("aria-label") || el.textContent || "").trim();
    if (!label || !SUBSCRIBE_LABEL_RE.test(label) || !isVisible(el)) continue;
    // Anchor next to a reasonably-sized wrapper, not the raw <button> itself,
    // so our pill sits alongside it rather than inside a tightly-packed shape.
    return el.closest("ytd-subscribe-button-renderer, ytd-video-owner-renderer") || el;
  }
  return null;
}

let isPaired = false;

function applyPairState(btn) {
  if (!btn) return;
  btn.classList.toggle("ytdls-btn-disabled", !isPaired);
}

async function refreshPairState() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "GET_PAIR_STATE" });
    isPaired = !!response?.paired;
  } catch (err) {
    isPaired = false;
  }
  applyPairState(document.getElementById(BUTTON_ID));
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "paired" in changes) {
    isPaired = !!changes.paired.newValue;
    applyPairState(document.getElementById(BUTTON_ID));
  }
});

function buildButton() {
  const btn = document.createElement("button");
  btn.id = BUTTON_ID;
  btn.type = "button";
  btn.className = "ytdls-btn";
  btn.innerHTML = `${DOWNLOAD_ICON}<span class="ytdls-btn-label">Télécharger</span><span class="ytdls-btn-tooltip">Liez l'extension depuis son menu pour l'activer</span>`;
  btn.addEventListener("click", onDownloadClick);
  applyPairState(btn);
  return btn;
}

function setButtonState(btn, state) {
  const labelEl = btn.querySelector(".ytdls-btn-label");
  btn.classList.remove("ytdls-btn-loading", "ytdls-btn-error");
  if (state === "loading") {
    btn.classList.add("ytdls-btn-loading");
    labelEl.textContent = "Ouverture…";
  } else if (state === "error") {
    btn.classList.add("ytdls-btn-error");
    labelEl.textContent = "App fermée";
    setTimeout(() => setButtonState(btn, "idle"), 2200);
  } else {
    labelEl.textContent = "Télécharger";
  }
}

async function onDownloadClick(event) {
  const btn = event.currentTarget;
  if (!isPaired || btn.classList.contains("ytdls-btn-loading")) return;
  setButtonState(btn, "loading");
  try {
    const response = await chrome.runtime.sendMessage({ type: "OPEN_DOWNLOAD", url: location.href });
    if (response?.ok) {
      setButtonState(btn, "idle");
    } else {
      setButtonState(btn, "error");
    }
  } catch (err) {
    setButtonState(btn, "error");
  }
}

function injectButton() {
  const anchor = findSubscribeAnchor();
  if (!anchor || !anchor.parentElement) return;
  const existing = document.getElementById(BUTTON_ID);
  // Only replace the button if it's genuinely detached from the current
  // anchor's container -- YouTube's DOM churns constantly (view counts,
  // recommendations, etc.), and this fires on every mutation plus a 2s
  // safety poll. An exact previousElementSibling check used to get
  // invalidated by that churn and silently swap in a fresh button mid-
  // download, wiping out its live progress-tracking interval.
  if (existing && anchor.parentElement.contains(existing)) return;
  if (existing) existing.remove();
  anchor.insertAdjacentElement("afterend", buildButton());
  console.debug("[Downloader Youtube] bouton injecté à côté de", anchor);
}

function scheduleInjection() {
  injectButton();
  const observer = new MutationObserver(() => injectButton());
  observer.observe(document.documentElement, { childList: true, subtree: true });
  // Safety net: YouTube's SPA occasionally swaps the metadata section without
  // triggering a mutation our observer catches -- a light poll costs nothing.
  setInterval(injectButton, 2000);
}

refreshPairState();
scheduleInjection();
document.addEventListener("yt-navigate-finish", () => {
  setTimeout(injectButton, 300);
});

// Belt-and-suspenders alongside the storage.onChanged listener above: some
// MV3 service worker suspend/wake cycles can miss delivering that event to
// an already-open tab, so a light periodic re-check guarantees the button
// reflects the real pairing state within a few seconds either way -- no
// page reload required to link/unlink.
setInterval(refreshPairState, 3000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshPairState();
});

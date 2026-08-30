// Service worker: talks to the local Downloader Youtube app server and keeps pairing state.
const APP_ORIGIN = "http://127.0.0.1:47990";
const FETCH_TIMEOUT_MS = 2500;

async function fetchWithTimeout(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function ping() {
  try {
    const res = await fetchWithTimeout(`${APP_ORIGIN}/ping`);
    if (!res.ok) return { ok: false };
    return await res.json();
  } catch (err) {
    return { ok: false };
  }
}

async function link() {
  const pingResult = await ping();
  if (!pingResult.ok) {
    return { ok: false, error: "app_not_running" };
  }
  try {
    const res = await fetchWithTimeout(`${APP_ORIGIN}/link`, { method: "POST" });
    if (!res.ok) return { ok: false, error: "link_failed" };
    const data = await res.json();
    if (data.token) {
      await chrome.storage.local.set({ paired: true, token: data.token });
      // Seed the app with cookies straight away so the very first download
      // that needs them already has them.
      syncCookies();
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: "app_not_running" };
  }
}

// How long the app can be unreachable before we conclude it was actually
// closed (vs. e.g. a few seconds' gap while it restarts to apply an update).
// Time-based rather than a per-call miss counter so it behaves the same
// whether it's being checked every few seconds (an open YouTube tab) or just
// once in a while (opening the popup).
const UNLINK_GRACE_MS = 8000;
let firstMissAt = null;

async function getPairState() {
  const { paired } = await chrome.storage.local.get("paired");
  if (!paired) return { paired: false };

  const pingResult = await ping();
  if (pingResult.ok && pingResult.paired) {
    firstMissAt = null;
    return { paired: true };
  }

  if (firstMissAt === null) firstMissAt = Date.now();
  if (Date.now() - firstMissAt < UNLINK_GRACE_MS) {
    return { paired: true };
  }
  await chrome.storage.local.set({ paired: false, token: "" });
  return { paired: false };
}

// YouTube sometimes demands a signed-in session ("confirm you're not a robot").
// The app can't read Chrome/Edge cookies itself -- App-Bound Encryption blocks
// that by design -- but an extension gets them already decrypted through the
// browser's own API, so we hand them over and the app stores them for yt-dlp.
async function syncCookies() {
  const { paired, token } = await chrome.storage.local.get(["paired", "token"]);
  if (!paired || !token) return { ok: false, error: "not_paired" };

  let cookies;
  try {
    cookies = await chrome.cookies.getAll({ domain: "youtube.com" });
  } catch (err) {
    return { ok: false, error: "cookies_unavailable" };
  }
  if (!cookies?.length) return { ok: false, error: "no_cookies" };

  try {
    const res = await fetchWithTimeout(`${APP_ORIGIN}/cookies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, cookies }),
    });
    if (!res.ok) return { ok: false, error: "sync_failed" };
    return await res.json();
  } catch (err) {
    return { ok: false, error: "app_not_running" };
  }
}

async function openDownload(url) {
  const { token } = await chrome.storage.local.get("token");
  // Refresh before handing the URL over, so the app has current cookies by the
  // time it starts fetching -- awaited so it can't lose the race.
  await syncCookies();
  try {
    const res = await fetchWithTimeout(`${APP_ORIGIN}/open-download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, token: token || "" }),
    });
    if (!res.ok) return { ok: false, error: "app_not_running" };
    return { ok: true };
  } catch (err) {
    return { ok: false, error: "app_not_running" };
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "PING") {
    ping().then(sendResponse);
    return true;
  }
  if (message?.type === "LINK") {
    link().then(sendResponse);
    return true;
  }
  if (message?.type === "OPEN_DOWNLOAD") {
    openDownload(message.url).then(sendResponse);
    return true;
  }
  if (message?.type === "GET_PAIR_STATE") {
    getPairState().then(sendResponse);
    return true;
  }
  if (message?.type === "SYNC_COOKIES") {
    syncCookies().then(sendResponse);
    return true;
  }
  return false;
});

/* Platform catalog: drives the platform picker page, the URL screen's badge
   and placeholder, link validation and the background tint. Every entry is
   handled by yt-dlp (checked against its extractor list); DRM services
   (Netflix, Canal+, M6+, Spotify...) are left out on purpose. */

const PLATFORM_CATEGORIES = [
  { id: "pop", label: "Populaires" },
  { id: "social", label: "Réseaux sociaux" },
  { id: "video", label: "Vidéo & streaming" },
  { id: "tv", label: "TV & replay" },
  { id: "audio", label: "Audio & podcasts" },
];

const SVG = {
  youtube: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.6 7.2s-.2-1.5-.8-2.2c-.8-.9-1.7-.9-2.1-.9C15.9 4 12 4 12 4h0s-3.9 0-6.7.1c-.4 0-1.3.1-2.1.9-.6.7-.8 2.2-.8 2.2S2 9 2 10.7v1.6C2 14 2.2 15.7 2.2 15.7s.2 1.5.8 2.2c.8.9 1.8.9 2.3 1 1.6.1 6.7.2 6.7.2s3.9 0 6.7-.2c.4 0 1.3-.1 2.1-.9.6-.7.8-2.2.8-2.2s.2-1.6.2-3.3v-1.6c0-1.7-.2-3.4-.2-3.4ZM9.9 14.5V8.8l5.4 2.9-5.4 2.8Z"/></svg>',
  tiktok: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.53.02C13.84 0 15.14.01 16.44 0c.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>',
  instagram: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37Z"/><path d="M17.5 6.5h.01"/></svg>',
  twitch: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z"/></svg>',
  dailymotion: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><circle cx="10.5" cy="14" r="5"/><path d="M15.5 3v16"/></svg>',
  twitter: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z"/></svg>',
};

// `domains` are regex fragments matched against the link's host (any
// subdomain allowed). `url`, when set, is the stricter check the link must
// also pass -- e.g. a Twitch channel URL is an endless live stream.
const PLATFORMS = [
  { id: "youtube", name: "YouTube", cat: "pop", desc: "Vidéos & Shorts", color: "#ff0033", color2: "#cc0022", svg: SVG.youtube,
    domains: ["youtube\\.com", "youtu\\.be"], url: /^https?:\/\/(?:(?:[\w-]+\.)?youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/)|youtu\.be\/)[\w-]+/i,
    placeholder: "https://www.youtube.com/watch?v=...", tint: ["#ff3366", "#ff5470", "#ff8a5c"] },
  { id: "tiktok", name: "TikTok", cat: "pop", desc: "Vidéos", color: "#111111", color2: "#000000", svg: SVG.tiktok, cls: "badge-tiktok",
    domains: ["tiktok\\.com"], placeholder: "https://www.tiktok.com/@utilisateur/video/...", tint: ["#2f7dff", "#00c2ff", "#1450c9"] },
  { id: "instagram", name: "Instagram", cat: "pop", desc: "Reels & posts", color: "#d62976", color2: "#962fbf", svg: SVG.instagram, cls: "badge-instagram",
    domains: ["instagram\\.com"], url: /^https?:\/\/(?:www\.)?instagram\.com\/(?:[\w.]+\/)?(?:reels?|p|tv)\/[\w-]+/i,
    placeholder: "https://www.instagram.com/reel/...", tint: ["#f77737", "#c13584", "#833ab4"],
    subtitle: "Copiez l'URL Instagram de la vidéo (reel ou post) que vous souhaitez télécharger." },
  { id: "twitter", name: "X (Twitter)", cat: "pop", desc: "Vidéos des posts", color: "#14171a", color2: "#000000", svg: SVG.twitter, cls: "badge-dark",
    domains: ["twitter\\.com", "x\\.com"], url: /^https?:\/\/(?:www\.|mobile\.)?(?:twitter|x)\.com\/\w+\/status\/\d+/i,
    placeholder: "https://x.com/utilisateur/status/...", tint: ["#1d9bf0", "#536471", "#8ecdf8"],
    subtitle: "Copiez l'URL du post X (Twitter) qui contient la vidéo." },
  { id: "facebook", name: "Facebook", cat: "pop", desc: "Vidéos & Reels", color: "#1877f2", color2: "#0a5fd1", mono: "f",
    domains: ["facebook\\.com", "fb\\.watch", "fb\\.com"], placeholder: "https://www.facebook.com/watch/?v=..." },
  { id: "twitch", name: "Twitch", cat: "pop", desc: "Rediffusions & clips", color: "#9146ff", color2: "#6b2fd6", svg: SVG.twitch,
    domains: ["twitch\\.tv"], url: /^https?:\/\/(?:(?:www\.|m\.)?twitch\.tv\/(?:videos\/\d+|[\w-]+\/clip\/[\w-]+)|clips\.twitch\.tv\/[\w-]+)/i,
    placeholder: "https://www.twitch.tv/videos/...", tint: ["#9146ff", "#772ce8", "#bf94ff"],
    subtitle: "Copiez l'URL d'une rediffusion ou d'un clip Twitch (pas d'un direct)." },
  { id: "dailymotion", name: "Dailymotion", cat: "pop", desc: "Vidéos", color: "#0a6cff", color2: "#0047c2", svg: SVG.dailymotion,
    domains: ["dailymotion\\.com", "dai\\.ly"], url: /^https?:\/\/(?:(?:www\.)?dailymotion\.com\/video\/\w+|dai\.ly\/\w+)/i,
    placeholder: "https://www.dailymotion.com/video/...", tint: ["#0a6cff", "#00aaff", "#1b2a6b"] },
  { id: "vimeo", name: "Vimeo", cat: "pop", desc: "Vidéos HD", color: "#1ab7ea", color2: "#0e8fc0", mono: "v",
    domains: ["vimeo\\.com"], placeholder: "https://vimeo.com/..." },

  { id: "reddit", name: "Reddit", cat: "social", desc: "Vidéos des posts", color: "#ff4500", color2: "#d83a00", mono: "r",
    domains: ["reddit\\.com", "redd\\.it"], placeholder: "https://www.reddit.com/r/.../comments/..." },
  { id: "snapchat", name: "Snapchat", cat: "social", desc: "Spotlight", color: "#fffc00", color2: "#f5e600", fg: "#111", mono: "S",
    domains: ["snapchat\\.com"], placeholder: "https://www.snapchat.com/spotlight/..." },
  { id: "pinterest", name: "Pinterest", cat: "social", desc: "Épingles vidéo", color: "#e60023", color2: "#b8001c", mono: "P",
    domains: ["pinterest\\.[a-z.]+", "pin\\.it"], placeholder: "https://www.pinterest.fr/pin/..." },
  { id: "linkedin", name: "LinkedIn", cat: "social", desc: "Vidéos des posts", color: "#0a66c2", color2: "#084d93", mono: "in",
    domains: ["linkedin\\.com"], placeholder: "https://www.linkedin.com/posts/..." },
  { id: "bluesky", name: "Bluesky", cat: "social", desc: "Vidéos des posts", color: "#1185fe", color2: "#0560c9", mono: "B",
    domains: ["bsky\\.app"], placeholder: "https://bsky.app/profile/.../post/..." },
  { id: "tumblr", name: "Tumblr", cat: "social", desc: "Vidéos des posts", color: "#001935", color2: "#00284f", mono: "t", cls: "badge-dark",
    domains: ["tumblr\\.com"], placeholder: "https://....tumblr.com/post/..." },
  { id: "vk", name: "VK", cat: "social", desc: "VK Vidéo", color: "#0077ff", color2: "#0059c2", mono: "VK",
    domains: ["vk\\.com", "vk\\.ru", "vkvideo\\.ru"], placeholder: "https://vk.com/video..." },
  { id: "okru", name: "OK.ru", cat: "social", desc: "Odnoklassniki", color: "#ee8208", color2: "#c96a00", mono: "OK",
    domains: ["ok\\.ru"], placeholder: "https://ok.ru/video/..." },
  { id: "weibo", name: "Weibo", cat: "social", desc: "Vidéos", color: "#e6162d", color2: "#b80f22", mono: "W",
    domains: ["weibo\\.com", "weibo\\.cn"], placeholder: "https://weibo.com/..." },
  { id: "9gag", name: "9GAG", cat: "social", desc: "Vidéos & GIF", color: "#1c1c1c", color2: "#000000", mono: "9", cls: "badge-dark",
    domains: ["9gag\\.com"], placeholder: "https://9gag.com/gag/..." },
  { id: "imgur", name: "Imgur", cat: "social", desc: "Vidéos & GIF", color: "#1bb76e", color2: "#11905a", mono: "i",
    domains: ["imgur\\.com"], placeholder: "https://imgur.com/..." },

  { id: "kick", name: "Kick", cat: "video", desc: "Rediffusions & clips", color: "#0b0e0f", color2: "#000000", fg: "#53fc18", mono: "K", cls: "badge-dark",
    domains: ["kick\\.com"], placeholder: "https://kick.com/.../videos/...", tint: ["#53fc18", "#1f8f2f", "#0b0e0f"] },
  { id: "rumble", name: "Rumble", cat: "video", desc: "Vidéos", color: "#85c742", color2: "#5e9a26", mono: "R",
    domains: ["rumble\\.com"], placeholder: "https://rumble.com/..." },
  { id: "odysee", name: "Odysee", cat: "video", desc: "Vidéos", color: "#ef1970", color2: "#f77937", mono: "O",
    domains: ["odysee\\.com"], placeholder: "https://odysee.com/@.../..." },
  { id: "bilibili", name: "Bilibili", cat: "video", desc: "Vidéos & anime", color: "#00a1d6", color2: "#fb7299", mono: "B",
    domains: ["bilibili\\.com", "bilibili\\.tv", "b23\\.tv"], placeholder: "https://www.bilibili.com/video/..." },
  { id: "niconico", name: "Niconico", cat: "video", desc: "Vidéos", color: "#252525", color2: "#000000", mono: "N", cls: "badge-dark",
    domains: ["nicovideo\\.jp", "nico\\.ms"], placeholder: "https://www.nicovideo.jp/watch/..." },
  { id: "streamable", name: "Streamable", cat: "video", desc: "Clips", color: "#0f90fa", color2: "#0a6ac2", mono: "S",
    domains: ["streamable\\.com"], placeholder: "https://streamable.com/..." },
  { id: "peertube", name: "PeerTube", cat: "video", desc: "Toutes les instances", color: "#f1680d", color2: "#c94f00", mono: "P",
    domains: [], url: /^https?:\/\/[^/\s]+\/(?:videos\/watch|w)\/[\w-]+/i, placeholder: "https://instance.tld/w/..." },
  { id: "loom", name: "Loom", cat: "video", desc: "Enregistrements", color: "#625df5", color2: "#4440c9", mono: "L",
    domains: ["loom\\.com"], placeholder: "https://www.loom.com/share/..." },
  { id: "coub", name: "Coub", cat: "video", desc: "Boucles vidéo", color: "#0332ff", color2: "#0024b8", mono: "C",
    domains: ["coub\\.com"], placeholder: "https://coub.com/view/..." },
  { id: "archive", name: "Internet Archive", cat: "video", desc: "Archive.org", color: "#3d3d3d", color2: "#1f1f1f", mono: "IA", cls: "badge-dark",
    domains: ["archive\\.org"], placeholder: "https://archive.org/details/..." },

  { id: "francetv", name: "france.tv", cat: "tv", desc: "Replay France TV", color: "#2c3cff", color2: "#1a1f8f", mono: "f.tv",
    domains: ["france\\.tv"], placeholder: "https://www.france.tv/..." },
  { id: "franceinfo", name: "franceinfo", cat: "tv", desc: "JT & reportages", color: "#ffd300", color2: "#f2b600", fg: "#1a1a1a", mono: "fi",
    domains: ["francetvinfo\\.fr", "franceinfo\\.fr"], placeholder: "https://www.francetvinfo.fr/..." },
  { id: "arte", name: "Arte", cat: "tv", desc: "Replay & culture", color: "#fd4600", color2: "#d63a00", mono: "arte",
    domains: ["arte\\.tv"], placeholder: "https://www.arte.tv/fr/videos/..." },
  { id: "bfmtv", name: "BFMTV", cat: "tv", desc: "Vidéos d'actualité", color: "#00337f", color2: "#e30613", mono: "BFM",
    domains: ["bfmtv\\.com"], placeholder: "https://www.bfmtv.com/..." },
  { id: "lcp", name: "LCP", cat: "tv", desc: "Assemblée nationale", color: "#e30613", color2: "#a8000c", mono: "LCP",
    domains: ["lcp\\.fr"], placeholder: "https://www.lcp.fr/..." },
  { id: "tv5monde", name: "TV5Monde", cat: "tv", desc: "TV5MONDEplus", color: "#1f1f1f", color2: "#0063be", mono: "TV5",
    domains: ["tv5monde\\.com", "tv5mondeplus\\.com"], placeholder: "https://www.tv5monde.com/..." },
  { id: "rts", name: "RTS Play", cat: "tv", desc: "Télévision suisse", color: "#af001e", color2: "#7d0015", mono: "RTS",
    domains: ["rts\\.ch", "srf\\.ch", "rsi\\.ch"], placeholder: "https://www.rts.ch/play/tv/..." },
  { id: "rtbf", name: "RTBF Auvio", cat: "tv", desc: "Télévision belge", color: "#00b4e6", color2: "#0080b8", mono: "Au",
    domains: ["rtbf\\.be"], placeholder: "https://auvio.rtbf.be/media/..." },
  { id: "zdf", name: "ZDF", cat: "tv", desc: "Mediathek", color: "#fa7d19", color2: "#d4600a", mono: "ZDF",
    domains: ["zdf\\.de"], placeholder: "https://www.zdf.de/..." },
  { id: "ard", name: "ARD", cat: "tv", desc: "Mediathek", color: "#003480", color2: "#001a4b", mono: "ARD",
    domains: ["ardmediathek\\.de"], placeholder: "https://www.ardmediathek.de/video/..." },
  { id: "nhk", name: "NHK World", cat: "tv", desc: "Japon", color: "#2d2d2d", color2: "#000000", mono: "NHK", cls: "badge-dark",
    domains: ["nhk\\.or\\.jp"], placeholder: "https://www3.nhk.or.jp/nhkworld/..." },

  { id: "soundcloud", name: "SoundCloud", cat: "audio", desc: "Titres & mixes", color: "#ff7700", color2: "#ff3300", mono: "SC",
    domains: ["soundcloud\\.com"], placeholder: "https://soundcloud.com/.../..." },
  { id: "bandcamp", name: "Bandcamp", cat: "audio", desc: "Titres", color: "#1da0c3", color2: "#167e9a", mono: "bc",
    domains: ["bandcamp\\.com"], placeholder: "https://....bandcamp.com/track/..." },
  { id: "mixcloud", name: "Mixcloud", cat: "audio", desc: "Mixes & radio", color: "#5000ff", color2: "#3a00b8", mono: "M",
    domains: ["mixcloud\\.com"], placeholder: "https://www.mixcloud.com/.../..." },
  { id: "radiofrance", name: "Radio France", cat: "audio", desc: "Podcasts & émissions", color: "#e2001a", color2: "#9b0012", mono: "RF",
    domains: ["radiofrance\\.fr"], placeholder: "https://www.radiofrance.fr/..." },
  { id: "applepodcasts", name: "Apple Podcasts", cat: "audio", desc: "Épisodes", color: "#d56dfb", color2: "#832bc1", mono: "P",
    domains: ["podcasts\\.apple\\.com"], placeholder: "https://podcasts.apple.com/..." },
];

// Any web page: yt-dlp's generic extractor digs the video out of it.
const PLATFORM_OTHER = {
  id: "autre", name: "Autre site", desc: "N'importe quel lien", color: "#7c5cff", color2: "#ff3366", svg: SVG.globe,
  url: /^https?:\/\/[^\s/$.?#][^\s]*$/i, placeholder: "https://www.exemple.com/page-avec-une-video",
  subtitle: "Collez le lien de n'importe quelle page contenant une vidéo : elle sera détectée automatiquement.",
};

PLATFORMS.concat(PLATFORM_OTHER).forEach((p) => {
  p.hostRe = p.domains && p.domains.length
    ? new RegExp(`^https?:\\/\\/(?:[\\w-]+\\.)*(?:${p.domains.join("|")})(?:[:/?#]|$)`, "i")
    : p.url;
  p.subtitle = p.subtitle || `Copiez l'URL ${p.name} de la vidéo que vous souhaitez télécharger.`;
  p.tint = p.tint || [p.color, p.color2, p.color];
});

const PLATFORM_BY_ID = Object.fromEntries(PLATFORMS.concat(PLATFORM_OTHER).map((p) => [p.id, p]));

function platformBadgeHtml(p, extraClass = "") {
  const glyph = p.svg || `<span class="badge-mono" data-len="${Math.min(p.mono.length, 4)}">${p.mono}</span>`;
  const style = `--brand:${p.color};--brand-2:${p.color2};--brand-fg:${p.fg || "#fff"}`;
  return `<span class="platform-badge ${p.cls || ""} ${extraClass}" style="${style}" aria-hidden="true">${glyph}</span>`;
}

// The platform a link belongs to (the current one first, so a PeerTube-style
// path match never steals a link from it), or null.
function platformForUrl(url, currentId) {
  const current = PLATFORM_BY_ID[currentId];
  if (current && current.id !== "autre" && current.hostRe.test(url)) return current;
  return PLATFORMS.find((p) => p.domains.length && p.hostRe.test(url))
    || PLATFORMS.find((p) => !p.domains.length && p.hostRe.test(url))
    || null;
}

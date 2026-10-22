// Tondar browser integration: takes over downloads, finds videos on pages,
// and hands everything to the desktop app through native messaging.

const HOST = "com.tondar.host";
const MAX_PER_TAB = 25;
const MAX_BATCH = 500; // links sent at once from a selection
const MEDIA_SITES = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|aparat\.com|twitter\.com|x\.com|instagram\.com|facebook\.com|tiktok\.com|twitch\.tv|soundcloud\.com|reddit\.com|namava\.ir|filimo\.com)$/;

const media = new Map(); // tabId -> [{url, kind, label, size, type, time}]
let settings = { capture: true };
let hostOk = null; // null = unknown
let lastPing = 0;
const PING_AGAIN_MS = 15000; // "not reachable" is re-checked: Tondar may have been started since
const bypass = new Set(); // urls we re-download in the browser on purpose

const ready = (async () => {
  const s = await chrome.storage.local.get("settings");
  if (s.settings) settings = { ...settings, ...s.settings };
  try {
    const all = await chrome.storage.session.get(null);
    for (const [k, v] of Object.entries(all)) if (k.startsWith("tab_")) media.set(Number(k.slice(4)), v);
  } catch (e) { /* storage.session unavailable */ }
})();

// ---------------------------------------------------------------------------
// Native messaging
async function ping() {
  lastPing = Date.now();
  try {
    const r = await chrome.runtime.sendNativeMessage(HOST, { cmd: "ping" });
    hostOk = !!(r && r.ok);
  } catch (e) {
    hostOk = false;
  }
  return hostOk;
}

async function cookiesFor(...urls) {
  const seen = new Map();
  for (const url of urls) {
    if (!url || !/^https?:/i.test(url)) continue;
    try {
      for (const c of await chrome.cookies.getAll({ url })) {
        seen.set(`${c.domain}|${c.path}|${c.name}`, {
          domain: c.domain, name: c.name, value: c.value, path: c.path,
          secure: c.secure, hostOnly: c.hostOnly, expirationDate: c.expirationDate || 0,
        });
      }
    } catch (e) { /* ignore */ }
  }
  return [...seen.values()];
}

function oneLinkPerHost(links) {
  const hosts = new Map();
  for (const l of links || []) {
    try { const h = new URL(l.url).host; if (!hosts.has(h)) hosts.set(h, l.url); } catch (e) { /* ignore */ }
  }
  return [...hosts.values()];
}

async function sendToApp(req) {
  const item = {
    url: req.url,
    kind: req.kind || "http",
    referer: req.referer || "",
    filename: req.filename || "",
    title: req.title || "",
    page_url: req.pageUrl || "",
    size: req.size || -1,
    ...(req.clip && typeof req.clip === "object" ? { clip: { start: Number(req.clip.start) || 0, end: req.clip.end == null ? -1 : Number(req.clip.end) } } : {}),
    ...(req.container ? { container: String(req.container) } : {}),
    ...(req.audio ? { audio: true } : {}),
    ...(Array.isArray(req.links) ? { links: req.links } : {}),
    user_agent: navigator.userAgent,
    cookies: await cookiesFor(req.url, req.kind === "media" || req.links ? req.pageUrl : null, ...oneLinkPerHost(req.links)),
  };
  let resp;
  try {
    resp = await chrome.runtime.sendNativeMessage(HOST, { cmd: "add", item });
  } catch (e) {
    hostOk = false;
    throw new Error("Tondar app is not installed (" + e.message + ")");
  }
  if (!resp || !resp.ok) throw new Error((resp && resp.error) || "Tondar did not answer");
  hostOk = true;
  return true;
}

async function hostReachable() {
  if (hostOk === null || (!hostOk && Date.now() - lastPing > PING_AGAIN_MS)) await ping();
  return hostOk;
}

// ---------------------------------------------------------------------------
// Taking over browser downloads
chrome.downloads.onCreated.addListener(async (d) => {
  await ready;
  const url = d.finalUrl || d.url;
  if (!settings.capture || !/^https?:/i.test(url) || d.state !== "in_progress") return;
  if (bypass.has(url)) { bypass.delete(url); return; }
  if (!(await hostReachable())) return;

  try {
    await chrome.downloads.cancel(d.id);
    await chrome.downloads.erase({ id: d.id });
  } catch (e) { /* already finished */ }
  try {
    await sendToApp({
      url, referer: d.referrer || "", size: d.totalBytes > 0 ? d.totalBytes : -1,
      filename: (d.filename || "").split(/[\\/]/).pop(),
    });
  } catch (e) {
    // App unreachable: give the download back to the browser.
    bypass.add(url);
    chrome.downloads.download({ url });
  }
});

// ---------------------------------------------------------------------------
// Sniffing video/audio streams
function headerMap(list) {
  const h = {};
  for (const x of list || []) h[x.name.toLowerCase()] = x.value || "";
  return h;
}

function classify(details) {
  let u;
  try { u = new URL(details.url); } catch (e) { return null; }
  const path = u.pathname.toLowerCase();
  const h = headerMap(details.responseHeaders);
  const type = (h["content-type"] || "").split(";")[0].trim().toLowerCase();

  if (type.includes("mpegurl") || path.endsWith(".m3u8")) return { kind: "media", label: "HLS stream", type: "m3u8" };
  if (type.includes("dash+xml") || path.endsWith(".mpd")) return { kind: "media", label: "DASH stream", type: "mpd" };
  if (!(type.startsWith("video/") || type.startsWith("audio/"))) return null;
  if (type === "video/mp2t" || /\.(ts|m4s|aac)$/.test(path)) return null; // stream fragments
  if (/(^|\.)googlevideo\.com$/.test(u.hostname)) return null; // YouTube chunks: use the page instead

  let size = -1;
  const m = /\/(\d+)\s*$/.exec(h["content-range"] || "");
  if (m) size = Number(m[1]);
  else if (h["content-length"]) size = Number(h["content-length"]);
  if (size >= 0 && size < 300 * 1024) return null; // thumbnails, ads, previews
  const kind = type.startsWith("audio/") ? "Audio" : "Video";
  return { kind: "http", label: `${kind} (${type.split("/")[1] || "file"})`, type, size };
}

// One timer per tab: with a single shared timer, videos found in one tab were never saved
// when another tab found something within 300 ms (and were lost when the worker went to sleep).
const saveTimers = new Map();
function persist(tabId) {
  clearTimeout(saveTimers.get(tabId));
  saveTimers.set(tabId, setTimeout(() => {
    saveTimers.delete(tabId);
    const list = media.get(tabId);
    const key = "tab_" + tabId;
    (list && list.length ? chrome.storage.session.set({ [key]: list }) : chrome.storage.session.remove(key)).catch(() => {});
  }, 300));
}

function updateBadge(tabId) {
  const n = (media.get(tabId) || []).length;
  chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#e8590c" }).catch(() => {});
}

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const found = classify(details);
    if (!found) return;
    const list = media.get(details.tabId) || [];
    const key = details.url.split("#")[0];
    const existing = list.find((x) => x.url === key);
    if (existing) {
      if (found.size > existing.size) existing.size = found.size;
      return;
    }
    list.unshift({ url: key, ...found, time: Date.now() });
    list.length = Math.min(list.length, MAX_PER_TAB);
    media.set(details.tabId, list);
    updateBadge(details.tabId);
    persist(details.tabId);
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "object", "other"] },
  ["responseHeaders"]
);

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (media.delete(details.tabId)) {
      updateBadge(details.tabId);
      persist(details.tabId);
    }
  },
  { urls: ["<all_urls>"], types: ["main_frame"] }
);

chrome.tabs.onRemoved.addListener((tabId) => {
  media.delete(tabId);
  persist(tabId);
});

// ---------------------------------------------------------------------------
// Options shown on the in-page button and in the popup
function human(n) {
  if (!(n > 0)) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + " " + u[i];
}

function shortUrl(url) {
  try {
    const u = new URL(url);
    const file = decodeURIComponent(u.pathname.split("/").pop() || "");
    return u.hostname + (file ? " · " + (file.length > 40 ? file.slice(0, 37) + "…" : file) : "");
  } catch (e) { return url; }
}

function foundOption(f, pageUrl, title) {
  let path = "";
  try { path = new URL(f.url).pathname.toLowerCase(); } catch (e) { return null; }
  const ext = (/\.([a-z0-9]{2,5})$/.exec(path) || [])[1] || "";
  const stream = ext === "m3u8" ? "HLS stream" : ext === "mpd" ? "DASH stream" : "";
  const audio = /^(mp3|m4a|aac|ogg|opus|flac|wav)$/.test(ext);
  return {
    label: (stream || `${audio ? "Audio" : "Video"} (${ext || "file"})`) + " · no login needed",
    sub: `Found on page (${f.how}) · ` + shortUrl(f.url),
    req: { url: f.url, kind: stream ? "media" : "http", referer: pageUrl, pageUrl, title },
  };
}

async function scanTab(tabId) {
  const r = await chrome.tabs.sendMessage(tabId, { type: "scan" }, { frameId: 0 }).catch(() => null);
  return (r && Array.isArray(r.found)) ? r.found : [];
}

async function optionsFor(tabId, frameUrl, videoSrc, postUrl, found) {
  await ready;
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const tabUrl = tab ? tab.url : frameUrl;
  let pageUrl = tabUrl;
  let title = tab ? tab.title : "";
  // A video in a feed: the content script found the post it belongs to.
  if (postUrl && /^https:/i.test(postUrl) && frameUrl === tabUrl) {
    pageUrl = postUrl;
    title = ""; // the tab's title is the feed's, let yt-dlp name the video
  }
  const opts = [];
  const list = media.get(tabId) || [];

  if (videoSrc && /^https?:/i.test(videoSrc) && !list.some((x) => x.url === videoSrc)) {
    opts.push({ label: "This video file", sub: shortUrl(videoSrc), req: { url: videoSrc, kind: "http", referer: pageUrl, pageUrl, title } });
  }
  for (const m of list) {
    const size = human(m.size);
    opts.push({
      label: m.label + (size ? " · " + size : ""),
      sub: shortUrl(m.url),
      req: { url: m.url, kind: m.kind, referer: pageUrl, pageUrl, title },
    });
  }
  // Links found in the page itself: they work on sites that want a login before yt-dlp
  // may look at the video, because the page shows them to any visitor.
  const known = new Set(opts.map((o) => o.req.url.split("#")[0]));
  if (videoSrc) known.add(videoSrc);
  for (const f of found || []) {
    if (!f || !/^https?:/i.test(f.url || "") || known.has(f.url)) continue;
    const opt = foundOption(f, pageUrl, title);
    if (opt) { opts.push(opt); known.add(f.url); }
  }
  const pageOpt = {
    label: "Best quality (yt-dlp)",
    sub: "Detect video on this page · " + shortUrl(pageUrl),
    req: { url: pageUrl, kind: "media", referer: pageUrl, pageUrl, title },
  };
  let host = "";
  try { host = new URL(pageUrl).hostname; } catch (e) { /* ignore */ }
  const hasDirect = opts.some((o) => o.req.kind === "http");
  if (MEDIA_SITES.test(host) || !hasDirect) opts.unshift(pageOpt);
  else opts.push(pageOpt);

  if (frameUrl && frameUrl !== tabUrl && /^https?:/i.test(frameUrl)) {
    opts.push({
      label: "Embedded player (yt-dlp)",
      sub: shortUrl(frameUrl),
      req: { url: frameUrl, kind: "media", referer: pageUrl, pageUrl: frameUrl, title },
    });
  }
  return { options: opts, hostOk: await hostReachable() };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "menuTarget") return { ok: true };
    if (msg.type === "options") {
      const tabId = msg.tabId ?? sender.tab?.id;
      // The popup has no page of its own: ask the tab's content script what the page shows.
      const found = Array.isArray(msg.found) ? msg.found : (msg.tabId != null ? await scanTab(tabId) : []);
      return optionsFor(tabId, msg.frameUrl || sender.url, msg.src, msg.postUrl, found);
    }
    if (msg.type === "download") {
      try {
        await sendToApp(msg.req);
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e.message };
      }
    }
    if (msg.type === "settings") {
      await ready;
      if (msg.set) {
        settings = { ...settings, ...msg.set };
        await chrome.storage.local.set({ settings });
      }
      return { settings, hostOk: await ping() };
    }
    if (msg.type === "clear") {
      media.delete(msg.tabId);
      updateBadge(msg.tabId);
      persist(msg.tabId);
      return { ok: true };
    }
  })().then(sendResponse, (e) => sendResponse({ ok: false, error: String(e) }));
  return true;
});

// ---------------------------------------------------------------------------
// Right-click menu
const PAGE_TITLE = "Download video on this page with Tondar";
// One entry per context keeps "Download with Tondar" at the top level of the menu on links
// (browsers fold two or more entries into a "Tondar" submenu).
function createMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "link", title: "Download with Tondar", contexts: ["link"] });
    chrome.contextMenus.create({ id: "media", title: "Download with Tondar", contexts: ["video", "audio", "image"] });
    chrome.contextMenus.create({ id: "page", title: PAGE_TITLE, contexts: ["page", "frame"] });
    chrome.contextMenus.create({ id: "clone", title: "Clone this website with Tondar", contexts: ["page"] });
    chrome.contextMenus.create({ id: "selection", title: "Download selected links with Tondar", contexts: ["selection"] });
  });
}
chrome.runtime.onInstalled.addListener(createMenus);
chrome.runtime.onStartup.addListener(createMenus);

// The content script tells us what is under the mouse before the menu opens: a download
// button that isn't a link gets "Download with Tondar" instead of the page entry.
let pageTitle = PAGE_TITLE;
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "menuTarget") {
    const title = msg.found ? "Download with Tondar" : PAGE_TITLE;
    if (title !== pageTitle) {
      pageTitle = title;
      chrome.contextMenus.update("page", { title }, () => void chrome.runtime.lastError);
    }
  }
  return false;
});

function tell(tab, frameId, text, ok) {
  if (!tab || tab.id < 0) return;
  chrome.tabs.sendMessage(tab.id, { type: "toast", text, ok }, { frameId: frameId || 0 }).catch(() => {});
}

// Several links selected at once (the episodes of a series…): one window in Tondar lists them all.
async function downloadSelection(info, tab, pageUrl, title) {
  let links = [];
  if (tab) {
    const r = await chrome.tabs.sendMessage(tab.id, { type: "selectionLinks" }, { frameId: info.frameId || 0 }).catch(() => null);
    if (r && Array.isArray(r.links)) links = r.links;
  }
  if (!links.length) { // no content script in this frame: links written out in the selected text
    const seen = new Set();
    for (const m of (info.selectionText || "").matchAll(/https?:\/\/[^\s"'<>]+/gi)) {
      const url = m[0].replace(/[.,;:!?)\]]+$/, "");
      if (!seen.has(url)) { seen.add(url); links.push({ url, text: "" }); }
    }
  }
  links = links.slice(0, MAX_BATCH);
  if (!links.length) {
    tell(tab, info.frameId, "No links in the selected text", false);
    return;
  }
  const req = links.length === 1
    ? { url: links[0].url, kind: "http", referer: pageUrl, pageUrl }
    : { url: pageUrl, kind: "batch", links, referer: pageUrl, pageUrl, title };
  try {
    await sendToApp(req);
    tell(tab, info.frameId, links.length === 1 ? "Sent to Tondar" : `Sent ${links.length} links to Tondar`, true);
  } catch (e) {
    tell(tab, info.frameId, e.message, false);
  }
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = info.pageUrl || (tab && tab.url) || "";
  const title = (tab && tab.title) || "";
  if (info.menuItemId === "selection") return downloadSelection(info, tab, pageUrl, title);
  let req;
  if (info.menuItemId === "link") req = { url: info.linkUrl, kind: "http", referer: pageUrl, pageUrl };
  else if (info.menuItemId === "media" && /^https?:/i.test(info.srcUrl || "")) req = { url: info.srcUrl, kind: "http", referer: pageUrl, pageUrl, title };
  else if (info.menuItemId === "clone") req = { url: pageUrl, kind: "site", title };
  else {
    // In a feed the page isn't the video: ask the content script which post (or download button) was clicked.
    let postUrl = "", target = null;
    if (tab) {
      const r = await chrome.tabs.sendMessage(tab.id, { type: "postUrl" }, { frameId: info.frameId || 0 }).catch(() => null);
      if (r && r.target && /^https?:/i.test(r.target.url || "")) target = r.target;
      if (!info.frameId && r && /^https:/i.test(r.postUrl || "")) postUrl = r.postUrl;
    }
    if (target) req = { url: target.url, kind: "http", referer: info.frameUrl || pageUrl, pageUrl };
    else if (postUrl) req = { url: postUrl, kind: "media", referer: postUrl, pageUrl: postUrl, title: "" };
    else req = { url: info.frameUrl || pageUrl, kind: "media", referer: pageUrl, pageUrl, title };
  }
  if (!req.url || !/^https?:/i.test(req.url)) {
    tell(tab, info.frameId, "Tondar can only download http and https links", false);
    return;
  }
  try {
    await sendToApp(req);
    tell(tab, info.frameId, req.kind === "site" ? "Sent to Tondar: choose how to clone the site" : "Sent to Tondar", true);
  } catch (e) {
    console.warn("Tondar:", e.message);
    tell(tab, info.frameId, e.message, false);
  }
});

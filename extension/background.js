// Tondar browser integration: takes over downloads, finds videos on pages,
// and hands everything to the desktop app through native messaging.

const HOST = "com.tondar.host";
const MAX_PER_TAB = 25;
const MEDIA_SITES = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|aparat\.com|twitter\.com|x\.com|instagram\.com|facebook\.com|tiktok\.com|twitch\.tv|soundcloud\.com|reddit\.com|namava\.ir|filimo\.com)$/;

const media = new Map(); // tabId -> [{url, kind, label, size, type, time}]
let settings = { capture: true };
let hostOk = null; // null = unknown
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

async function sendToApp(req) {
  const item = {
    url: req.url,
    kind: req.kind || "http",
    referer: req.referer || "",
    filename: req.filename || "",
    title: req.title || "",
    page_url: req.pageUrl || "",
    size: req.size || -1,
    user_agent: navigator.userAgent,
    cookies: await cookiesFor(req.url, req.kind === "media" ? req.pageUrl : null),
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

// ---------------------------------------------------------------------------
// Taking over browser downloads
chrome.downloads.onCreated.addListener(async (d) => {
  await ready;
  const url = d.finalUrl || d.url;
  if (!settings.capture || !/^https?:/i.test(url) || d.state !== "in_progress") return;
  if (bypass.has(url)) { bypass.delete(url); return; }
  if (hostOk === null) await ping();
  if (!hostOk) return;

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

let saveTimer = null;
function persist(tabId) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const list = media.get(tabId);
    const key = "tab_" + tabId;
    (list && list.length ? chrome.storage.session.set({ [key]: list }) : chrome.storage.session.remove(key)).catch(() => {});
  }, 300);
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

async function optionsFor(tabId, frameUrl, videoSrc, postUrl) {
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
  return { options: opts, hostOk: hostOk === null ? await ping() : hostOk };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "options") {
      const tabId = msg.tabId ?? sender.tab?.id;
      return optionsFor(tabId, msg.frameUrl || sender.url, msg.src, msg.postUrl);
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
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "link", title: "Download link with Tondar", contexts: ["link"] });
    chrome.contextMenus.create({ id: "media", title: "Download this media with Tondar", contexts: ["video", "audio"] });
    chrome.contextMenus.create({ id: "page", title: "Download video on this page with Tondar", contexts: ["page", "frame"] });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = info.pageUrl || (tab && tab.url) || "";
  const title = (tab && tab.title) || "";
  let req;
  if (info.menuItemId === "link") req = { url: info.linkUrl, kind: "http", referer: pageUrl, pageUrl };
  else if (info.menuItemId === "media" && /^https?:/i.test(info.srcUrl || "")) req = { url: info.srcUrl, kind: "http", referer: pageUrl, pageUrl, title };
  else req = { url: info.frameUrl || pageUrl, kind: "media", referer: pageUrl, pageUrl, title };
  try {
    await sendToApp(req);
  } catch (e) {
    console.warn("Tondar:", e.message);
  }
});

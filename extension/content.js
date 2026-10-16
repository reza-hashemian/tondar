// Shows a floating "Download" button on top of videos (like IDM's video panel).
// The × next to it hides the button on this page until the page is reloaded.
(() => {
  if (window.__tondarLoaded) return;
  window.__tondarLoaded = true;

  const MIN_W = 200, MIN_H = 110;
  const videos = document.getElementsByTagName("video"); // live list: cheaper than querySelectorAll on every move
  let host, root, bar, btn, closeBtn, menu, video = null, hideTimer = null, menuOpen = false, lastMove = 0;
  let dismissed = false; // × pressed: no button on this page until it's reloaded
  let placeQueued = false;

  function build() {
    host = document.createElement("tondar-video-button");
    host.style.cssText = "all:initial;position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;";
    root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        :host { all: initial; }
        * { box-sizing: border-box; font: 13px/1.35 system-ui, "Vazirmatn", sans-serif; }
        .bar { position: fixed; display: none; align-items: center; gap: 4px; }
        .btn { display: flex; align-items: center; gap: 6px; padding: 6px 12px 6px 9px;
          border: 0; border-radius: 999px; cursor: pointer; color: #fff; font-weight: 600;
          background: linear-gradient(135deg, #f76707, #e03131); box-shadow: 0 2px 10px rgba(0,0,0,.45);
          opacity: .93; transition: opacity .15s, transform .15s; }
        .btn:hover { opacity: 1; transform: translateY(-1px); }
        .btn svg { width: 16px; height: 16px; }
        .close { display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; padding: 0;
          border: 0; border-radius: 50%; cursor: pointer; color: #fff; background: rgba(20,20,22,.78);
          box-shadow: 0 2px 8px rgba(0,0,0,.45); opacity: .85; transition: opacity .15s, background .15s; }
        .close:hover { opacity: 1; background: #e03131; }
        .close svg { width: 10px; height: 10px; }
        .menu { position: fixed; display: none; min-width: 280px; max-width: 420px; max-height: 60vh; overflow: auto;
          background: #232326; color: #eee; border-radius: 12px; padding: 6px; box-shadow: 0 8px 30px rgba(0,0,0,.5);
          border: 1px solid rgba(255,255,255,.08); }
        .item { display: block; width: 100%; text-align: left; background: none; border: 0; color: inherit;
          border-radius: 8px; padding: 8px 10px; cursor: pointer; }
        .item:hover { background: rgba(255,255,255,.08); }
        .label { font-weight: 600; }
        .sub { opacity: .6; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .note { padding: 8px 10px; opacity: .8; }
        .err { color: #ff8787; }
        .ok { color: #8ce99a; }
      </style>
      <div class="bar">
        <button class="btn" title="Download with Tondar">
          <svg viewBox="0 0 16 16" fill="currentColor"><path d="M7 1h2v7.6l2.6-2.6L13 7.4 8 12.4 3 7.4 4.4 6 7 8.6z"/><path d="M2 13h12v2H2z"/></svg>
          Download
        </button>
        <button class="close" title="Hide (comes back when you reload the page)" aria-label="Hide">
          <svg viewBox="0 0 10 10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7"/></svg>
        </button>
      </div>
      <div class="menu"></div>`;
    bar = root.querySelector(".bar");
    btn = root.querySelector(".btn");
    closeBtn = root.querySelector(".close");
    menu = root.querySelector(".menu");
    btn.addEventListener("click", onClick, true);
    closeBtn.addEventListener("click", dismiss, true);
    // Keep the click away from the player underneath (it would pause / play the video).
    for (const type of ["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick"]) {
      bar.addEventListener(type, (e) => e.stopPropagation(), true);
    }
    bar.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    menu.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    menu.addEventListener("mouseleave", scheduleHide);
    attach();
  }

  function dismiss(e) {
    e.preventDefault();
    e.stopPropagation();
    dismissed = true;
    clearTimeout(hideTimer);
    menuOpen = false;
    video = null;
    if (host) host.remove(); // gone until the page is reloaded (the script runs again then)
  }

  function attach() {
    if (dismissed) return;
    const parent = document.fullscreenElement || document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
  }

  function closeMenu() {
    menuOpen = false;
    if (menu) menu.style.display = "none";
  }

  function place() {
    placeQueued = false;
    if (dismissed || !bar) return;
    if (!video || !video.isConnected) return hide();
    const r = video.getBoundingClientRect();
    if (r.width < MIN_W || r.height < MIN_H) return hide();
    bar.style.display = "flex";
    const bw = bar.offsetWidth || 140;
    bar.style.left = Math.max(4, Math.min(r.right - bw - 12, innerWidth - bw - 4)) + "px";
    bar.style.top = Math.max(4, r.top + 12) + "px";
    if (menuOpen) {
      const br = btn.getBoundingClientRect();
      menu.style.top = br.bottom + 6 + "px";
      menu.style.left = Math.max(4, Math.min(br.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 4)) + "px";
    }
  }

  // Scrolling fires very often: move the button at most once per frame.
  function queuePlace() {
    if (placeQueued || dismissed) return;
    placeQueued = true;
    requestAnimationFrame(place);
  }

  function hide() {
    if (menuOpen) return;
    if (bar) bar.style.display = "none";
    video = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { closeMenu(); hide(); }, 1800);
  }

  function videoAt(x, y) {
    for (const v of videos) {
      const r = v.getBoundingClientRect();
      if (r.width >= MIN_W && r.height >= MIN_H && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return v;
    }
    return null;
  }

  document.addEventListener("mousemove", (e) => {
    if (dismissed || !videos.length) return;
    const now = Date.now();
    if (now - lastMove < 150) return;
    lastMove = now;
    const v = videoAt(e.clientX, e.clientY);
    if (v) {
      if (!host) build();
      attach();
      clearTimeout(hideTimer);
      video = v;
      place();
    } else if (video && !menuOpen) {
      scheduleHide();
    }
  }, { passive: true, capture: true });

  addEventListener("scroll", () => video && queuePlace(), { passive: true, capture: true });
  addEventListener("resize", () => video && queuePlace(), { passive: true });
  document.addEventListener("fullscreenchange", () => { if (host && !dismissed) { attach(); place(); } });
  document.addEventListener("mousedown", (e) => {
    if (menuOpen && !e.composedPath().includes(host)) { closeMenu(); scheduleHide(); }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menuOpen) { closeMenu(); scheduleHide(); }
  }, true);

  function note(text, cls) {
    menu.innerHTML = "";
    const div = document.createElement("div");
    div.className = "note " + (cls || "");
    div.textContent = text;
    menu.appendChild(div);
    menuOpen = true;
    menu.style.display = "block";
    place();
  }

  // In a feed (instagram.com/, x.com/home) the address bar doesn't name the video; the post's own link does.
  const POST_LINKS = [
    [/(^|\.)instagram\.com$/, /\/(p|tv|reels?)\/[\w-]+/],
    [/(^|\.)(x|twitter)\.com$/, /\/status\/\d+/],
  ];

  function permalink(v) {
    const site = POST_LINKS.find(([host]) => host.test(location.hostname));
    if (!site || !v || site[1].test(location.pathname)) return "";
    for (let el = v; el; el = el.parentElement) {
      const found = new Set();
      for (const a of el.querySelectorAll("a[href]")) {
        let u;
        try { u = new URL(a.href); } catch (err) { continue; }
        const m = site[1].exec(u.pathname);
        if (m && u.hostname === location.hostname) found.add(u.origin + u.pathname.slice(0, m.index + m[0].length) + "/");
      }
      if (found.size) return found.size === 1 ? [...found][0] : ""; // several posts: we climbed past this one
    }
    return "";
  }

  // ---------------------------------------------------------------------------
  // Video links a visitor can see in the page. Sites that want a login before yt-dlp may
  // look at a video often still put the file or stream in the page itself (og:video,
  // <video src>, a player config in a script): those links work without an account.
  const MEDIA_EXT = /\.(mp4|m4v|mkv|webm|mov|avi|flv|wmv|3gp|m3u8|mpd|mp3|m4a|aac|ogg|opus|flac|wav)$/i;
  const MEDIA_IN_TEXT = /https?:(?:\\?\/){2}[^\s"'<>()]+?\.(?:mp4|m4v|mkv|webm|mov|avi|flv|m3u8|mpd|mp3|m4a)(?:[?#][^\s"'<>()]*)?(?=$|[\s"'<>()\\])/gi;
  const SKIP_HOST = /(^|\.)googlevideo\.com$/; // YouTube chunks: yt-dlp handles YouTube
  const MAX_FOUND = 30;

  function scanPage() {
    const found = new Map();
    const add = (raw, how) => {
      if (found.size >= MAX_FOUND || !raw || typeof raw !== "string") return;
      let u;
      try {
        u = new URL(raw.replace(/\\u0026/gi, "&").replace(/\\u002f/gi, "/").replace(/\\\//g, "/").replace(/&amp;/g, "&").replace(/\\+$/, ""), location.href);
      } catch (err) { return; }
      if (!/^https?:$/.test(u.protocol) || SKIP_HOST.test(u.hostname)) return;
      u.searchParams.delete("bytestart"); // Facebook / Instagram CDNs: the whole file, not one piece
      u.searchParams.delete("byteend");
      u.hash = "";
      if (!found.has(u.href)) found.set(u.href, how);
    };
    for (const el of document.querySelectorAll("video, audio, video source, audio source")) add(el.currentSrc || el.src, "player");
    for (const m of document.querySelectorAll(
      'meta[property^="og:video"], meta[property^="og:audio"], meta[name="twitter:player:stream"], meta[itemprop="contentUrl"]')) {
      if (!/:(type|width|height)$/.test(m.getAttribute("property") || "")) add(m.content, "page info");
    }
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      const walk = (o, depth) => {
        if (!o || typeof o !== "object" || depth > 6) return;
        if (typeof o.contentUrl === "string") add(o.contentUrl, "page info");
        for (const v of Object.values(o)) walk(v, depth + 1);
      };
      try { walk(JSON.parse(s.textContent), 0); } catch (err) { /* not JSON */ }
    }
    for (const a of document.querySelectorAll("a[href]")) {
      if (MEDIA_EXT.test(a.pathname || "")) add(a.href, "link");
    }
    // Files the page already fetched, also before the extension started watching.
    try {
      for (const e of performance.getEntriesByType("resource")) {
        let path = "";
        try { path = new URL(e.name).pathname; } catch (err) { continue; }
        if (MEDIA_EXT.test(path)) add(e.name, "played");
      }
    } catch (err) { /* ignore */ }
    // Player configs in inline scripts; capped so huge pages stay quick.
    if (found.size < MAX_FOUND) {
      let text = "";
      for (const s of document.scripts) {
        if (!s.src && text.length < 4e6) text += s.textContent + "\n";
      }
      for (const m of text.matchAll(MEDIA_IN_TEXT)) add(m[0], "player config");
    }
    return [...found].map(([url, how]) => ({ url, how }));
  }

  // The right-click menu lives in the background script, which can't see what was clicked.
  let menuPostUrl = "";
  document.addEventListener("contextmenu", (e) => {
    const el = e.composedPath()[0];
    menuPostUrl = permalink(el instanceof Element ? el : null);
  }, true);
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "postUrl") sendResponse({ postUrl: menuPostUrl });
    else if (msg.type === "scan") sendResponse({ found: scanPage() });
  });

  async function onClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if (menuOpen) { closeMenu(); return; }
    note("Looking for videos…");
    let res;
    try {
      res = await chrome.runtime.sendMessage({
        type: "options", frameUrl: location.href, src: video && video.currentSrc, postUrl: permalink(video), found: scanPage(),
      });
    } catch (err) {
      return note("Extension was updated — reload this page.", "err");
    }
    if (!res || !res.hostOk) {
      return note("Tondar app is not installed or not reachable. Install Tondar and open it once.", "err");
    }
    menu.innerHTML = "";
    for (const opt of res.options) {
      const b = document.createElement("button");
      b.className = "item";
      const l = document.createElement("div");
      l.className = "label";
      l.textContent = opt.label;
      const s = document.createElement("div");
      s.className = "sub";
      s.textContent = opt.sub;
      b.append(l, s);
      b.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        note("Sending to Tondar…");
        let r;
        try {
          r = await chrome.runtime.sendMessage({ type: "download", req: opt.req });
        } catch (err) {
          r = { ok: false, error: "Extension was updated — reload this page." };
        }
        note(r.ok ? "✓ Sent to Tondar" : "✗ " + r.error, r.ok ? "ok" : "err");
        setTimeout(() => { closeMenu(); scheduleHide(); }, 1500);
      });
      menu.appendChild(b);
    }
    place();
  }
})();

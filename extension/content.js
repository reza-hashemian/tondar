// Shows a floating "Download" button on top of videos (like IDM's video panel).
(() => {
  if (window.__tondarLoaded) return;
  window.__tondarLoaded = true;

  const MIN_W = 200, MIN_H = 110;
  let host, root, btn, menu, video = null, hideTimer = null, menuOpen = false, lastMove = 0;

  function build() {
    host = document.createElement("tondar-video-button");
    host.style.cssText = "all:initial;position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;";
    root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        :host { all: initial; }
        * { box-sizing: border-box; font: 13px/1.35 system-ui, "Vazirmatn", sans-serif; }
        .btn { position: fixed; display: none; align-items: center; gap: 6px; padding: 6px 12px 6px 9px;
          border: 0; border-radius: 999px; cursor: pointer; color: #fff; font-weight: 600;
          background: linear-gradient(135deg, #f76707, #e03131); box-shadow: 0 2px 10px rgba(0,0,0,.45);
          opacity: .93; transition: opacity .15s, transform .15s; }
        .btn:hover { opacity: 1; transform: translateY(-1px); }
        .btn svg { width: 16px; height: 16px; }
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
      <button class="btn" title="Download with Tondar">
        <svg viewBox="0 0 16 16" fill="currentColor"><path d="M7 1h2v7.6l2.6-2.6L13 7.4 8 12.4 3 7.4 4.4 6 7 8.6z"/><path d="M2 13h12v2H2z"/></svg>
        Download
      </button>
      <div class="menu"></div>`;
    btn = root.querySelector(".btn");
    menu = root.querySelector(".menu");
    btn.addEventListener("click", onClick, true);
    btn.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    menu.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    menu.addEventListener("mouseleave", scheduleHide);
    attach();
  }

  function attach() {
    const parent = document.fullscreenElement || document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
  }

  function place() {
    if (!video || !video.isConnected) return hide();
    const r = video.getBoundingClientRect();
    if (r.width < MIN_W || r.height < MIN_H) return hide();
    btn.style.display = "flex";
    const bw = btn.offsetWidth || 110;
    btn.style.left = Math.max(4, Math.min(r.right - bw - 12, innerWidth - bw - 4)) + "px";
    btn.style.top = Math.max(4, r.top + 12) + "px";
    if (menuOpen) {
      const br = btn.getBoundingClientRect();
      menu.style.top = br.bottom + 6 + "px";
      menu.style.left = Math.max(4, Math.min(br.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 4)) + "px";
    }
  }

  function hide() {
    if (menuOpen) return;
    if (btn) btn.style.display = "none";
    video = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { menuOpen = false; menu.style.display = "none"; hide(); }, 1800);
  }

  function videoAt(x, y) {
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      if (r.width >= MIN_W && r.height >= MIN_H && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return v;
    }
    return null;
  }

  document.addEventListener("mousemove", (e) => {
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

  addEventListener("scroll", () => video && place(), { passive: true, capture: true });
  addEventListener("resize", () => video && place(), { passive: true });
  document.addEventListener("fullscreenchange", () => { if (host) { attach(); place(); } });
  document.addEventListener("mousedown", (e) => {
    if (menuOpen && !e.composedPath().includes(host)) { menuOpen = false; menu.style.display = "none"; scheduleHide(); }
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

  // The right-click menu lives in the background script, which can't see what was clicked.
  let menuPostUrl = "";
  document.addEventListener("contextmenu", (e) => {
    const el = e.composedPath()[0];
    menuPostUrl = permalink(el instanceof Element ? el : null);
  }, true);
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "postUrl") sendResponse({ postUrl: menuPostUrl });
  });

  async function onClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if (menuOpen) { menuOpen = false; menu.style.display = "none"; return; }
    note("Looking for videos…");
    let res;
    try {
      res = await chrome.runtime.sendMessage({ type: "options", frameUrl: location.href, src: video && video.currentSrc, postUrl: permalink(video) });
    } catch (err) {
      return note("Extension was updated — reload this page.", "err");
    }
    if (!res.hostOk) {
      return note("Tondar app is not installed or not reachable. Install the tondar .deb package.", "err");
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
        const r = await chrome.runtime.sendMessage({ type: "download", req: opt.req });
        note(r.ok ? "✓ Sent to Tondar" : "✗ " + r.error, r.ok ? "ok" : "err");
        setTimeout(() => { menuOpen = false; menu.style.display = "none"; scheduleHide(); }, 1500);
      });
      menu.appendChild(b);
    }
    place();
  }
})();

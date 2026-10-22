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
        .menu { position: fixed; display: none; width: min(360px, calc(100vw - 8px)); max-height: 70vh;
          overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain;
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
        .opts { position: sticky; bottom: -6px; margin: 6px -6px -6px; padding: 10px 12px 12px;
          background: #1b1b1e; border-top: 1px solid rgba(255,255,255,.08); border-radius: 0 0 12px 12px; }
        .opt-title { font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; opacity: .55;
          margin: 0 0 6px; }
        .clip-head { display: flex; align-items: center; gap: 8px; cursor: pointer; font-weight: 600; }
        .clip-head input { accent-color: #f76707; width: 15px; height: 15px; margin: 0; }
        .clip-row { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
        .clip-row[hidden] { display: none; }
        .field { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 6px; }
        .field span { font-size: 12px; opacity: .7; }
        .field input { display: block; width: 100%; min-width: 0; height: 30px; margin: 0; padding: 0 9px; border-radius: 7px;
          border: 1px solid rgba(255,255,255,.14); background: #2c2c30; color: #fff; font-variant-numeric: tabular-nums;
          appearance: none; }
        .field input::placeholder { color: rgba(255,255,255,.4); }
        .field input:focus { outline: 2px solid #f76707; outline-offset: -1px; }
        .field input.bad { border-color: #ff6b6b; }
        .now { height: 30px; margin: 0; padding: 0 10px; border-radius: 7px; border: 0; background: #3a3a3f; color: #eee;
          cursor: pointer; font-size: 12px; white-space: nowrap; }
        .now:hover { background: #4a4a50; }
        .hint { font-size: 11px; opacity: .55; padding-left: 50px; }
        .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center; }
        .chips .opt-title { flex-basis: 100%; margin: 0; }
        .chip { padding: 4px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,.16); background: none;
          color: #ddd; cursor: pointer; font-size: 12px; }
        .chip:hover { background: rgba(255,255,255,.08); }
        .chip.on { background: linear-gradient(135deg, #f76707, #e03131); border-color: transparent; color: #fff; font-weight: 600; }
        .opt-err { color: #ff8787; font-size: 12px; margin-top: 8px; }
        .opt-err:empty { display: none; }
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
    // Typing a time must not reach the page: video sites use digits and letters as shortcuts.
    for (const type of ["keydown", "keyup", "keypress", "mousedown", "pointerdown", "click", "dblclick", "wheel"]) {
      menu.addEventListener(type, (e) => e.stopPropagation());
    }
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
  let menuTarget = null;
  const FILE_EXT = /\.(zip|rar|7z|tar|gz|bz2|xz|zst|tgz|iso|exe|msi|dmg|pkg|deb|rpm|apk|appimage|pdf|docx?|xlsx?|pptx?|epub|mp4|m4v|mkv|webm|mov|avi|flv|wmv|3gp|mp3|m4a|aac|flac|wav|ogg|opus|torrent|bin|img)$/i;
  const URL_ATTRS = ["data-href", "data-url", "data-download", "data-download-url", "data-downloadurl", "data-file",
    "data-file-url", "data-link", "data-src", "href", "formaction"];

  // Download buttons that aren't links (<button data-url=…>, onclick="location='…/file.zip'"):
  // the browser only offers its page menu for them, so find their file here.
  function downloadTarget(start) {
    let n = 0;
    for (let e = start; e && e.nodeType === 1 && n < 6; e = e.parentElement || (e.getRootNode && e.getRootNode().host), n++) {
      if (e.matches && e.matches("a[href]")) return null; // the browser's link menu handles it
      const candidates = [];
      for (const a of URL_ATTRS) {
        const v = e.getAttribute && e.getAttribute(a);
        if (v) candidates.push([v, /download/i.test(a)]);
      }
      const onclick = e.getAttribute && e.getAttribute("onclick");
      if (onclick) {
        const m = /(?:location(?:\.href)?\s*=|window\.open\(|\.assign\()\s*['"]([^'"]+)['"]/.exec(onclick) || /['"](https?:\/\/[^'"\s]+)['"]/.exec(onclick);
        if (m) candidates.push([m[1], false]);
      }
      if (e.form && e.form.method && e.form.method.toLowerCase() === "get" && e.form.action) candidates.push([e.form.action, false]);
      const words = ((e.textContent || "").slice(0, 80) + " " + (e.getAttribute && (e.getAttribute("aria-label") || e.getAttribute("title")) || "")).toLowerCase();
      const says = /download|دانلود|بارگیری|herunterladen|télécharger|descargar|indir|скачать/.test(words);
      for (const [raw, named] of candidates) {
        let u;
        try { u = new URL(raw, location.href); } catch (err) { continue; }
        if (!/^https?:$/.test(u.protocol) || u.href === location.href) continue;
        if (named || says || FILE_EXT.test(u.pathname)) return { url: u.href };
      }
    }
    return null;
  }

  function rememberTarget(e) {
    const el = e.composedPath()[0];
    const node = el instanceof Element ? el : null;
    menuPostUrl = permalink(node);
    menuTarget = downloadTarget(node);
    return menuTarget;
  }
  // The right button goes down before the menu opens: name the menu entry after what's under the mouse.
  document.addEventListener("mousedown", (e) => {
    if (e.button !== 2) return;
    const t = rememberTarget(e);
    chrome.runtime.sendMessage({ type: "menuTarget", found: !!t }).catch(() => {});
  }, true);
  document.addEventListener("contextmenu", rememberTarget, true);

  let toastBox = null, toastTimer = null;
  function toast(text, ok) {
    if (!toastBox) {
      toastBox = document.createElement("tondar-toast");
      toastBox.style.cssText = "all:initial;position:fixed;right:20px;bottom:20px;z-index:2147483647;";
      const r = toastBox.attachShadow({ mode: "closed" });
      r.innerHTML = `<style>
        div { font: 600 13px/1.35 system-ui, "Vazirmatn", sans-serif; color: #fff; background: #232326; padding: 10px 16px 10px 12px;
          border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,.45); display: flex; gap: 10px; align-items: center;
          border: 1px solid rgba(255,255,255,.08); max-width: 380px; transition: opacity .2s, transform .2s; }
        i { font-style: normal; display: inline-flex; width: 22px; height: 22px; border-radius: 50%; align-items: center;
          justify-content: center; flex: none; background: linear-gradient(135deg, #f76707, #e03131); }
        div.bad i { background: #c92a2a; }
      </style><div><i></i><span></span></div>`;
      toastBox._div = r.querySelector("div");
    }
    toastBox._div.className = ok ? "" : "bad";
    toastBox._div.querySelector("i").textContent = ok ? "✓" : "!";
    toastBox._div.querySelector("span").textContent = text;
    (document.fullscreenElement || document.documentElement).appendChild(toastBox);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastBox.remove(), ok ? 2500 : 5000);
  }

  // The links inside the selected text, in page order ("Download selected links with Tondar").
  function selectionLinks() {
    const sel = window.getSelection();
    const out = [], seen = new Set();
    const push = (url, text) => {
      if (typeof url !== "string" || !/^https?:/i.test(url)) return;
      const key = url.split("#")[0];
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ url: key, text: (text || "").replace(/\s+/g, " ").trim().slice(0, 200) });
    };
    if (!sel || sel.isCollapsed) return out;
    for (let i = 0; i < sel.rangeCount; i++) {
      const range = sel.getRangeAt(i);
      let node = range.commonAncestorContainer;
      if (node.nodeType !== 1) node = node.parentElement;
      if (!node) continue;
      const own = node.closest("a[href]"); // the selection is inside one link
      if (own) push(own.href, own.textContent);
      for (const a of node.querySelectorAll("a[href]")) {
        if (range.intersectsNode(a)) push(a.href, a.textContent);
      }
    }
    // Addresses written out as plain text.
    for (const m of sel.toString().matchAll(/https?:\/\/[^\s"'<>]+/gi)) push(m[0].replace(/[.,;:!?)\]]+$/, ""), "");
    return out;
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "postUrl") sendResponse({ postUrl: menuPostUrl, target: menuTarget });
    else if (msg.type === "selectionLinks") sendResponse({ links: selectionLinks() });
    else if (msg.type === "scan") sendResponse({ found: scanPage() });
    else if (msg.type === "toast") { toast(msg.text, msg.ok); sendResponse({ ok: true }); }
  });

  // ---------------------------------------------------------------------------
  // Options under the list: only a part of the video, and the file type to save.
  const opts = { clip: false, start: "", end: "", container: "", audio: false };
  const FORMATS = [["", "Auto"], ["mp4", "MP4"], ["mkv", "MKV"], ["webm", "WebM"], ["m4a", "Audio only"]];

  function fmtTime(t) {
    t = Math.max(0, Math.round(t || 0));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(s).padStart(2, "0");
  }

  function parseTime(text) {
    text = (text || "").trim().replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace("٫", ".");
    if (!text) return null;
    const parts = text.split(":");
    if (parts.length > 3) return NaN;
    let t = 0;
    for (let i = 0; i < parts.length; i++) {
      if (!/^\d+(\.\d+)?$/.test(parts[i])) return NaN;
      const v = Number(parts[i]);
      if (i > 0 && v >= 60) return NaN;
      t = t * 60 + v;
    }
    return t;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  let optErr = null;
  function optionsPanel() {
    const box = el("div", "opts");
    const head = el("label", "clip-head");
    const check = el("input");
    check.type = "checkbox";
    check.checked = opts.clip;
    head.append(check, el("span", "", "✂  Download only a part"));
    const row = el("div", "clip-row");
    row.hidden = !opts.clip;
    const field = (label, key, placeholder) => {
      const f = el("label", "field");
      const input = el("input");
      input.placeholder = placeholder;
      input.value = opts[key];
      input.inputMode = "decimal";
      input.addEventListener("input", () => { opts[key] = input.value; input.classList.remove("bad"); optErr.textContent = ""; });
      const now = el("button", "now", "Now");
      now.title = "Use the video's current time";
      now.addEventListener("click", (e) => {
        e.preventDefault();
        if (video) { input.value = opts[key] = fmtTime(video.currentTime); input.classList.remove("bad"); }
      });
      f.append(el("span", "", label), input, now);
      return [f, input];
    };
    const [fromField, fromInput] = field("From", "start", "0:00");
    const [toField, toInput] = field("To", "end", "end");
    const length = video && isFinite(video.duration) && video.duration > 0 ? "Video length " + fmtTime(video.duration) + " · " : "";
    row.append(fromField, toField, el("div", "hint", length + "Times like 1:20 or 1:02:03"));
    check.addEventListener("change", () => {
      opts.clip = check.checked;
      row.hidden = !opts.clip;
      if (opts.clip && !opts.start && video && video.currentTime > 1) {
        fromInput.value = opts.start = fmtTime(video.currentTime); // start where the video is now
      }
      if (opts.clip) (opts.start ? toInput : fromInput).focus();
      place();
    });
    const chips = el("div", "chips");
    chips.append(el("div", "opt-title", "Format"));
    for (const [value, label] of FORMATS) {
      const c = el("button", "chip" + ((value === "m4a" ? opts.audio : !opts.audio && opts.container === value) ? " on" : ""), label);
      c.title = value === "m4a" ? "Only the sound" : value ? "Save as " + label + " (the Tondar window shows what the site offers)" : "Whatever is best on the site";
      c.addEventListener("click", (e) => {
        e.preventDefault();
        opts.audio = value === "m4a";
        opts.container = value;
        for (const x of chips.querySelectorAll(".chip")) x.classList.toggle("on", x === c);
      });
      chips.append(c);
    }
    optErr = el("div", "opt-err");
    box.append(head, row, chips, optErr);
    box._inputs = [fromInput, toInput];
    return box;
  }

  // The options as fields of the download request, or {error}.
  function chosenOptions(panel) {
    const extra = {};
    if (opts.clip) {
      const start = parseTime(opts.start), end = parseTime(opts.end);
      const [fromInput, toInput] = panel._inputs;
      if (Number.isNaN(start)) { fromInput.classList.add("bad"); return { error: "Write the start like 1:20" }; }
      if (Number.isNaN(end)) { toInput.classList.add("bad"); return { error: "Write the end like 2:05 (or leave it empty)" }; }
      if (end != null && end <= (start || 0)) { toInput.classList.add("bad"); return { error: "The end must come after the start" }; }
      if (start || end != null) extra.clip = { start: start || 0, end: end == null ? -1 : end };
    }
    if (opts.container) extra.container = opts.container;
    if (opts.audio) extra.audio = true;
    return { extra };
  }

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
    const panel = optionsPanel();
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
        const chosen = chosenOptions(panel);
        if (chosen.error) { optErr.textContent = chosen.error; return; }
        note("Sending to Tondar…");
        let r;
        try {
          r = await chrome.runtime.sendMessage({ type: "download", req: { ...opt.req, ...chosen.extra } });
        } catch (err) {
          r = { ok: false, error: "Extension was updated — reload this page." };
        }
        note(r.ok ? "✓ Sent to Tondar" : "✗ " + r.error, r.ok ? "ok" : "err");
        setTimeout(() => { closeMenu(); scheduleHide(); }, 1500);
      });
      menu.appendChild(b);
    }
    menu.appendChild(panel);
    place();
  }
})();

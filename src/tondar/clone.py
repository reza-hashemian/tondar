"""Website cloning: saves a site's pages together with their pictures, styles, scripts and fonts,
with the links between them rewritten so the copy works offline (like `wget --mirror -k -p`).

Files are saved as they arrive; the links are rewritten in one pass at the end, when every
file's local name is known. Pausing keeps a small state file, so a clone resumes where it was."""

import codecs
import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib

from .http_task import DEFAULT_UA, build_opener

STATE_FILE = ".tondar-clone.json"
# What was saved last time (address, ETag / Last-Modified, links): cloning into the same folder
# again asks the server "changed since?" and only downloads what did change.
CACHE_FILE = ".tondar-cache.json"
CHUNK = 64 * 1024
PAGE_EXTS = {"", "html", "htm", "xhtml", "shtml", "php", "php3", "asp", "aspx", "jsp", "jspx", "cfm", "cgi", "pl", "do"}
CSS_EXTS = {"css"}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
SKIP_SCHEMES = ("mailto:", "javascript:", "data:", "tel:", "sms:", "about:", "blob:", "file:", "ftp:", "#")
# Link types of <link rel=…> that a page needs to look right.
RES_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "apple-touch-icon-precomposed", "preload",
            "modulepreload", "manifest", "mask-icon", "image_src"}

# One regex walks the document: comments, <script>/<style> blocks (their content isn't HTML) and tags.
# Quoted attribute values may hold ">" but not "<"; a stray quote doesn't swallow the rest of the page.
_ATTRS = r"""(?:[^>"']|"[^"<]*"|'[^'<]*'|["'])*"""
TOKEN = re.compile(
    r"<!--.*?-->"
    r"|<(?P<blk>script|style)\b(?P<battrs>" + _ATTRS + r")>(?P<body>.*?)</(?P=blk)\s*>"
    r"|<(?P<tag>[a-zA-Z][\w:-]*)(?P<attrs>" + _ATTRS + r")>",
    re.S | re.I)
ATTR = re.compile(r"""([^\s=/>"']+)(?:(\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")
CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"\s]*))\s*\)|@import\s+(?:"([^"]*)"|'([^']*)')""", re.I)
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)""", re.I)
REFRESH_URL = re.compile(r"""^(\s*\d+\s*[;,]\s*url\s*=\s*)['"]?([^'"]+)['"]?\s*$""", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
INTEGRITY = re.compile(r"""\s(?:integrity|crossorigin)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?""", re.I)

URL_ATTRS = {
    "a": {"href": "page"}, "area": {"href": "page"},
    "iframe": {"src": "frame"}, "frame": {"src": "frame"},
    "link": {"href": "link"},
    "script": {"src": "res"},
    "img": {"src": "res", "srcset": "srcset", "data-src": "res", "data-srcset": "srcset",
            "data-original": "res", "data-lazy-src": "res", "data-fallback-src": "res"},
    "source": {"src": "res", "srcset": "srcset", "data-src": "res", "data-srcset": "srcset"},
    "video": {"src": "res", "poster": "res"}, "audio": {"src": "res"}, "track": {"src": "res"},
    "embed": {"src": "res"}, "object": {"data": "res"}, "input": {"src": "res"},
    "body": {"background": "res"}, "table": {"background": "res"}, "td": {"background": "res"},
    "th": {"background": "res"},
    "meta": {"content": "meta"},
}
WIN_BAD = re.compile(r'[<>:"\\|?*\x00-\x1f]')
WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.I)


class TooBig(Exception):
    pass


# Query parameters that only track where a visitor came from: the same page without them.
TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|dclid|gbraid|wbraid|msclkid|yclid|mc_cid|mc_eid|igshid|_ga|_gl|"
                      r"ref_src|spm|__s|_hsenc|_hsmi|mkt_tok|oly_enc_id|oly_anon_id|vero_id|si)$", re.I)
# Second-level names under which a site's own domain has three parts (example.co.uk, example.ac.ir).
SECOND_LEVEL = {"co", "com", "net", "org", "ac", "gov", "edu", "or", "ne", "go", "gob", "nic", "sch", "id", "ltd", "plc"}


def normalize(url):
    """Comparable form of a link: no fragment, lower-case host, no default port, "/" for an empty path,
    query parameters sorted and tracking ones (utm_…, fbclid…) left out."""
    try:
        u = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    host = u.hostname.lower()
    try:
        port = u.port
    except ValueError:
        return None
    if port and not ((u.scheme == "http" and port == 80) or (u.scheme == "https" and port == 443)):
        host += f":{port}"
    path = u.path or "/"
    # Spaces and non-ASCII characters in links: one spelling per file.
    path = urllib.parse.quote(urllib.parse.unquote(path), safe="/%:@!$&'()*+,;=-._~")
    query = u.query
    if query:
        params = [p for p in query.split("&") if p and not TRACKING.match(p.split("=", 1)[0])]
        query = "&".join(sorted(params))
    return urllib.parse.urlunsplit((u.scheme.lower(), host, path, query, ""))


def page_key(url):
    """One key for the addresses of the same page: "/dir/" and "/dir/index.html"."""
    head, _, last = url.rpartition("/")
    base, sep, query = last.partition("?")
    if base.lower() in ("index.html", "index.htm"):
        return head + "/" + (sep + query if sep else "")
    return url


def site_domain(host):
    """The site's own domain of a host name: blog.example.com → example.com, www.x.co.uk → x.co.uk."""
    host = host.split(":")[0]
    parts = host.split(".")
    if len(parts) <= 2 or re.fullmatch(r"[\d.]+", host):
        return host
    if len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _same_page(a, b):
    """True for "https://x/dir/" and "https://x/dir/index.html" (same query)."""
    a, b = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    if (a.scheme, a.netloc, a.query) != (b.scheme, b.netloc, b.query):
        return False
    pa, pb = sorted((a.path or "/", b.path or "/"), key=len)
    return pa.endswith("/") and pb[len(pa):].lower() in ("index.html", "index.htm") and pb.startswith(pa)


def resolve(base, raw):
    raw = (raw or "").strip()
    if not raw or raw.lower().startswith(SKIP_SCHEMES):
        return None
    raw = raw.replace("&amp;", "&")
    try:
        return normalize(urllib.parse.urljoin(base, raw))
    except ValueError:
        return None


def url_ext(url):
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def safe_segment(seg, limit=100):
    """A path segment that works on Windows, macOS and Linux (clones get copied around)."""
    seg = WIN_BAD.sub("_", seg).strip().rstrip(". ")
    if WIN_RESERVED.match(seg):
        seg = "_" + seg
    if len(seg) > limit:
        base, dot, ext = seg.rpartition(".")
        if not dot or len(ext) > 10:
            base, ext = seg, ""
        digest = hashlib.sha1(seg.encode()).hexdigest()[:8]
        seg = base[:limit - len(ext) - 10] + "-" + digest + ("." + ext if ext else "")
    return seg or "_"


def decode(raw, ctype_charset=None):
    """(text, codec name) of an HTML/CSS document; undecodable bytes survive a round trip."""
    for name in (ctype_charset, _sniff_charset(raw), "utf-8"):
        if not name:
            continue
        try:
            codec = codecs.lookup(name).name
        except LookupError:
            continue
        return raw.decode(codec, "surrogateescape"), codec
    return raw.decode("utf-8", "surrogateescape"), "utf-8"


def _sniff_charset(raw):
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    m = META_CHARSET.search(raw[:4096])
    return m.group(1).decode("ascii", "ignore") if m else None


def _encode(text, codec):
    try:
        return text.encode(codec, "surrogateescape")
    except UnicodeEncodeError:
        return text.encode(codec, "xmlcharrefreplace")


# ---------------------------------------------------------------------------------------------
# Finding and rewriting links. `on_url(kind, absolute_or_None, raw) -> replacement or None`.
def transform_css(text, base, on_url):
    def sub(m):
        raw = next(g for g in m.groups() if g is not None) if any(g is not None for g in m.groups()) else ""
        new = on_url("res", resolve(base, raw), raw)
        if new is None:
            return m.group(0)
        return f'url("{new}")' if m.group(0)[:1].lower() == "u" else f'@import "{new}"'
    return CSS_URL.sub(sub, text)


def _srcset(value, base, on_url):
    parts, changed = [], False
    for part in value.split(","):
        bits = part.strip().split(None, 1)
        if not bits:
            continue
        new = on_url("res", resolve(base, bits[0]), bits[0])
        if new is not None:
            bits[0], changed = new, True
        parts.append(" ".join(bits))
    return ", ".join(parts) if changed else None


def _rewrite_attrs(tag, attrs, base, on_url):
    """New attribute text of one tag (or None when nothing changed)."""
    kinds = URL_ATTRS.get(tag, {})
    found = [(m, m.group(1).lower()) for m in ATTR.finditer(attrs)]
    names = {name: html.unescape(m.group(3) if m.group(3) is not None else m.group(4) if m.group(4) is not None
                                 else m.group(5) or "")
             for m, name in found}
    out, pos, changed, local = [], 0, False, False
    for m, name in found:
        if m.group(2) is None:
            continue
        value = html.unescape(m.group(3) if m.group(3) is not None else m.group(4) if m.group(4) is not None
                              else m.group(5) or "")
        kind = kinds.get(name)
        new = None
        if name == "style":
            css = transform_css(value, base, on_url)
            new = css if css != value else None
        elif kind == "srcset":
            new = _srcset(value, base, on_url)
        elif kind == "link":
            rels = set((names.get("rel") or "").lower().split())
            kind = "res" if rels & RES_RELS else "page" if rels & {"alternate", "next", "prev"} and \
                "stylesheet" not in rels else None
            if kind:
                new = on_url(kind, resolve(base, value), value)
        elif kind == "meta":
            refresh = (names.get("http-equiv") or "").lower() == "refresh"
            prop = (names.get("property") or names.get("name") or "").lower()
            if refresh:
                r = REFRESH_URL.match(value)
                if r:
                    target = on_url("page", resolve(base, r.group(2)), r.group(2))
                    new = r.group(1) + target if target is not None else None
            elif prop in ("og:image", "twitter:image", "msapplication-tileimage"):
                new = on_url("meta", resolve(base, value), value)
        elif kind:
            new = on_url(kind, resolve(base, value), value)
        if new is not None:
            local = True
        if new is not None and new != value:
            q = "'" if '"' in new else '"'
            new = new.replace("&", "&amp;").replace(q, "&#39;" if q == "'" else "&quot;")
            out.append(attrs[pos:m.start()])
            out.append(f"{m.group(1)}={q}{new}{q}")
            pos, changed = m.end(), True
    if local and tag in ("link", "script") and INTEGRITY.search(attrs):
        changed = True  # saved copies (styles get rewritten) no longer match the hash
    if not changed:
        return None
    out.append(attrs[pos:])
    text = "".join(out)
    if local and tag in ("link", "script"):
        text = INTEGRITY.sub("", text)
    return text


def transform_html(text, page_url, on_url, drop_base=False):
    """Walk an HTML document, calling on_url for every link; returns the rewritten text."""
    base = page_url
    m = re.search(r"""<base\b[^>]*\bhref\s*=\s*["']?([^"'\s>]+)""", text, re.I)
    if m:
        base = urllib.parse.urljoin(page_url, m.group(1).replace("&amp;", "&"))

    def sub(t):
        if t.group(0).startswith("<!--"):
            return t.group(0)
        if t.group("blk"):
            blk = t.group("blk").lower()
            attrs = _rewrite_attrs(blk, t.group("battrs"), base, on_url)
            body = t.group("body")
            if blk == "style":
                body = transform_css(body, base, on_url)
            if attrs is None and body == t.group("body"):
                return t.group(0)
            a = attrs if attrs is not None else t.group("battrs")
            return f"<{t.group('blk')}{a}>{body}</{t.group('blk')}>"
        tag = t.group("tag").lower()
        if tag == "base" and drop_base:
            return ""  # every link was made relative to the saved file
        attrs = _rewrite_attrs(tag, t.group("attrs"), base, on_url)
        return t.group(0) if attrs is None else f"<{t.group('tag')}{attrs}>"
    return TOKEN.sub(sub, text)


# ---------------------------------------------------------------------------------------------
class SiteTask:
    """Clones the website at item.url into item.path (a folder)."""

    def __init__(self, item, limiter, on_done, proxy=None):
        self.item = item
        self.limiter = limiter
        self.on_done = on_done
        self.proxy = proxy
        self.stopped = threading.Event()
        self.resolve_folder = None
        self.claim_name = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def start(self):
        threading.Thread(target=self._run, daemon=True, name=f"site-{self.item.id[:8]}").start()

    def stop(self):
        self.stopped.set()
        with self._cond:
            self._cond.notify_all()

    def _run(self):
        error = None
        try:
            self._main()
        except Exception as e:  # noqa: BLE001 - reported to the UI
            error = str(e) or e.__class__.__name__
        self.on_done(self, error)

    # --- setup ----------------------------------------------------------------------------------
    def _main(self):
        it = self.item
        self.root = it.path
        os.makedirs(self.root, exist_ok=True)
        self.opener = build_opener(it, self.proxy)
        self.ua = it.user_agent or DEFAULT_UA
        start = normalize(it.url)
        if not start:
            raise RuntimeError("This isn't a web address (it must start with http:// or https://)")
        self.start_url = start
        host = urllib.parse.urlsplit(start).netloc
        bare = host[4:] if host.startswith("www.") else host
        self.hosts = {bare, "www." + bare}
        self.scope = getattr(it, "clone_scope", "site") or "site"
        self.domain = site_domain(bare)
        self.max_depth = int(it.clone_depth)  # -1 = no limit
        self.max_pages = max(1, int(it.clone_max_pages or 1))
        self.max_bytes = int(it.clone_max_mb or 0) * 1024 * 1024
        self.urls = {}  # normalized url -> relative path of its file
        self.files = {}  # relative path -> {"url": final url, "type": "html"|"css"|"other"}
        self.failed = {}  # url -> reason
        self.seen = set()  # page_key() of every address queued or saved
        self.queue = []  # (url, kind, depth, referer)
        self.pages = 0
        self.busy = 0
        self.robots = None
        self.hashes = {}  # sha1 of a file's content -> its relative path: one copy of identical files
        self.cache = self._load_cache()  # url -> what was saved last time
        self.reused = 0
        if it.done == 0 or not self._load_state():
            self._reset()
            with self._cond:
                self._add(start, "page", 0, "", force=True)
        if it.clone_robots:
            self.robots = self._read_robots(start)
        self._crawl()
        if self.stopped.is_set():
            self._save_state()
            return
        if start not in self.urls:
            reason = self.failed.get(start, "the page could not be downloaded")
            raise RuntimeError(f"Couldn't open {it.url}: {reason}")
        self._rewrite_all()
        self._save_cache()
        it.site_entry = self.urls[start]
        it.files_total = it.files_done
        it.files_failed = len(self.failed)
        it.size = it.done
        try:
            os.unlink(os.path.join(self.root, STATE_FILE))
        except OSError:
            pass
        self._write_failures()

    def _reset(self):
        it = self.item
        it.done, it.files_done, it.files_total, it.files_failed = 0, 0, 0, 0
        try:
            os.unlink(os.path.join(self.root, STATE_FILE))
        except OSError:
            pass

    def _read_robots(self, start):
        u = urllib.parse.urlsplit(start)
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{u.scheme}://{u.netloc}/robots.txt", headers={"User-Agent": self.ua})
            with self.opener.open(req, timeout=20) as r:
                rp.parse(r.read(512 * 1024).decode("utf-8", "replace").splitlines())
        except Exception:  # noqa: BLE001 - no robots.txt: everything is allowed
            return None
        return rp

    # --- the queue ------------------------------------------------------------------------------
    def _in_scope(self, url):
        """On the website that is cloned (with or without "www."): saved in the main folder."""
        return urllib.parse.urlsplit(url).netloc in self.hosts

    def _follow(self, url):
        """May pages at `url` be cloned? Depends on "Only this website" / "Include subdomains"."""
        if self._in_scope(url) or self.scope == "all":
            return True
        if self.scope == "subdomains":
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
            return host == self.domain or host.endswith("." + self.domain)
        return False

    def _add(self, url, kind, depth, referer, force=False):
        """Queue a link found in a page (called with the lock held)."""
        if not url or page_key(url) in self.seen:
            return
        it = self.item
        inside = self._follow(url)
        ext = url_ext(url)
        if kind == "page":
            if not inside:
                return
            if ext not in PAGE_EXTS and ext not in CSS_EXTS:
                if not it.clone_files:
                    return
                kind = "file"  # a PDF, ZIP, video… linked from the site
            else:
                if not force and (0 <= self.max_depth < depth or self.pages >= self.max_pages):
                    return
                if self.robots and not self.robots.can_fetch(self.ua, url) and not force:
                    return
                self.pages += 1
        elif kind == "frame":
            if not inside:
                return
            if self.pages >= self.max_pages:
                return
            self.pages += 1
            kind = "page"
        elif kind in ("res", "meta"):
            if not inside and not it.clone_external:
                return
            kind = "res"
        self.seen.add(page_key(url))
        self.queue.append((url, kind, depth, referer))
        it.files_total = it.files_done + len(self.queue) + self.busy
        self._cond.notify()

    def _crawl(self):
        workers = [threading.Thread(target=self._worker, daemon=True) for _ in range(max(1, min(self.item.max_segments, 16)))]
        for w in workers:
            w.start()
        last_save = time.monotonic()
        while any(w.is_alive() for w in workers):
            for w in workers:
                w.join(0.5)
            if time.monotonic() - last_save > 15 and not self.stopped.is_set():
                with self._lock:
                    self._save_state()
                last_save = time.monotonic()

    def _worker(self):
        while True:
            with self._cond:
                while not self.queue and self.busy and not self.stopped.is_set():
                    self._cond.wait(0.5)
                if self.stopped.is_set() or (not self.queue and not self.busy):
                    self._cond.notify_all()
                    return
                # Pages first (breadth first), so a page limit keeps the pages closest to the start.
                url, kind, depth, referer = self.queue.pop(0)
                self.busy += 1
            try:
                self._fetch_one(url, kind, depth, referer)
            except TooBig:
                with self._lock:
                    self.failed[url] = "larger than the size limit"
            except Exception as e:  # noqa: BLE001 - one broken file doesn't stop the clone
                with self._lock:
                    self.failed[url] = str(e) or e.__class__.__name__
            finally:
                with self._cond:
                    self.busy -= 1
                    it = self.item
                    it.files_failed = len(self.failed)
                    it.files_total = it.files_done + len(self.queue) + self.busy + it.files_failed
                    self._cond.notify_all()

    # --- downloading ------------------------------------------------------------------------------
    def _fetch_one(self, url, kind, depth, referer):
        with self._lock:
            if url in self.urls:
                return  # saved meanwhile under another address that redirected here
        headers = {"User-Agent": self.ua, "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
        if kind == "page":
            headers["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"
        if referer:
            headers["Referer"] = referer
        old = self._cached(url)
        if old:
            if old.get("etag"):
                headers["If-None-Match"] = old["etag"]
            if old.get("modified"):
                headers["If-Modified-Since"] = old["modified"]
        for attempt in range(3):
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    self._save(r, url, kind, depth)
                return
            except urllib.error.HTTPError as e:
                if e.code == 304 and old:
                    self._reuse(url, old, depth)  # unchanged since the last clone
                    return
                if e.code < 500 or attempt == 2:
                    raise RuntimeError(f"HTTP {e.code}") from None
            except (TooBig, OSError) as e:
                if isinstance(e, TooBig) or self.stopped.is_set() or attempt == 2:
                    raise
            time.sleep(1 + attempt * 2)

    def _assign(self, url, final, ctype):
        """Local path (relative, with "/") for a downloaded file; called with the lock held."""
        u = urllib.parse.urlsplit(final)
        segs = [s for s in urllib.parse.unquote(u.path).split("/") if s not in ("", ".", "..")]
        is_html = ctype in HTML_TYPES
        if u.path.endswith("/") or not segs:
            segs.append("index.html" if is_html or ctype == "" else "index")
        if not self._in_scope(final):
            segs = ["_external", u.netloc.replace(":", "_")] + segs
        name = segs[-1]
        base, dot, ext = name.rpartition(".")
        if not dot:
            base, ext = name, ""
        if u.query:
            base += "-" + hashlib.sha1(u.query.encode()).hexdigest()[:8]
        ext_l = ext.lower()
        if is_html and ext_l not in ("html", "htm", "xhtml"):
            ext = (ext + "." if ext else "") + "html"
        elif ctype == "text/css" and ext_l != "css":
            ext = (ext + "." if ext else "") + "css"
        elif not ext:
            guess = mimetypes.guess_extension(ctype or "") or ""
            ext = guess.lstrip(".")
        segs[-1] = base + ("." + ext if ext else "")
        segs = [safe_segment(s) for s in segs]
        rel = "/".join(segs)
        # Windows: keep the whole path short enough
        if len(os.path.join(self.root, rel)) > 240:
            rel = "_long/" + hashlib.sha1(final.encode()).hexdigest()[:16] + ("." + ext if ext else "")
        n, candidate = 2, rel
        if candidate in self.files and _same_page(self.files[candidate]["url"], final):
            return candidate  # "dir/" and "dir/index.html": one file, not index.html and index-2.html
        while candidate in self.files and self.files[candidate]["url"] != final:
            stem, dot, e = rel.rpartition(".")
            candidate = f"{stem}-{n}.{e}" if dot and "/" not in e else f"{rel}-{n}"
            n += 1
        return candidate

    def _cached(self, url):
        """What the last clone into this folder saved for `url`, if its file is still there."""
        old = self.cache.get(url)
        if old and old.get("rel") and os.path.isfile(os.path.join(self.root, *old["rel"].split("/"))):
            return old
        return None

    def _reuse(self, url, old, depth):
        """Keep the file from the last clone (the server says it didn't change) and follow its links again."""
        rel = old["rel"]
        with self._lock:
            final = old.get("url") or url
            self.urls[url] = self.urls[final] = rel
            # Already rewritten for offline use last time: don't rewrite it again.
            self.files[rel] = {"url": final, "type": "done", "links": old.get("links") or [],
                               **{k: old[k] for k in ("etag", "modified", "sha1") if old.get(k)}}
            self.seen.add(page_key(final))
            if old.get("sha1"):
                self.hashes.setdefault(old["sha1"], rel)
            self.item.files_done += 1
            self.reused += 1
            for kind, link in old.get("links") or []:
                self._add(link, kind, depth + 1 if kind == "page" else depth, final)
            self._cond.notify_all()

    def _save(self, r, url, kind, depth):
        it = self.item
        final = normalize(r.geturl()) or url
        with self._lock:
            if final != url and final in self.urls:  # redirected to a file we already have
                self.urls[url] = self.urls[final]
                it.files_done += 1
                return
        ctype = r.headers.get_content_type() if r.headers.get("Content-Type") else ""
        length = r.headers.get("Content-Length")
        limit = self.max_bytes if kind in ("file", "res") else 0
        if limit and length and length.isdigit() and int(length) > limit:
            raise TooBig()
        ftype = "html" if ctype in HTML_TYPES else "css" if ctype == "text/css" else "other"
        with self._lock:
            rel = self.urls.get(final) or self._assign(url, final, ctype)
            other = self.files.get(rel)
            if other and other["url"] != final:  # the same page under its other address
                self.urls[url] = self.urls[final] = rel
                self.seen.add(final)
                it.files_done += 1
                return
            self.files[rel] = {"url": final, "type": ftype,
                               "etag": r.headers.get("ETag") or "", "modified": r.headers.get("Last-Modified") or ""}
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        inflate = zlib.decompressobj(16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS) \
            if enc in ("gzip", "x-gzip", "deflate") else None
        keep = ftype in ("html", "css")
        body = bytearray()
        tmp = path + ".part"
        digest = hashlib.sha1()
        try:
            self._receive(r, tmp, inflate, keep, body, limit, digest)
        except BaseException:
            with self._lock:
                if self.files.get(rel, {}).get("url") == final and rel not in self.urls.values():
                    del self.files[rel]
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if self.stopped.is_set():
            try:
                os.unlink(tmp)
            except OSError:
                pass
            with self._lock:
                self.files.pop(rel, None)
                self.queue.insert(0, (url, kind, depth, ""))
            return
        sha1 = digest.hexdigest()
        with self._lock:
            same = self.hashes.get(sha1)
            if same and same != rel and os.path.isfile(os.path.join(self.root, *same.split("/"))):
                # The same content under another address (session ids, sorting parameters…): one copy.
                self.files.pop(rel, None)
                self.urls[url] = self.urls[final] = same
                self.seen.add(page_key(final))
                it.files_done += 1
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return
            self.hashes[sha1] = rel
            self.files[rel]["sha1"] = sha1
        os.replace(tmp, path)
        with self._lock:
            self.urls[url] = self.urls[final] = rel
            self.seen.add(page_key(final))
            it.files_done += 1
            if ftype == "html" and url == self.start_url and not it.title:
                m = TITLE.search(bytes(body[:65536]).decode("utf-8", "replace"))
                if m:
                    it.title = " ".join(m.group(1).split())[:150]
        if keep:
            self._discover(bytes(body), ftype, final, depth, r.headers.get_content_charset())

    def _receive(self, r, tmp, inflate, keep, body, limit, digest):
        it = self.item
        size = 0
        with open(tmp, "wb") as f:
            while True:
                if self.stopped.is_set():
                    break
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                self.limiter.consume(len(chunk))
                with self._lock:
                    it.done += len(chunk)
                if inflate:
                    chunk = inflate.decompress(chunk)
                size += len(chunk)
                if limit and size > limit:
                    raise TooBig()
                f.write(chunk)
                digest.update(chunk)
                if keep:
                    body += chunk
            if inflate and not self.stopped.is_set():
                rest = inflate.flush()
                f.write(rest)
                digest.update(rest)
                body += rest if keep else b""

    def _discover(self, raw, ftype, page_url, depth, charset=None):
        text, _codec = decode(raw, charset)
        found = []

        def on_url(kind, url, _raw):
            if url:
                found.append((kind, url))
            return None

        if ftype == "html":
            transform_html(text, page_url, on_url)
        else:
            transform_css(text, page_url, on_url)
        with self._lock:
            rel = self.urls.get(page_url)
            if rel in self.files:
                self.files[rel]["links"] = found  # for the next clone into this folder
            for kind, url in found:
                self._add(url, kind, depth + 1 if kind == "page" else depth, page_url)

    # --- the end: links that work offline -------------------------------------------------------------
    def _rewrite_all(self):
        for rel, info in list(self.files.items()):
            if info["type"] not in ("html", "css") or self.stopped.is_set():
                continue
            path = os.path.join(self.root, *rel.split("/"))
            try:
                with open(path, "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            text, codec = decode(raw)
            here = posixpath.dirname(rel)

            def on_url(kind, url, raw_value, here=here):
                if not url:
                    return None
                frag = ""
                if "#" in raw_value:
                    frag = "#" + raw_value.split("#", 1)[1]
                target = self.urls.get(url) or self.urls.get(page_key(url))
                if target is None:
                    # Not saved (outside the site, over a limit): keep a working online link.
                    return None if raw_value.startswith(("http://", "https://")) else url + frag
                link = posixpath.relpath(target, here or ".")
                return urllib.parse.quote(link, safe="/-._~!$&'()*+,;=:@") + frag

            if info["type"] == "html":
                new = transform_html(text, info["url"], on_url, drop_base=True)
            else:
                new = transform_css(text, info["url"], on_url)
            if new != text:
                with open(path, "wb") as f:
                    f.write(_encode(new, codec))

    def _write_failures(self):
        path = os.path.join(self.root, "_tondar-failed.txt")
        if not self.failed:
            try:
                os.unlink(path)
            except OSError:
                pass
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("Files Tondar couldn't save while cloning this website:\n\n")
            for url, why in sorted(self.failed.items()):
                f.write(f"{url}\t{why}\n")

    # --- what was saved, for the next clone into this folder ----------------------------------------
    def _load_cache(self):
        try:
            with open(os.path.join(self.root, CACHE_FILE), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data.get("files") or {} if data.get("start") == self.start_url else {}

    def _save_cache(self):
        files = {}
        for url, rel in self.urls.items():
            info = self.files.get(rel)
            if not info:
                continue
            entry = {"rel": rel, "url": info["url"]}
            for key in ("etag", "modified", "sha1", "links"):
                if info.get(key):
                    entry[key] = info[key]
            files[url] = entry
        tmp = os.path.join(self.root, CACHE_FILE + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"start": self.start_url, "files": files}, f)
            os.replace(tmp, os.path.join(self.root, CACHE_FILE))
        except OSError:
            pass

    # --- pause / resume ------------------------------------------------------------------------------
    def _save_state(self):
        state = {"start": self.start_url, "urls": self.urls, "files": self.files, "failed": self.failed,
                 "queue": self.queue, "pages": self.pages}
        tmp = os.path.join(self.root, STATE_FILE + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, os.path.join(self.root, STATE_FILE))
        except OSError:
            pass

    def _load_state(self):
        try:
            with open(os.path.join(self.root, STATE_FILE), encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return False
        if state.get("start") != self.start_url:
            return False
        self.urls = state.get("urls") or {}
        self.files = state.get("files") or {}
        self.pages = int(state.get("pages") or 0)
        self.queue = [tuple(q) for q in state.get("queue") or []]
        self.seen = {page_key(u) for u in set(self.urls) | {q[0] for q in self.queue} | {f["url"] for f in self.files.values()}}
        self.hashes = {f["sha1"]: rel for rel, f in self.files.items() if f.get("sha1")}
        # Failed files get another chance.
        for url in state.get("failed") or {}:
            self.queue.append((url, "res", 0, ""))
            self.seen.add(page_key(url))
        it = self.item
        it.files_done = len(self.files)
        it.files_total = it.files_done + len(self.queue)
        return True

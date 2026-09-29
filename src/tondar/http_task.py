"""Segmented, resumable HTTP(S) downloader with dynamic segment splitting."""

import http.cookiejar
import os
import re
import threading
import time
import urllib.error
import urllib.request

from .net import proxy_handlers
from .util import filename_from_disposition, filename_from_url, unique_path

CHUNK = 64 * 1024
MIN_SPLIT = 1024 * 1024  # never split a segment that has less than 2 MiB left
MAX_RETRIES = 10
READ_TIMEOUT = 20
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


class DownloadError(Exception):
    pass


class RateLimiter:
    """Global token bucket shared by every download (bytes per second, 0 = unlimited)."""

    def __init__(self):
        self.rate = 0
        self._allowance = 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n):
        if self.rate <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._allowance = min(self.rate, self._allowance + (now - self._last) * self.rate)
            self._last = now
            self._allowance -= n
            wait = -self._allowance / self.rate if self._allowance < 0 else 0
        if wait > 0:
            time.sleep(wait)


def build_opener(item, proxy=None):
    jar = http.cookiejar.CookieJar()
    for c in item.cookies or []:
        domain = c.get("domain", "")
        host_only = c.get("hostOnly", not domain.startswith("."))
        if not host_only and not domain.startswith("."):
            domain = "." + domain
        jar.set_cookie(
            http.cookiejar.Cookie(
                0, c.get("name", ""), c.get("value", ""), None, False,
                domain, not host_only, domain.startswith("."),
                c.get("path", "/"), True, bool(c.get("secure")),
                int(c["expirationDate"]) if c.get("expirationDate") else None,
                not c.get("expirationDate"), None, None, {},
            )
        )
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), *proxy_handlers(proxy))


def make_request(item, extra=None):
    headers = {"User-Agent": item.user_agent or DEFAULT_UA, "Accept": "*/*"}
    if item.referer:
        headers["Referer"] = item.referer
    headers.update(extra or {})
    return urllib.request.Request(item.url, headers=headers)


CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


def probe(item, opener=None, proxy=None):
    """Return (size, supports_ranges, filename, content_type) for item.url."""
    opener = opener or build_opener(item, proxy)
    with opener.open(make_request(item, {"Range": "bytes=0-"}), timeout=30) as r:
        size, ranges = -1, False
        if r.status == 206:
            m = CONTENT_RANGE.match(r.headers.get("Content-Range", ""))
            if m and m.group(3) != "*":
                size, ranges = int(m.group(3)), True
        elif r.headers.get("Content-Length"):
            size = int(r.headers["Content-Length"])
        name = filename_from_disposition(r.headers.get("Content-Disposition")) or filename_from_url(r.geturl())
        return size, ranges, name, r.headers.get_content_type()


def _permanent(exc):
    return isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code not in (408, 425, 429)


class HttpTask:
    def __init__(self, item, limiter, on_done, proxy=None):
        self.item = item
        self.proxy = proxy
        self.limiter = limiter
        self.on_done = on_done  # called from a worker thread: on_done(task, error_message_or_None)
        self.stopped = threading.Event()
        self._lock = threading.Lock()
        self._active = set()
        self._error = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name=f"dl-{self.item.id[:8]}").start()

    def stop(self):
        self.stopped.set()

    def _run(self):
        error = None
        try:
            self._main()
        except Exception as e:  # noqa: BLE001 - every failure is reported to the UI
            error = _describe(e)
        self.on_done(self, error)

    def _main(self):
        it = self.item
        self.opener = build_opener(it, self.proxy)
        os.makedirs(it.folder, exist_ok=True)

        if not it.filename or it.size < 0 or not it.segments or not os.path.exists(it.path + ".part"):
            size, ranges, name, _ = probe(it, self.opener)
            it.size, it.resumable = size, ranges and size > 0
            it.segments = []
            if not it.filename:
                it.filename = unique_path(it.folder, name or "download")
        part = it.path + ".part"

        if it.resumable:
            if not it.segments:
                with open(part, "wb") as f:
                    f.truncate(it.size)
                n = max(1, min(it.max_segments, it.size // MIN_SPLIT))
                step = it.size // n
                it.segments = [[i * step, (i + 1) * step - 1 if i < n - 1 else it.size - 1, i * step] for i in range(n)]
                it.done = 0
            else:
                it.done = sum(min(s[2], s[1] + 1) - s[0] for s in it.segments)
            workers = [threading.Thread(target=self._worker, args=(part,), daemon=True) for _ in range(it.max_segments)]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
            if self._error:
                raise self._error
            if self.stopped.is_set():
                return
            if any(s[2] <= s[1] for s in it.segments):
                raise DownloadError("Download ended before all parts were received")
        else:
            self._single_stream(part)
            if self.stopped.is_set():
                return

        final = it.path
        if os.path.exists(final):
            it.filename = unique_path(it.folder, it.filename)
            final = it.path
        os.replace(part, final)
        it.segments = []

    # --- non-resumable servers -------------------------------------------------
    def _single_stream(self, part):
        it = self.item
        it.done = 0
        with self.opener.open(make_request(it), timeout=READ_TIMEOUT) as r, open(part, "wb") as f:
            if it.size < 0 and r.headers.get("Content-Length"):
                it.size = int(r.headers["Content-Length"])
            while not self.stopped.is_set():
                data = r.read(CHUNK)
                if not data:
                    break
                self.limiter.consume(len(data))
                f.write(data)
                it.done += len(data)
        if not self.stopped.is_set() and it.size > 0 and it.done != it.size:
            raise DownloadError(f"Connection closed after {it.done} of {it.size} bytes")

    # --- segmented download --------------------------------------------------
    def _take_segment(self):
        segs = self.item.segments
        with self._lock:
            for i, s in enumerate(segs):
                if i not in self._active and s[2] <= s[1]:
                    self._active.add(i)
                    return i
            # Nothing left unassigned: steal the second half of the largest running segment.
            best, best_left = None, 2 * MIN_SPLIT
            for i in self._active:
                left = segs[i][1] - segs[i][2] + 1
                if left > best_left:
                    best, best_left = i, left
            if best is None:
                return None
            s = segs[best]
            mid = s[2] + best_left // 2
            segs.append([mid, s[1], mid])
            s[1] = mid - 1
            self._active.add(len(segs) - 1)
            return len(segs) - 1

    def _worker(self, part):
        try:
            with open(part, "r+b", buffering=0) as f:
                while not self.stopped.is_set():
                    i = self._take_segment()
                    if i is None:
                        return
                    try:
                        self._fetch_segment(i, f)
                    finally:
                        with self._lock:
                            self._active.discard(i)
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._error = self._error or e
            self.stopped.set()

    def _fetch_segment(self, i, f):
        it = self.item
        s = it.segments[i]
        attempts = 0
        while not self.stopped.is_set() and s[2] <= s[1]:
            try:
                req = make_request(it, {"Range": f"bytes={s[2]}-{s[1]}"})
                with self.opener.open(req, timeout=READ_TIMEOUT) as r:
                    if r.status != 206:
                        raise DownloadError("Server stopped supporting resume (link may have expired)")
                    m = CONTENT_RANGE.match(r.headers.get("Content-Range", ""))
                    if not m or int(m.group(1)) != s[2] or (m.group(3) != "*" and int(m.group(3)) != it.size):
                        raise DownloadError("File on the server has changed")
                    while not self.stopped.is_set():
                        data = r.read(CHUNK)
                        if not data:
                            break
                        self.limiter.consume(len(data))
                        with self._lock:
                            pos = s[2]
                            n = min(len(data), s[1] - pos + 1)
                        # Write before advancing the position so a crash never records unwritten bytes.
                        _pwrite_all(f, data[:n], pos)
                        with self._lock:
                            s[2] += n
                            it.done += n
                        attempts = 0
                        if s[2] > s[1]:
                            return
                if s[2] <= s[1] and not self.stopped.is_set():
                    raise ConnectionError("connection closed early")
            except DownloadError:
                raise
            except Exception as e:  # noqa: BLE001
                if _permanent(e):
                    raise
                attempts += 1
                if attempts > MAX_RETRIES:
                    raise
                self.stopped.wait(min(30, 2 * attempts))


def _pwrite_all(f, data, pos):
    view = memoryview(data)
    if not hasattr(os, "pwrite"):  # Windows: every worker has its own handle, so seek + write is safe
        f.seek(pos)
        while view:
            view = view[f.write(view):]
        return
    while view:
        n = os.pwrite(f.fileno(), view, pos)
        view, pos = view[n:], pos + n


def _describe(e):
    if isinstance(e, urllib.error.HTTPError):
        hint = {403: " (link expired or login needed)", 404: " (file not found)", 410: " (link expired)"}.get(e.code, "")
        return f"HTTP {e.code} {e.reason}{hint}"
    if isinstance(e, urllib.error.URLError):
        return f"Network error: {e.reason}"
    return str(e) or e.__class__.__name__

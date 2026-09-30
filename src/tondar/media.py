"""Video/stream downloads (YouTube, HLS .m3u8, DASH, ...) through yt-dlp."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

from .net import proxy_handlers
from .util import WINDOWS, app_dir, clean_page_title, data_dir, sanitize_filename

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/" + ("yt-dlp.exe" if WINDOWS else "yt-dlp")
PROGRESS = "download:TONDAR|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s"


def private_ytdlp():
    return os.path.join(data_dir(), "bin", "yt-dlp.exe" if WINDOWS else "yt-dlp")


def ytdlp_command():
    """Prefer our own always-up-to-date copy, then the one bundled with the app, then the system one."""
    own = private_ytdlp()
    if os.path.exists(own):
        return [own] if WINDOWS else [sys.executable, own]
    bundled = os.path.join(app_dir(), "tools", "yt-dlp.exe")
    if WINDOWS and os.path.exists(bundled):
        return [bundled]
    system = shutil.which("yt-dlp")
    return [system] if system else None


def _ffmpeg_args():
    bundled = os.path.join(app_dir(), "tools", "ffmpeg")
    return ["--ffmpeg-location", bundled] if WINDOWS and os.path.isdir(bundled) else []


def _proc_kwargs():
    """Run yt-dlp without a console window on Windows, in its own process group, with UTF-8 output."""
    kw = {"encoding": "utf-8", "errors": "replace", "stdin": subprocess.DEVNULL}
    if WINDOWS:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        kw["env"] = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    else:
        kw["start_new_session"] = True
    return kw


def _encoding_args():
    return ["--encoding", "utf-8"] if WINDOWS else []


def ytdlp_version():
    cmd = ytdlp_command()
    if not cmd:
        return None
    try:
        return subprocess.run(cmd + ["--version"], capture_output=True, timeout=30, **_proc_kwargs()).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def install_ytdlp(proxy=None):
    """Download the latest yt-dlp release into our data folder. Returns the new version."""
    target = private_ytdlp()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".new"
    req = urllib.request.Request(YTDLP_URL, headers={"User-Agent": "Tondar"})
    opener = urllib.request.build_opener(*proxy_handlers(proxy))
    with opener.open(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return ytdlp_version()


def _header_args(item, proxy=None):
    args = ["--proxy", proxy or ""]  # "" = direct, also ignores proxy env vars
    if item.referer:
        args += ["--add-header", f"Referer:{item.referer}"]
    return args


# YouTube rejects logged-in browser cookies used outside the browser
# ("The page needs to be reloaded"), and public videos don't need them.
NO_COOKIE_SITES = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$")


def cookies_allowed(item):
    return bool(item.cookies) and not NO_COOKIE_SITES.search(urllib.parse.urlparse(item.url).hostname or "")


def write_cookie_file(item):
    if not cookies_allowed(item):
        return None
    folder = os.path.join(data_dir(), "cookies")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, f"{item.id}.txt")
    lines = ["# Netscape HTTP Cookie File"]
    for c in item.cookies:
        domain = c.get("domain", "")
        host_only = c.get("hostOnly", not domain.startswith("."))
        if not host_only and not domain.startswith("."):
            domain = "." + domain
        lines.append("\t".join([
            domain,
            "FALSE" if host_only else "TRUE",
            c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(int(c.get("expirationDate") or 0)),
            c.get("name", ""),
            c.get("value", ""),
        ]))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def probe_media(item, playlist=False, proxy=None):
    """Run `yt-dlp -J` and return the info dict.

    With playlist=True a playlist comes back as {"_type": "playlist", "entries": [...]}
    listing the videos without resolving each one (fast). Links that are only a
    playlist (no single video in them) always come back that way.
    """
    cmd = ytdlp_command()
    if not cmd:
        raise RuntimeError("yt-dlp is not installed. Open the menu → Install / update yt-dlp.")
    attempts = [True, False] if cookies_allowed(item) else [False]
    for with_cookies in attempts:
        cookie_file = write_cookie_file(item) if with_cookies else None
        args = cmd + ["-J", "--flat-playlist", "--yes-playlist" if playlist else "--no-playlist", "--no-warnings"]
        args += _header_args(item, proxy) + _encoding_args()
        if cookie_file:
            args += ["--cookies", cookie_file]
        try:
            proc = subprocess.run(args + ["--", item.url], capture_output=True, timeout=120, **_proc_kwargs())
        finally:
            if cookie_file:
                os.unlink(cookie_file)
        if proc.returncode == 0:
            break
    if proc.returncode != 0:
        err = [line for line in proc.stderr.splitlines() if line.startswith("ERROR")]
        raise RuntimeError((err[-1] if err else proc.stderr.strip()[-300:]) or "yt-dlp failed")
    return json.loads(proc.stdout)


PLAYLIST_HINT = re.compile(r"[?&]list=|/playlist\b|/sets/|/album/", re.I)


def is_playlist(info):
    return info.get("_type") in ("playlist", "multi_video") and info.get("entries") is not None


def playlist_entries(info):
    """[(url, title, duration)] for each playable video of a flat playlist."""
    out = []
    for e in info.get("entries") or []:
        if not e or e.get("_type") == "playlist":
            continue
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            if (e.get("ie_key") or "").lower() == "youtube" and e.get("id"):
                url = f"https://www.youtube.com/watch?v={e['id']}"
            else:
                continue
        out.append((url, e.get("title") or e.get("id") or url, e.get("duration") or 0))
    return out


def playlist_choices():
    choices = [("Best quality", "bv*+ba/b", 0)]
    for h in (2160, 1440, 1080, 720, 480, 360):
        choices.append((f"Up to {h}p", f"bv*[height<={h}]+ba/b[height<={h}]/b", 0))
    choices.append(("Audio only", "ba[ext=m4a]/ba/b", 0))
    return choices


def _fsize(f, duration=0):
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 125 * duration  # kbit/s -> bytes
    return int(size or 0)


def quality_choices(info):
    """Return [(label, format_selector, estimated_size)] best first."""
    duration = info.get("duration") or 0
    formats = info.get("formats") or []
    audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max((_fsize(f, duration) for f in audio), default=0)
    videos = [f for f in formats if f.get("height") and f.get("vcodec") != "none"]
    choices = []
    for h in sorted({f["height"] for f in videos}, reverse=True):
        best = max((f for f in videos if f["height"] == h), key=lambda f: f.get("tbr") or 0)
        size = _fsize(best, duration)
        if size and best.get("acodec") in (None, "none"):
            size += best_audio
        choices.append((f"{h}p", f"bv*[height<={h}]+ba/b[height<={h}]/b", size))
    best_label = f"Best quality ({choices[0][0]})" if choices else "Best quality"
    choices.insert(0, (best_label, "bv*+ba/b", choices[0][2] if choices else _fsize(info, duration)))
    if audio:
        choices.append(("Audio only", "ba[ext=m4a]/ba/b", best_audio))
    return choices


class MediaTask:
    def __init__(self, item, limiter, on_done, proxy=None):
        self.item = item
        self.proxy = proxy
        self.limiter = limiter
        self.on_done = on_done
        self.stopped = threading.Event()
        self.proc = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stopped.set()
        proc = self.proc
        if not proc or proc.poll() is not None:
            return
        try:
            if WINDOWS:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(proc.pid, signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass
        # yt-dlp may take a moment to clean up; don't let it hang around forever.
        threading.Timer(10, lambda: proc.poll() is None and proc.kill()).start()

    def _run(self):
        error = None
        try:
            self._main()
        except Exception as e:  # noqa: BLE001
            error = str(e)
        self.on_done(self, error)

    def _main(self):
        it = self.item
        cmd = ytdlp_command()
        if not cmd:
            raise RuntimeError("yt-dlp is not installed. Open the menu → Install / update yt-dlp.")
        os.makedirs(it.folder, exist_ok=True)
        name = sanitize_filename(clean_page_title(it.title), "") or "%(title).150B"
        if name.lower().endswith((".mp4", ".mkv", ".webm", ".m4a", ".mp3")):
            name = name.rsplit(".", 1)[0]
        attempts = [True, False] if cookies_allowed(it) else [False]
        for with_cookies in attempts:
            rc, tail = self._run_ytdlp(cmd, name, with_cookies)
            if rc == 0 or self.stopped.is_set():
                break
        if self.stopped.is_set():
            return
        if rc != 0:
            errors = [line for line in tail if line.startswith("ERROR")]
            raise RuntimeError((errors[-1] if errors else (tail[-1] if tail else f"yt-dlp exited with {rc}")))

    def _run_ytdlp(self, cmd, name, with_cookies):
        it = self.item
        cookie_file = write_cookie_file(it) if with_cookies else None
        args = cmd + [
            "--newline", "--progress", "--no-color", "--no-playlist", "--no-mtime",
            "-f", it.media_format or "bv*+ba/b",
            "--merge-output-format", "mp4/mkv",
            "-N", str(max(1, min(it.max_segments, 16))),
            "-P", it.folder, "-o", name + ".%(ext)s",
            "--progress-template", PROGRESS,
            "--print", "after_move:TONDARFILE|%(filepath)s",
        ] + _header_args(it, self.proxy) + _ffmpeg_args() + _encoding_args()
        if cookie_file:
            args += ["--cookies", cookie_file]
        if self.limiter.rate > 0:
            args += ["-r", str(int(self.limiter.rate))]
        args += ["--", it.url]

        tail = []
        base, last_done, last_total = 0, 0, 0
        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **_proc_kwargs())
            for line in self.proc.stdout:
                line = line.rstrip()
                if line.startswith("TONDAR|"):
                    done, total, estimate = (_num(v) for v in line.split("|")[1:4])
                    total = total or estimate or 0
                    if done < last_done * 0.5:  # yt-dlp moved on to the next stream (e.g. audio)
                        base += last_total or last_done
                    last_done, last_total = done, total
                    it.done = base + done
                    it.size = base + total if total else -1
                elif line.startswith("TONDARFILE|"):
                    path = line.split("|", 1)[1]
                    it.folder, it.filename = os.path.split(path)
                    if os.path.exists(path):
                        it.size = it.done = os.path.getsize(path)
                elif line:
                    tail = (tail + [line])[-30:]
            rc = self.proc.wait()
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.unlink(cookie_file)
        return rc, tail


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0

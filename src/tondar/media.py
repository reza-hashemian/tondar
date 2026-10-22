"""Video/stream downloads (YouTube, HLS .m3u8, DASH, ...) through yt-dlp."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import html
import threading
import urllib.parse
import urllib.request

from .net import proxy_handlers
from .util import FROZEN_TOOLS, MACOS, WINDOWS, app_dir, clean_page_title, data_dir, sanitize_filename

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/" + (
    "yt-dlp.exe" if WINDOWS else "yt-dlp_macos" if MACOS else "yt-dlp")
PROGRESS = "download:TONDAR|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s"


def private_ytdlp():
    return os.path.join(data_dir(), "bin", "yt-dlp.exe" if WINDOWS else "yt-dlp")


def ytdlp_command():
    """Prefer our own always-up-to-date copy, then the one bundled with the app, then the system one."""
    own = private_ytdlp()
    if os.path.exists(own):
        return [own] if FROZEN_TOOLS else [sys.executable, own]  # Linux: a Python zipapp
    bundled = os.path.join(app_dir(), "tools", "yt-dlp.exe" if WINDOWS else "yt-dlp")
    if FROZEN_TOOLS and os.path.exists(bundled):
        return [bundled]
    system = shutil.which("yt-dlp")
    return [system] if system else None


def _search_path():
    """PATH for yt-dlp, with our own folder first so helpers the user drops there are found."""
    return os.pathsep.join([os.path.join(data_dir(), "bin"), os.environ.get("PATH", "")])


# YouTube asks some networks (VPNs, data centers, shared IPs) to sign in before it plays anything.
BOT_CHECK = re.compile(r"confirm you.?re not a bot|sign in to confirm|Use --cookies-from-browser", re.I)
YOUTUBE = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$")
BROWSERS = ["firefox", "chrome", "edge", "brave", "chromium", "opera", "vivaldi", "safari"]
_settings = {"cookies_browser": "", "gentle": True}


def configure(settings):
    """Options from Preferences that change how yt-dlp is run."""
    browser = (settings.get("cookies_browser") or "").lower()
    _settings["cookies_browser"] = browser if browser in BROWSERS else ""
    _settings["gentle"] = bool(settings.get("youtube_gentle", True))


def is_youtube(url):
    return bool(YOUTUBE.search(urllib.parse.urlparse(url or "").hostname or ""))


TOO_MANY = re.compile(r"HTTP Error 429|Too Many Requests|rate.?limited", re.I)


def is_bot_check(error):
    return bool(error) and bool(BOT_CHECK.search(error))


def _bot_help():
    if _settings["cookies_browser"]:
        name = _settings["cookies_browser"].capitalize()
        return (f"YouTube wants you to sign in to confirm you're not a bot, and the sign-in from {name} "
                f"didn't help.\n"
                f"• Open youtube.com in {name}, make sure you're signed in, play any video, then press Try Again.\n"
                f"• Close {name} completely (Chrome and Edge lock their cookies while open) and try again.\n"
                f"• Turn off your VPN/proxy or try another network.")
    return ("YouTube wants you to sign in to confirm you're not a bot. This happens on some networks "
            "(VPN, proxy, shared or data-center connections), not because of the link.\n"
            "• Sign in to youtube.com in your browser and send the video with Download with Tondar.\n"
            "• Or open Preferences → Video downloads → \"Sign-in from browser\" and pick the browser you use "
            "YouTube in, then press Try Again.\n"
            "• Or turn off your VPN/proxy, or try another network.")


def _friendly(error):
    """Turn yt-dlp errors ordinary users can fix themselves into instructions."""
    if is_bot_check(error):
        return _bot_help()
    if "PhantomJS not found" in error:
        folder = os.path.join(data_dir(), "bin")
        os.makedirs(folder, exist_ok=True)
        exe = "phantomjs.exe" if WINDOWS else "phantomjs"
        return (f"This site needs PhantomJS. Download it from phantomjs.org/download.html, unzip it, "
                f"copy {exe} from its bin folder into {folder} and press Retry.")
    return error


# A captured stream link (.m3u8/.mpd) carries a token that expires; the page itself still works.
EXPIRED_LINK = re.compile(r"HTTP Error (403|404|410)")


def _page_fallback(item, error):
    if item.page_url and item.page_url != item.url and EXPIRED_LINK.search(error or ""):
        return item.page_url
    return None


# Errors of sites that want a logged-in user (or that yt-dlp has no extractor for). The page
# itself often still has the video for visitors (og:video, <video src>, a player config), and
# yt-dlp's generic extractor finds it there without an account.
LOGIN_NEEDED = re.compile(
    r"log ?in|sign ?in|cookies|authenticat|account|registered|premium|subscri|members?[ -]only|private|"
    r"rate.?limit|unable to extract|no video formats|unsupported url|empty media response|"
    r"HTTP Error 40[13]", re.I)


def needs_guest_mode(error):
    return bool(error) and bool(LOGIN_NEEDED.search(error))


def _attempts(item):
    """(cookies, generic) tries for yt-dlp, in order. cookies: None, "page" (the ones the browser
    sent with the link) or "browser" (yt-dlp reads the sign-in from the browser chosen in Preferences)."""
    normal = [("page", False), (None, False)] if cookies_allowed(item) else [(None, False)]
    return [(None, True)] + normal if item.guest else normal


def _more_attempts(item, error, tried):
    """What to try next after every planned attempt failed with `error`."""
    extra = []
    if is_bot_check(error):
        # YouTube's bot check: only a signed-in session gets past it.
        if item.cookies and ("page", False) not in tried:
            extra.append(("page", False))
        if _settings["cookies_browser"] and ("browser", False) not in tried:
            extra.append(("browser", False))
    elif needs_guest_mode(error) and (None, True) not in tried:
        extra.append((None, True))  # no account: read the page like a visitor
    return extra


def _cookie_args(item, mode):
    """yt-dlp arguments for a cookie mode, and a temporary file to delete afterwards."""
    if mode == "page":
        path = write_cookie_file(item, force=True)
        return (["--cookies", path], path) if path else ([], None)
    if mode == "browser" and _settings["cookies_browser"]:
        return ["--cookies-from-browser", _settings["cookies_browser"]], None
    return [], None


def _bundled_ffmpeg():
    bundled = os.path.join(app_dir(), "tools", "ffmpeg")
    return bundled if FROZEN_TOOLS and os.path.isdir(bundled) else None


def ffmpeg_available():
    return bool(_bundled_ffmpeg() or shutil.which("ffmpeg"))


def _ffmpeg_args():
    bundled = _bundled_ffmpeg()
    return ["--ffmpeg-location", bundled] if bundled else []


def _proc_kwargs():
    """Run yt-dlp without a console window on Windows, in its own process group, with UTF-8 output."""
    kw = {"encoding": "utf-8", "errors": "replace", "stdin": subprocess.DEVNULL}
    if WINDOWS:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        kw["env"] = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PATH=_search_path())
    else:
        kw["start_new_session"] = True
        kw["env"] = dict(os.environ, PATH=_search_path())
    return kw


def _encoding_args():
    return ["--encoding", "utf-8"] if WINDOWS else []


_version_cache = {}  # yt-dlp command -> (file time, version)


def _ytdlp_stamp(cmd):
    try:
        return os.path.getmtime(cmd[-1])
    except OSError:
        return None


def cached_ytdlp_version():
    """The version found earlier for the current yt-dlp, if it hasn't changed since; else None."""
    cmd = ytdlp_command()
    if not cmd:
        return ""
    hit = _version_cache.get(tuple(cmd))
    return hit[1] if hit and hit[0] == _ytdlp_stamp(cmd) else None


def ytdlp_version():
    cmd = ytdlp_command()
    if not cmd:
        return None
    try:
        version = subprocess.run(cmd + ["--version"], capture_output=True, timeout=30, **_proc_kwargs()).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    if version:
        _version_cache[tuple(cmd)] = (_ytdlp_stamp(cmd), version)
    return version


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


# YouTube rejects logged-in browser cookies used outside the browser ("The page needs to be
# reloaded"), and public videos don't need them: they're only tried after a bot check.
def cookies_allowed(item):
    return bool(item.cookies) and not is_youtube(item.url)


def write_cookie_file(item, force=False):
    """The cookies the browser sent with this link, as a temporary file for yt-dlp (deleted after use)."""
    if not item.cookies or not (force or cookies_allowed(item)):
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
    try:
        return _probe(cmd, item, item.url, playlist, proxy)
    except RuntimeError as e:
        fallback = _page_fallback(item, str(e))
        if not fallback:
            raise
    return _probe(cmd, item, fallback, playlist, proxy)


def _probe(cmd, item, url, playlist, proxy):
    first_error = None
    attempts = _attempts(item)
    i = 0
    while i < len(attempts):
        mode, generic = attempts[i]
        i += 1
        cookie_args, cookie_file = _cookie_args(item, mode)
        args = cmd + ["-J", "--flat-playlist", "--yes-playlist" if playlist else "--no-playlist", "--no-warnings"]
        args += _header_args(item, proxy) + _encoding_args() + cookie_args
        if generic:
            args.append("--force-generic-extractor")
        try:
            proc = subprocess.run(args + ["--", url], capture_output=True, timeout=120, **_proc_kwargs())
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.unlink(cookie_file)
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            if generic:
                info["_tondar_guest"] = True  # download it the same way
            if mode:
                info["_tondar_cookies"] = mode
            return info
        err = [line for line in proc.stderr.splitlines() if line.startswith("ERROR")]
        error = (err[-1] if err else proc.stderr.strip()[-300:]) or "yt-dlp failed"
        if is_bot_check(error):
            first_error = error  # the one thing the user can fix; the other errors only follow from it
        first_error = first_error or error
        if i == len(attempts):
            attempts += _more_attempts(item, error, attempts)
    raise RuntimeError(_friendly(first_error))


# Links to video/audio files and streams in a page's HTML or scripts (also JSON-escaped: https:\/\/…).
MEDIA_LINK = re.compile(
    r"""https?:(?:\\?/){2}[^\s"'<>()]+?\.(?:mp4|m4v|mkv|webm|mov|avi|flv|wmv|3gp|m3u8|mpd|mp3|m4a|aac|ogg|opus|flac|wav)"""
    r"""(?:[?#][^\s"'<>()]*)?(?=$|[\s"'<>()\\])""", re.I)
META_MEDIA = re.compile(
    r"""<meta[^>]+(?:property|name|itemprop)\s*=\s*["'](?:og:video(?::secure_url|:url)?|og:audio(?::secure_url)?|"""
    r"""twitter:player:stream|contentUrl)["'][^>]*>""", re.I)
TAG_SRC = re.compile(r"""<(?:video|audio|source)\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I)
ATTR_CONTENT = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)
STREAM_EXT = {"m3u8": "HLS stream", "mpd": "DASH stream"}
AUDIO_EXT = {"mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"}
SKIP_HOSTS = re.compile(r"(^|\.)googlevideo\.com$")  # YouTube chunks; yt-dlp handles YouTube


def _clean_link(raw, base):
    raw = html.unescape(raw).replace("\\/", "/").replace("\\u0026", "&").replace("\\u002F", "/").rstrip("\\")
    try:
        u = urllib.parse.urlsplit(urllib.parse.urljoin(base, raw))
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname or SKIP_HOSTS.search(u.hostname):
        return None
    # Facebook / Instagram CDNs: without the byte range the link is the whole file.
    query = "&".join(p for p in u.query.split("&") if p and not p.startswith(("bytestart=", "byteend=")))
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, query, ""))


def media_link_info(url):
    """(kind, label) for a found link: kind "media" (stream, yt-dlp) or "http" (a plain file)."""
    path = urllib.parse.urlsplit(url).path.lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in STREAM_EXT:
        return "media", STREAM_EXT[ext]
    return "http", f"{'Audio' if ext in AUDIO_EXT else 'Video'} file ({ext or 'file'})"


def find_page_media(item, url=None, proxy=None, limit=30):
    """Video links a visitor can see in the page at `url`, without logging in.

    Returns [{"url", "kind", "label"}]. Used when yt-dlp can't get the video (login wall,
    unknown site)."""
    url = url or item.page_url or item.url
    headers = {
        "User-Agent": item.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    if item.referer:
        headers["Referer"] = item.referer
    opener = urllib.request.build_opener(*proxy_handlers(proxy))
    with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
        base = r.geturl()
        ctype = r.headers.get_content_type()
        if not ctype.startswith(("text/", "application/xhtml", "application/json", "application/javascript")):
            return []
        raw = r.read(6 * 1024 * 1024)
        charset = r.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")

    found = []
    for m in META_MEDIA.finditer(text):
        c = ATTR_CONTENT.search(m.group(0))
        if c:
            found.append(c.group(1))
    found += TAG_SRC.findall(text)
    found += [m.group(0) for m in MEDIA_LINK.finditer(text)]

    out, seen = [], set()
    for raw_link in found:
        link = _clean_link(raw_link, base)
        if not link or link in seen:
            continue
        seen.add(link)
        kind, label = media_link_info(link)
        if kind == "http" and not re.search(r"\.[a-z0-9]{2,5}$", urllib.parse.urlsplit(link).path, re.I):
            kind = "media"  # og:video pointing at a player page: let yt-dlp have a go at it
        out.append({"url": link, "kind": kind, "label": label})
        if len(out) >= limit:
            break
    return out  # in page order: og:video / <video> first, then links found in scripts


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


# File types a video can be saved as. "Repackaged" ones need only ffmpeg's copy mode: same
# quality, no re-encoding (the bundled ffmpeg can't encode).
MERGEABLE = ("mp4", "mkv", "webm", "mov")
AUDIO_EXTS = ("m4a", "webm", "mp3", "opus", "ogg", "aac", "flac", "wav")
EXT_NAMES = {"webm": "WebM", "opus": "Opus"}


def ext_name(ext):
    return EXT_NAMES.get(ext, ext.upper())


def format_summary(info):
    """What the site offers: ({video_ext: (lowest, highest height)}, [audio exts]), most common first."""
    video, audio = {}, []
    for f in info.get("formats") or []:
        ext = (f.get("ext") or "").lower()
        if not ext or ext in ("mhtml", "none"):
            continue
        if f.get("vcodec") not in (None, "none") and f.get("height"):
            lo, hi = video.get(ext, (f["height"], f["height"]))
            video[ext] = (min(lo, f["height"]), max(hi, f["height"]))
        elif f.get("vcodec") == "none" and f.get("acodec") not in (None, "none"):
            if ext not in audio:
                audio.append(ext)
    order = {e: i for i, e in enumerate(("mp4", "webm", "mkv", "mov", "flv", "3gp"))}
    video = dict(sorted(video.items(), key=lambda kv: (order.get(kv[0], 99), kv[0])))
    return video, audio


def describe_formats(info):
    """One line for the New Download window: the file types this site has for the video."""
    video, audio = format_summary(info)
    parts = []
    if video:
        parts.append("Video: " + ", ".join(
            f"{ext_name(e)} ({lo}p)" if lo == hi else f"{ext_name(e)} ({lo}p–{hi}p)" for e, (lo, hi) in video.items()))
    if audio:
        parts.append("Audio: " + ", ".join(ext_name(e) for e in audio))
    return "  ·  ".join(parts)


def container_choices(info, audio_only=False):
    """[(label, container)] for the Format list; "" = whatever the site's best format is."""
    video, audio = format_summary(info) if info else ({}, [])
    if audio_only:
        choices = [("Automatic (best audio)", "")]
        choices += [(f"{ext_name(e)}  ·  offered by the site", e) for e in audio]
        return choices
    choices = [("Automatic (best quality)", "")]
    for e, (_lo, hi) in video.items():
        choices.append((f"{ext_name(e)}  ·  offered by the site  ·  up to {hi}p", e))
    for e in ("mp4", "mkv"):
        if e not in video:
            choices.append((f"{ext_name(e)}  ·  repackaged, same quality", e))
    return choices


def container_args(container, audio_only=False):
    """yt-dlp options that make the download come out as `container`."""
    c = (container or "").lower()
    if not c or audio_only:
        return ["--merge-output-format", "mp4/mkv"]
    # The site's own files of that type first (no repackaging needed), then the best resolution.
    args = ["-S", f"ext:{c}:m4a" if c == "mp4" else f"ext:{c}:{c}" if c == "webm" else f"ext:{c}"]
    if c in MERGEABLE:
        args += ["--merge-output-format", c, "--remux-video", c]
    else:
        args += ["--merge-output-format", "mp4/mkv"]
    return args


def audio_selector(container):
    """Format selector for "Audio only" in a chosen file type."""
    return f"ba[ext={container}]/ba/b" if container else "ba[ext=m4a]/ba/b"


def parse_time(text):
    """Seconds from "1:02:03", "2:05", "75" or "1:20.5"; None when it isn't a time."""
    text = (text or "").strip().replace("٫", ".").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if any(v < 0 for v in values) or any(v >= 60 for v in values[1:]):
        return None
    total = 0.0
    for v in values:
        total = total * 60 + v
    return total


def format_time(seconds):
    seconds = max(0, int(round(seconds)))
    h, m, s = seconds // 3600, seconds % 3600 // 60, seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def clip_args(item):
    if not item.is_clip:
        return []
    start = max(0.0, item.clip_start)
    end = "inf" if item.clip_end < 0 else f"{item.clip_end:g}"
    return ["--download-sections", f"*{start:g}-{end}"]


def clip_suffix(item):
    """" (clip 1m20s-2m05s)": a clip doesn't take the full video's name."""
    def stamp(t):
        t = int(t)
        h, m, s = t // 3600, t % 3600 // 60, t % 60
        return f"{h}h{m:02}m{s:02}s" if h else f"{m}m{s:02}s"
    end = "end" if item.clip_end < 0 else stamp(item.clip_end)
    return f" (clip {stamp(max(0, item.clip_start))}-{end})"


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
        self.throttled = False  # YouTube said "too many requests"
        self.bot_check = False

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
        if it.is_clip and "(clip " not in name:
            name += clip_suffix(it)
        error = self._try(cmd, name, it.url)
        fallback = _page_fallback(it, error)
        if fallback:
            error = self._try(cmd, name, fallback)
            if not error:
                it.url = fallback  # a restart shouldn't hit the dead stream link again
        if error:
            self.throttled = bool(TOO_MANY.search(error))
            self.bot_check = is_bot_check(error)
            raise RuntimeError(_friendly(error))

    def _try(self, cmd, name, url):
        """Download `url`; returns yt-dlp's error, or None when done or stopped."""
        attempts = _attempts(self.item)
        mode = getattr(self.item, "cookie_mode", "")
        if mode and (mode, False) in _more_attempts(self.item, "confirm you're not a bot", []):
            attempts.insert(0, (mode, False))  # what worked when the link was checked
        first_error = None
        i = 0
        while i < len(attempts):
            mode, generic = attempts[i]
            i += 1
            rc, tail = self._run_ytdlp(cmd, name, url, mode, generic)
            if rc == 0 or self.stopped.is_set():
                if generic:
                    self.item.guest = True
                return None
            errors = [line for line in tail if line.startswith("ERROR")]
            error = errors[-1] if errors else (tail[-1] if tail else f"yt-dlp exited with {rc}")
            if is_bot_check(error):
                first_error = error
            first_error = first_error or error
            if i == len(attempts):
                attempts += _more_attempts(self.item, error, attempts)
        return first_error

    def _run_ytdlp(self, cmd, name, url, mode, generic=False):
        it = self.item
        cookie_args, cookie_file = _cookie_args(it, mode)
        args = cmd + [
            "--newline", "--progress", "--no-color", "--no-playlist", "--no-mtime",
            "-f", it.media_format or "bv*+ba/b",
        ] + container_args(it.container, (it.media_format or "").startswith("ba")) + clip_args(it) + [
            "-N", str(max(1, min(it.max_segments, 16))),
            "-P", it.folder, "-o", name + ".%(ext)s",
            "--progress-template", PROGRESS,
            "--print", "after_move:TONDARFILE|%(filepath)s",
        ] + _header_args(it, self.proxy) + _ffmpeg_args() + _encoding_args()
        if generic:
            args.append("--force-generic-extractor")
        if is_youtube(url) and _settings["gentle"]:
            # A short pause between the page requests yt-dlp makes, like a person clicking around.
            args += ["--sleep-requests", "1", "--extractor-retries", "3"]
        args += cookie_args
        if self.limiter.rate > 0:
            args += ["-r", str(int(self.limiter.rate))]
        args += ["--", url]

        tail = []
        state = {"base": 0, "done": 0, "total": 0}

        def read(stream):
            for line in stream:
                line = line.rstrip()
                if line.startswith("TONDAR|"):
                    done, total, estimate = (_num(v) for v in line.split("|")[1:4])
                    total = total or estimate or 0
                    if done < state["done"] * 0.5:  # yt-dlp moved on to the next stream (e.g. audio)
                        state["base"] += state["total"] or state["done"]
                    state["done"], state["total"] = done, total
                    it.done = state["base"] + done
                    it.size = state["base"] + total if total else -1
                elif line.startswith("TONDARFILE|"):
                    path = line.split("|", 1)[1]
                    it.folder, it.filename = os.path.split(path)
                    if os.path.exists(path):
                        it.size = it.done = os.path.getsize(path)
                elif line:
                    tail.append(line)
                    del tail[:-30]

        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **_proc_kwargs())
            reader = threading.Thread(target=read, args=(self.proc.stdout,), daemon=True)
            reader.start()
            rc = self.proc.wait()
            # ffmpeg (started by yt-dlp for merging) can keep the output pipe open after yt-dlp has
            # exited. Reading until the pipe closes then hung the download: it never finished and
            # the downloads behind it stayed "Waiting in queue". Wait for yt-dlp itself instead.
            reader.join(3)
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.unlink(cookie_file)
        return rc, list(tail)


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0

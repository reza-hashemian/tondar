import os
import re
import sys
import urllib.parse

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
# No D-Bus: a single instance is kept by ipc.py and the app ships its own yt-dlp and ffmpeg.
FROZEN_TOOLS = WINDOWS or MACOS
# Characters and names Windows doesn't allow in file names
WIN_BAD_CHARS = re.compile(r'[<>:"\\|?*]')
WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.I)

CATEGORIES = {
    "Video": {"mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "3gp", "ts", "m3u8"},
    "Music": {"mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "wma"},
    "Compressed": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "zst", "tgz", "iso"},
    "Documents": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "txt", "epub", "djvu"},
    "Programs": {"deb", "rpm", "appimage", "exe", "msi", "apk", "run", "sh", "flatpakref", "dmg"},
}

CATEGORY_ICONS = {
    "Video": "video-x-generic",
    "Music": "audio-x-generic",
    "Compressed": "package-x-generic",
    "Documents": "x-office-document",
    "Programs": "application-x-executable",
    "Other": "text-x-generic",
}


def category_for(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Other"


def sanitize_filename(name, fallback="download"):
    name = name.replace("/", "_").replace("\0", "")
    name = re.sub(r"[\x00-\x1f]", "", name).strip().strip(".")
    if WINDOWS:
        name = WIN_BAD_CHARS.sub("_", name).rstrip(" .")
        if WIN_RESERVED.match(name):
            name = "_" + name
    # Linux limits names to 255 bytes; Windows paths get into trouble past ~260 characters.
    limit, measure = (150, len) if WINDOWS else (240, lambda s: len(s.encode()))
    if measure(name) > limit:
        base, dot, ext = name.rpartition(".")
        if not dot or len(ext) > 10:
            base, ext = name, ""
        while measure(base + "." + ext) > limit:
            base = base[:-1]
        name = base + ("." + ext if ext else "")
    return name or fallback


def filename_from_url(url):
    path = urllib.parse.urlparse(url).path
    return sanitize_filename(urllib.parse.unquote(os.path.basename(path)))


def filename_from_disposition(value):
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", value, re.I)
    if m:
        charset = m.group(1) or "utf-8"
        try:
            return sanitize_filename(urllib.parse.unquote(m.group(2).strip().strip('"'), encoding=charset))
        except LookupError:
            pass
    m = re.search(r'filename\s*=\s*"([^"]*)"', value, re.I) or re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    if m:
        raw = m.group(1).strip()
        # Many servers send raw UTF-8 bytes that http.client decoded as latin-1.
        try:
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return sanitize_filename(urllib.parse.unquote(raw))
    return None


def unique_path(folder, name, taken=()):
    base, dot, ext = name.rpartition(".")
    if not dot:
        base, ext = name, ""
    candidate = name
    n = 1
    while (
        os.path.exists(os.path.join(folder, candidate))
        or os.path.exists(os.path.join(folder, candidate + ".part"))
        or os.path.join(folder, candidate) in taken
    ):
        candidate = f"{base} ({n})" + (f".{ext}" if ext else "")
        n += 1
    return candidate


def human_size(n):
    if n is None or n < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_time(sec):
    if sec is None or sec < 0:
        return "?"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def data_dir():
    if WINDOWS and not os.environ.get("XDG_DATA_HOME"):
        path = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Tondar")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = os.path.join(base, "tondar")
    os.makedirs(path, exist_ok=True)
    return path


def config_dir():
    if WINDOWS and not os.environ.get("XDG_CONFIG_HOME"):
        path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Tondar")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, "tondar")
    os.makedirs(path, exist_ok=True)
    return path


def app_dir():
    """Folder with the bundled tools (yt-dlp, ffmpeg) in the Windows and macOS builds."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def downloads_dir():
    if WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
                return os.path.expandvars(value)
        except OSError:
            return os.path.join(os.path.expanduser("~"), "Downloads")
    try:
        with open(os.path.expanduser("~/.config/user-dirs.dirs")) as f:
            for line in f:
                if line.startswith("XDG_DOWNLOAD_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    return value.replace("$HOME", os.path.expanduser("~"))
    except OSError:
        pass
    return os.path.expanduser("~/Downloads")


MEDIA_SITES = re.compile(
    r"(^|\.)(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|aparat\.com|twitter\.com|x\.com|"
    r"instagram\.com|facebook\.com|tiktok\.com|twitch\.tv|soundcloud\.com|reddit\.com|namava\.ir|filimo\.com)$"
)


def looks_like_media_page(url):
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    path = p.path.lower()
    if path.endswith((".m3u8", ".mpd")):
        return True
    return bool(MEDIA_SITES.search(p.hostname or ""))


def clean_page_title(title):
    """'(497) Song name - YouTube' -> 'Song name'."""
    title = re.sub(r"^\(\d+\+?\)\s*", "", title or "").strip()
    return re.sub(r"\s+[-|–·]\s+(YouTube|Aparat|آپارات|Vimeo|Dailymotion|Instagram|Facebook|X|Twitter|TikTok)$", "", title, flags=re.I)

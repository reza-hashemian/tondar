"""Download list, settings, persistence and the download queue."""

import collections
import datetime
import json
import locale
import os
import random
import shutil
import threading
import time
import traceback
import uuid

from .clone import SiteTask
from .http_task import HttpTask, RateLimiter
from .media import MediaTask, is_youtube
from .net import proxy_url
from .util import category_for, config_dir, data_dir, downloads_dir, unique_path

QUEUED, DOWNLOADING, PAUSING, PAUSED, COMPLETED, ERROR = (
    "queued", "downloading", "pausing", "paused", "completed", "error",
)

DEFAULT_SETTINGS = {
    "folder": downloads_dir(),
    "categorize": True,
    "max_active": 3,
    "segments": 8,
    "speed_limit_kb": 0,
    "background": True,
    "autostart": False,
    "confirm_browser": True,
    "notify": True,
    # A window that follows a download started by hand, and one that says it's finished.
    "progress_window": True,
    "complete_window": True,
    # New downloads go to the folder that was last picked by hand in the New Download window.
    "remember_folder": True,
    "last_folder": "",
    # Proxy: "system" (GNOME / environment), "none", or "manual"
    "proxy_mode": "system",
    "proxy_type": "http",  # "http" or "socks5"
    "proxy_host": "",
    "proxy_port": 8080,
    "proxy_user": "",
    "proxy_pass": "",
    # Scheduler
    "schedule_enabled": False,
    "schedule_start": "02:00",
    "schedule_stop": "",  # "" = run until done
    "schedule_days": [0, 1, 2, 3, 4, 5, 6],  # Python weekdays, Monday = 0
    "schedule_all": False,  # also start every unfinished download, not only scheduled ones
    "schedule_done_action": "nothing",  # "nothing", "quit", "shutdown"
    "schedule_last": "",  # date of the last session that was started
    # yt-dlp may read the YouTube sign-in from this browser when YouTube asks to prove you're not a bot
    # ("" = never).
    "cookies_browser": "",
    # When the "follow the Telegram channel" reminder was last shown (0 = not yet).
    "support_last": 0,
    # Big YouTube playlists: few videos at once with a pause between them, and a long break when
    # YouTube says "too many requests", so it doesn't block the connection.
    "youtube_gentle": True,
}

YT_PARALLEL = 2  # YouTube videos at the same time (gentle mode)
YT_GAP = (4, 10)  # seconds between starting two YouTube videos
YT_COOLDOWN = 10 * 60  # break after "too many requests"; longer each time it happens again
YT_RETRIES = 3  # times a video goes back in the queue after "too many requests"



class Item:
    FIELDS = (
        "id", "url", "kind", "filename", "folder", "size", "done", "status", "error", "created",
        "finished", "segments", "resumable", "referer", "user_agent", "cookies", "max_segments",
        "media_format", "title", "page_url", "scheduled", "auto_folder", "guest",
        "container", "clip_start", "clip_end", "popup", "cookie_mode",
        "clone_depth", "clone_max_pages", "clone_external", "clone_files", "clone_max_mb", "clone_robots",
        "clone_scope", "clone_update",
        "site_entry", "files_done", "files_total", "files_failed",
    )

    def __init__(self, **kw):
        self.id = uuid.uuid4().hex
        self.url = ""
        self.kind = "http"  # "http", "media" (yt-dlp) or "site" (a whole website, clone.py)
        self.filename = ""
        self.folder = ""
        self.size = -1
        self.done = 0
        self.status = PAUSED
        self.error = ""
        self.created = time.time()
        self.finished = 0
        self.segments = []
        self.resumable = False
        self.referer = ""
        self.user_agent = ""
        self.cookies = []
        self.max_segments = 8
        self.media_format = ""
        self.title = ""
        self.page_url = ""
        self.scheduled = False
        # The folder came from "Sort into sub-folders" (not picked by hand): it may be corrected
        # once the real file name is known.
        self.auto_folder = False
        # Look the video up like a visitor who isn't logged in (yt-dlp's generic extractor).
        self.guest = False
        # Videos: the file type to save ("" = whatever the site has, "mp4", "mkv", "webm", "m4a"…)
        # and, for a clip, the part to download in seconds (-1 = from the start / to the end).
        self.container = ""
        self.clip_start = -1.0
        self.clip_end = -1.0
        # Show the progress window and the "Download complete" window for this download.
        self.popup = False
        # Which sign-in got past a bot check when the link was checked ("", "page" or "browser").
        self.cookie_mode = ""
        # Website clones: how far to follow links (-1 = the whole site) and what to save with the pages.
        self.clone_depth = -1
        self.clone_max_pages = 1000
        self.clone_external = True
        self.clone_files = True
        self.clone_max_mb = 200
        self.clone_robots = True
        # Which pages to follow: "site" (this website only), "subdomains" (also blog.…, shop.…) or "all".
        self.clone_scope = "site"
        # Clone into a folder that has an earlier copy of the site: only what changed is downloaded.
        self.clone_update = False
        self.site_entry = ""  # the start page inside the clone's folder
        self.files_done = 0
        self.files_total = 0
        self.files_failed = 0
        for k, v in kw.items():
            if k in self.FIELDS:
                setattr(self, k, v)
        self.speed = 0.0
        self.eta = None
        self._samples = collections.deque(maxlen=12)

    @property
    def path(self):
        return os.path.join(self.folder, self.filename)

    @property
    def display_name(self):
        if self.kind == "site":
            return self.title or self.filename or self.url
        return self.filename or self.title or self.url

    @property
    def is_clip(self):
        return self.clip_start >= 0 or self.clip_end >= 0

    @property
    def open_path(self):
        """What "Open" opens: the file, or a cloned website's start page."""
        if self.kind == "site" and self.site_entry:
            return os.path.join(self.path, *self.site_entry.split("/"))
        return self.path

    @property
    def category(self):
        if self.kind == "site":
            return "Websites"
        if self.kind == "media" and not self.filename:
            return "Music" if (self.media_format or "").startswith("ba") else "Video"
        return category_for(self.filename or self.url)

    @property
    def progress(self):
        if self.kind == "site":
            return self.files_done / self.files_total if self.files_total > 0 else 0.0
        return self.done / self.size if self.size > 0 else 0.0

    def to_dict(self):
        d = {k: getattr(self, k) for k in self.FIELDS}
        d["segments"] = [list(s) for s in self.segments]
        return d


class Manager:
    def __init__(self, post):
        """`post(fn, *args)` must run fn on the UI thread (GLib.idle_add)."""
        self.post = post
        self.items = []
        self.tasks = {}
        self.limiter = RateLimiter()
        self.on_added = []
        self.on_removed = []
        self.on_finished = []
        self.on_schedule_started = []
        self.on_schedule_done = []
        self.on_youtube_blocked = []  # (paused count, cooldown seconds or 0 for a bot check)
        self._yt_next = 0.0  # monotonic time before which no YouTube video starts
        self.youtube_wait_until = 0.0  # wall-clock end of a "too many requests" break (status bar)
        self._session = None  # date of the scheduler session in progress
        self._session_ids = set()
        self._session_done = False
        self._last_sched_check = 0
        self._dirty = False
        self._last_save = 0
        self._paths_lock = threading.Lock()  # download threads pick file names at the same time
        self.settings = dict(DEFAULT_SETTINGS)
        self._load()
        self.apply_settings()

    # --- persistence -----------------------------------------------------------
    @property
    def _list_file(self):
        return os.path.join(data_dir(), "downloads.json")

    @property
    def _settings_file(self):
        return os.path.join(config_dir(), "settings.json")

    def _load(self):
        try:
            self.settings.update(_read_json(self._settings_file))
        except (OSError, ValueError):
            pass
        try:
            for d in _read_json(self._list_file):
                item = Item(**d)
                if item.status in (DOWNLOADING, PAUSING):
                    item.status = QUEUED  # resume what was running when we quit
                self.items.append(item)
        except (OSError, ValueError):
            pass

    def save(self):
        _atomic_json(self._list_file, [i.to_dict() for i in self.items])
        self._dirty = False
        self._last_save = time.monotonic()

    def save_settings(self):
        _atomic_json(self._settings_file, self.settings)
        self.apply_settings()

    def apply_settings(self):
        self.limiter.rate = int(self.settings["speed_limit_kb"]) * 1024
        from . import media
        media.configure(self.settings)

    def changed(self):
        self._dirty = True

    # --- list operations ---------------------------------------------------------
    def folder_for(self, filename, kind="http", audio=False):
        base = self.settings["folder"]
        if not self.settings["categorize"]:
            return base
        if kind == "media":
            return os.path.join(base, "Music" if audio else "Video")
        if kind == "site":
            return os.path.join(base, "Websites")
        return os.path.join(base, category_for(filename or ""))

    def remembered_folder(self):
        """The folder last picked by hand, if that's turned on and it still exists."""
        folder = self.settings.get("last_folder") or ""
        if self.settings.get("remember_folder", True) and folder and os.path.isdir(folder):
            return folder
        return None

    def remember_folder(self, folder):
        """Store (or with None forget) the folder picked by hand for the next downloads."""
        value = folder or ""
        if self.settings.get("last_folder", "") != value:
            self.settings["last_folder"] = value
            self.save_settings()

    def pick_folder(self, filename, kind="http", audio=False):
        """(folder, auto) for a new download: the remembered folder, or the sorted default one."""
        folder = self.remembered_folder()
        if folder:
            return folder, False
        return self.folder_for(filename, kind, audio), True

    def taken_paths(self):
        return {i.path for i in self.items if i.filename and i.status != COMPLETED}

    def claim_name(self, item, folder, name):
        """Pick a free file name in `folder` for `item` (called from download threads)."""
        with self._paths_lock:
            taken = {i.path for i in list(self.items) if i is not item and i.filename and i.status != COMPLETED}
            return unique_path(folder, name, taken)

    def duplicate_of(self, item):
        """An unfinished download of the same link (and quality), e.g. from a double click."""
        for other in self.items:
            if (other.url == item.url and other.kind == item.kind and other.status != COMPLETED
                    and (item.kind != "media" or other.media_format == item.media_format)
                    and (item.kind != "media" or other.title == item.title)
                    and (other.container, other.clip_start, other.clip_end) == (item.container, item.clip_start, item.clip_end)
                    and (item.kind != "site" or other.folder == item.folder)):
                return other
        return None

    def add(self, item, start=True):
        dup = self.duplicate_of(item)
        if dup:
            # Don't download the same thing twice: one copy would sit in the queue showing
            # "Waiting in queue" next to a file that is already there.
            if start and dup.status in (PAUSED, ERROR):
                self.start(dup)
            return dup
        if item.scheduled and self._session:
            start = True  # the scheduled time window is open right now
            self._session_ids.add(item.id)
        if item.filename and item.kind == "site" and item.clone_update:
            for old in [i for i in self.items if i.kind == "site" and i.path == item.path and i.status in (COMPLETED, PAUSED, ERROR)]:
                self.remove(old, save=False)  # the new clone updates the same folder
        elif item.filename and item.kind == "site":
            item.filename = self._free_folder_name(item.folder, item.filename)
        elif item.filename:
            item.filename = unique_path(item.folder, item.filename, self.taken_paths())
        item.status = QUEUED if start else PAUSED
        self.items.append(item)
        for cb in self.on_added:
            cb(item)
        self.changed()
        self.schedule()
        return item

    def _free_folder_name(self, folder, name):
        """A folder name for a website clone that no other clone (or file) uses yet."""
        taken = {i.path for i in self.items if i.kind == "site"}
        candidate, n = name, 2
        while os.path.exists(os.path.join(folder, candidate)) or os.path.join(folder, candidate) in taken:
            candidate = f"{name} ({n})"
            n += 1
        return candidate

    def remove(self, item, delete_file=False, save=True):
        self._stop_task(item)
        if item in self.items:
            self.items.remove(item)
        if item.kind == "site":
            if delete_file and item.filename and os.path.isdir(item.path):
                shutil.rmtree(item.path, ignore_errors=True)
        elif item.filename:
            paths = [item.path + ".part"]
            if delete_file:
                paths.append(item.path)
            for p in paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        for cb in self.on_removed:
            cb(item)
        if save:
            self.save()
        else:
            self.changed()

    def remove_many(self, items, delete_files=False):
        for item in list(items):
            self.remove(item, delete_files, save=False)
        self.save()

    def start(self, item):
        if item.status in (DOWNLOADING, PAUSING, QUEUED):
            return
        if item.status == COMPLETED:
            item.done, item.segments, item.size = 0, [], -1
            if item.kind == "site":
                item.files_done = item.files_total = item.files_failed = 0  # cloned again into its folder
            elif item.filename and os.path.exists(item.path):
                item.filename = unique_path(item.folder, item.filename, self.taken_paths())
        item.status, item.error = QUEUED, ""
        self.changed()
        self.schedule()

    def pause(self, item):
        if item.status == QUEUED:
            item.status = PAUSED
        elif item.status == DOWNLOADING:
            item.status = PAUSING
            self._stop_task(item)
        self.changed()

    def start_all(self):
        for item in self.items:
            if item.status in (PAUSED, ERROR):
                self.start(item)

    def pause_all(self):
        for item in self.items:
            self.pause(item)

    def _stop_task(self, item):
        task = self.tasks.get(item.id)
        if task:
            task.stop()

    def active_count(self):
        return sum(1 for i in self.items if i.status in (DOWNLOADING, PAUSING))

    def _gentle(self, item):
        return item.kind == "media" and self.settings.get("youtube_gentle", True) and is_youtube(item.url)

    def schedule(self):
        free = int(self.settings["max_active"]) - self.active_count()
        now = time.monotonic()
        yt_running = sum(1 for i in self.items if i.status in (DOWNLOADING, PAUSING) and self._gentle(i))
        for item in self.items:
            if free <= 0:
                break
            if item.status == QUEUED and item.id not in self.tasks:
                if self._gentle(item):
                    # Other downloads behind it may still start.
                    if yt_running >= YT_PARALLEL or now < self._yt_next:
                        continue
                    yt_running += 1
                    self._yt_next = now + random.uniform(*YT_GAP)
                self._launch(item)
                free -= 1

    def proxy_for(self, url):
        return proxy_url(self.settings, url)

    def _launch(self, item):
        item.status = DOWNLOADING
        item._samples.clear()
        cls = {"media": MediaTask, "site": SiteTask}.get(item.kind, HttpTask)
        try:
            task = cls(item, self.limiter, lambda t, err: self.post(self._task_done, t, err), self.proxy_for(item.url))
        except Exception as e:  # noqa: BLE001 - must not stop the rest of the queue
            item.status, item.error = ERROR, str(e) or e.__class__.__name__
            return
        task.resolve_folder = self._resolve_folder
        task.claim_name = self.claim_name
        self.tasks[item.id] = task
        try:
            task.start()
        except Exception as e:  # noqa: BLE001 - e.g. no more threads
            self.tasks.pop(item.id, None)
            item.status, item.error = ERROR, str(e) or e.__class__.__name__

    def _resolve_folder(self, item, filename):
        """Folder for a download whose file name only became known when it started."""
        if not item.auto_folder:
            return item.folder
        return self.folder_for(filename, item.kind, (item.media_format or "").startswith("ba"))

    def _task_done(self, task, error):
        item = task.item
        if self.tasks.get(item.id) is task:
            self.tasks.pop(item.id, None)
        elif item.id in self.tasks:
            return False  # an old task of a download that has been started again since
        item.speed, item.eta = 0, None
        if task.stopped.is_set() and item.status != DOWNLOADING:
            # Paused (or removed) by the user.
            if item.status == PAUSING:
                item.status = PAUSED
        elif error and getattr(task, "throttled", False) and self._gentle(item) \
                and getattr(item, "_throttled", 0) < YT_RETRIES:
            # "Too many requests": wait, then try this video again.
            item._throttled = getattr(item, "_throttled", 0) + 1
            pause = YT_COOLDOWN * item._throttled
            self._yt_next = time.monotonic() + pause
            self.youtube_wait_until = time.time() + pause
            item.status, item.done, item.size = QUEUED, 0, -1
            for cb in self.on_youtube_blocked:
                cb(0, pause)
        elif error:
            item.status, item.error = ERROR, error
            if getattr(task, "bot_check", False) and self._gentle(item):
                # Every other YouTube video would hit the same check: stop asking for now.
                waiting = [i for i in self.items if i.status == QUEUED and self._gentle(i)]
                for i in waiting:
                    i.status = PAUSED
                if waiting:
                    for cb in self.on_youtube_blocked:
                        cb(len(waiting), 0)
        else:
            item.status, item.finished, item.error = COMPLETED, time.time(), ""
            item.segments = []
            if item.size < 0 or item.done > item.size:
                item.size = item.done
            for cb in self.on_finished:
                try:
                    cb(item)
                except Exception:  # noqa: BLE001 - e.g. notifications unavailable
                    traceback.print_exc()
        try:
            self.save()
        except OSError:
            self._dirty = True  # try again on the next tick
            traceback.print_exc()
        self.schedule()
        return False

    def _reconcile(self):
        """Repair states that disagree with the running tasks, so no row stays stuck
        on "Waiting in queue" or "Downloading" for a download that has ended."""
        for item in self.items:
            task = self.tasks.get(item.id)
            if task and item.status == QUEUED:
                item.status = DOWNLOADING
            elif not task and item.status == DOWNLOADING:
                item.status = QUEUED  # its task is gone: run it again
            elif not task and item.status == PAUSING:
                item.status = PAUSED
        for item_id in [i for i, t in self.tasks.items() if t.item not in self.items]:
            self.tasks.pop(item_id).stop()  # removed from the list while running

    def tick(self):
        """Called every half second on the UI thread."""
        now = time.monotonic()
        self._reconcile()
        for item in self.items:
            if item.status != DOWNLOADING:
                continue
            item._samples.append((now, item.done))
            t0, d0 = item._samples[0]
            if now - t0 > 0.4:
                item.speed = max(0.0, (item.done - d0) / (now - t0))
                item.eta = (item.size - item.done) / item.speed if item.speed > 0 and item.size > 0 else None
            self._dirty = True
        if self._dirty and now - self._last_save > 3:
            try:
                self.save()
            except OSError:
                self._last_save = now
                traceback.print_exc()
        if now - self._last_sched_check > 5:
            self._last_sched_check = now
            self.run_scheduler()
        self.schedule()

    # --- scheduler ------------------------------------------------------------------------
    def schedule_session(self, now=None):
        """Date (ISO string) of the scheduler window we're in, or None."""
        s = self.settings
        start = _minutes(s.get("schedule_start"))
        if not s.get("schedule_enabled") or start is None:
            return None
        stop = _minutes(s.get("schedule_stop"))
        now = now or datetime.datetime.now()
        m = now.hour * 60 + now.minute
        days = set(s.get("schedule_days") or [])
        today = now.date()
        overnight = stop is not None and stop <= start
        if today.weekday() in days and m >= start and (stop is None or overnight or m < stop):
            return today.isoformat()
        if overnight and m < stop:
            yesterday = today - datetime.timedelta(days=1)
            if yesterday.weekday() in days:
                return yesterday.isoformat()
        return None

    def run_scheduler(self):
        session = self.schedule_session()
        if session and self.settings.get("schedule_last") != session:
            self.settings["schedule_last"] = session
            self.save_settings()
            self._session, self._session_ids, self._session_done = session, set(), False
            for item in self.items:
                if item.status in (PAUSED, ERROR) and (item.scheduled or self.settings["schedule_all"]):
                    self.start(item)
                    self._session_ids.add(item.id)
            for cb in self.on_schedule_started:
                cb(len(self._session_ids))
        elif session and self._session is None:
            # Restarted inside a window that already began: keep tracking what's still running.
            self._session, self._session_done = session, False
            self._session_ids = {i.id for i in self.items if i.scheduled and i.status in (QUEUED, DOWNLOADING)}
        elif not session and self._session:
            if self.settings.get("schedule_enabled") and _minutes(self.settings.get("schedule_stop")) is not None:
                for item in self.items:
                    if item.id in self._session_ids and item.status in (QUEUED, DOWNLOADING):
                        self.pause(item)
            self._session = None

        if self._session and self._session_ids and not self._session_done:
            tracked = [i for i in self.items if i.id in self._session_ids]
            if all(i.status in (COMPLETED, ERROR) for i in tracked):
                self._session_done = True
                for cb in self.on_schedule_done:
                    cb()

    def total_speed(self):
        return sum(i.speed for i in self.items if i.status == DOWNLOADING)

    def shutdown(self):
        for item in self.items:
            if item.status in (DOWNLOADING, PAUSING):
                self._stop_task(item)
        # Keep "downloading" state on disk so they resume on next start.
        self.save()


def _minutes(text):
    try:
        h, m = (int(x) for x in (text or "").split(":"))
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _read_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode(locale.getpreferredencoding(False)))  # saved by 1.3.2 or older on Windows


def _atomic_json(path, data):
    # Private: holds cookies and the proxy password.
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # Always UTF-8: Windows defaults to a code page that can't hold Persian names.
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows: antivirus or the search indexer briefly holds the old file open.
            if attempt == 9:
                raise
            time.sleep(0.05)

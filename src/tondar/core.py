"""Download list, settings, persistence and the download queue."""

import collections
import datetime
import json
import os
import time
import uuid

from .http_task import HttpTask, RateLimiter
from .media import MediaTask
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
}


class Item:
    FIELDS = (
        "id", "url", "kind", "filename", "folder", "size", "done", "status", "error", "created",
        "finished", "segments", "resumable", "referer", "user_agent", "cookies", "max_segments",
        "media_format", "title", "page_url", "scheduled",
    )

    def __init__(self, **kw):
        self.id = uuid.uuid4().hex
        self.url = ""
        self.kind = "http"  # "http" or "media" (yt-dlp)
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
        return self.filename or self.title or self.url

    @property
    def category(self):
        if self.kind == "media" and not self.filename:
            return "Music" if (self.media_format or "").startswith("ba") else "Video"
        return category_for(self.filename or self.url)

    @property
    def progress(self):
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
        self._session = None  # date of the scheduler session in progress
        self._session_ids = set()
        self._session_done = False
        self._last_sched_check = 0
        self._dirty = False
        self._last_save = 0
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
            with open(self._settings_file) as f:
                self.settings.update(json.load(f))
        except (OSError, ValueError):
            pass
        try:
            with open(self._list_file) as f:
                for d in json.load(f):
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

    def changed(self):
        self._dirty = True

    # --- list operations ---------------------------------------------------------
    def folder_for(self, filename, kind="http", audio=False):
        base = self.settings["folder"]
        if not self.settings["categorize"]:
            return base
        if kind == "media":
            return os.path.join(base, "Music" if audio else "Video")
        return os.path.join(base, category_for(filename or ""))

    def taken_paths(self):
        return {i.path for i in self.items if i.filename and i.status != COMPLETED}

    def add(self, item, start=True):
        if item.scheduled and self._session:
            start = True  # the scheduled time window is open right now
            self._session_ids.add(item.id)
        if item.filename:
            item.filename = unique_path(item.folder, item.filename, self.taken_paths())
        item.status = QUEUED if start else PAUSED
        self.items.append(item)
        for cb in self.on_added:
            cb(item)
        self.changed()
        self.schedule()
        return item

    def remove(self, item, delete_file=False):
        self._stop_task(item)
        if item in self.items:
            self.items.remove(item)
        if item.filename:
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
        self.save()

    def start(self, item):
        if item.status in (DOWNLOADING, PAUSING, QUEUED):
            return
        if item.status == COMPLETED:
            item.done, item.segments, item.size = 0, [], -1
            if item.filename and os.path.exists(item.path):
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

    def schedule(self):
        free = int(self.settings["max_active"]) - self.active_count()
        for item in self.items:
            if free <= 0:
                break
            if item.status == QUEUED and item.id not in self.tasks:
                self._launch(item)
                free -= 1

    def proxy_for(self, url):
        return proxy_url(self.settings, url)

    def _launch(self, item):
        item.status = DOWNLOADING
        item._samples.clear()
        cls = MediaTask if item.kind == "media" else HttpTask
        task = cls(item, self.limiter, lambda t, err: self.post(self._task_done, t, err), self.proxy_for(item.url))
        self.tasks[item.id] = task
        task.start()

    def _task_done(self, task, error):
        item = task.item
        self.tasks.pop(item.id, None)
        item.speed, item.eta = 0, None
        if task.stopped.is_set() and item.status != DOWNLOADING:
            # Paused (or removed) by the user.
            if item.status == PAUSING:
                item.status = PAUSED
        elif error:
            item.status, item.error = ERROR, error
        else:
            item.status, item.finished = COMPLETED, time.time()
            item.segments = []
            for cb in self.on_finished:
                cb(item)
        self.save()
        self.schedule()
        return False

    def tick(self):
        """Called every half second on the UI thread."""
        now = time.monotonic()
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
            self.save()
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


def _atomic_json(path, data):
    # Private: holds cookies and the proxy password.
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
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

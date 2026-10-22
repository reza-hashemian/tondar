#!/usr/bin/env python3
"""Make the README screenshots (docs/screenshots/*.png) from made-up downloads.

Runs Tondar off-screen (GTK's Broadway backend) with an empty, temporary settings and data folder,
so nothing from your own downloads list ends up in the pictures. Nothing is downloaded: link
checks and video lookups return the fake answers below.

    tools/screenshots.py [out-dir] [--dark]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = os.path.abspath(ARGS[0] if ARGS else os.path.join(ROOT, "docs", "screenshots"))
DARK = "--dark" in sys.argv
SCALE = 2  # pictures at twice the size, sharp on high-DPI screens

if "TONDAR_SHOTS_CHILD" not in os.environ:
    # Start a private Broadway display and run this script again inside it.
    tmp = tempfile.mkdtemp(prefix="tondar-shots-")
    display = ":%d" % (40 + os.getpid() % 50)
    broadway = subprocess.Popen(["gtk4-broadwayd", display], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    home = os.path.join(tmp, "home", "user")
    os.makedirs(os.path.join(home, "Downloads"))
    env = dict(os.environ, TONDAR_SHOTS_CHILD="1", GDK_BACKEND="broadway", BROADWAY_DISPLAY=display,
               XDG_DATA_HOME=os.path.join(tmp, "data"), XDG_CONFIG_HOME=os.path.join(tmp, "config"),
               TONDAR_APP_ID="io.github.tondar.Screenshots", GTK_A11Y="none",
               PYTHONPATH=os.path.join(ROOT, "src"))
    try:
        code = subprocess.call([sys.executable, *sys.argv], env=env)
    finally:
        broadway.terminate()
    # The extension's button and menu on a made-up video page, in headless Chrome.
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser", "brave-browser") if shutil.which(c)), None)
    if chrome and not DARK:
        page = "file://" + os.path.join(ROOT, "tools", "extension-demo.html") + "#menu"
        out = os.path.join(OUT, "extension-menu.png")
        subprocess.call([chrome, "--headless=new", f"--user-data-dir={tmp}/chrome", "--hide-scrollbars",
                         f"--force-device-scale-factor={SCALE}", "--window-size=1280,700",
                         "--virtual-time-budget=4000", "--allow-file-access-from-files",
                         f"--screenshot={out}", page], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("saved", out)
    else:
        print("skipped extension-menu.png (no Chrome)" if not chrome else "", end="")
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)

import json  # noqa: E402
import traceback  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

from tondar import core, dialogs, tray, util  # noqa: E402

DL = "/home/user/Downloads"
NOW = time.time()
GB, MB = 1024 ** 3, 1024 ** 2


def fake_list():
    def item(name, sub, size, status, done=None, kind="http", hours_ago=0, **kw):
        d = dict(filename=name, folder=f"{DL}/{sub}" if sub else DL, size=size, status=status,
                 done=size if done is None else done, kind=kind, url=kw.pop("url", f"https://example.com/{name}"),
                 created=NOW - hours_ago * 3600 - 600, finished=NOW - hours_ago * 3600, resumable=True)
        d.update(kw)
        return d

    return [
        item("ubuntu-24.10-desktop-amd64.iso", "Programs", int(5.7 * GB), "downloading", int(3.6 * GB)),
        item("Big Buck Bunny (4K).mp4", "Video", int(1.2 * GB), "downloading", int(0.49 * GB), kind="media"),
        item("LibreOffice_24.8.2_Win_x86-64.msi", "Programs", 352 * MB, "queued", 0),
        item("debian-13.1.0-amd64-DVD-1.iso", "Programs", int(3.9 * GB), "paused", 0, scheduled=True),
        item("Blender-4.2.3-linux-x64.tar.xz", "Compressed", 338 * MB, "paused", 121 * MB),
        item("آموزش پایتون - جلسه ۱.mp4", "Video", 486 * MB, "completed", kind="media", hours_ago=1),
        item("Sintel (1080p).mkv", "Video", 812 * MB, "completed", kind="media", hours_ago=3),
        item("Podcast - Episode 42.m4a", "Music", 58 * MB, "completed", kind="media", hours_ago=5),
        item("Python Documentation", "", 96 * MB, "completed", kind="site", title="Python Documentation",
             url="https://docs.python.org/3/", files_done=1240, files_total=1240, hours_ago=8),
        item("VLC-3.0.21-win64.exe", "Programs", 42 * MB, "completed", hours_ago=26),
        item("Atkinson-Hyperlegible-Font.zip", "Compressed", 3 * MB, "completed", hours_ago=30),
        item("Annual-Report-2025.pdf", "Documents", 7 * MB, "completed", hours_ago=50),
    ]


# Running downloads: their speed and time left, set again every tick (nothing really downloads).
LIVE = {"ubuntu-24.10-desktop-amd64.iso": (8.4 * MB, 255), "Big Buck Bunny (4K).mp4": (3.1 * MB, 230)}

VIDEO_INFO = {
    "title": "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film", "duration": 634,
    "extractor_key": "Youtube", "uploader": "Blender",
    "formats": [
        *[{"format_id": f"v{h}", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": h, "tbr": t}
          for h, t in [(1080, 4400), (720, 2500), (480, 1200), (360, 700)]],
        *[{"format_id": f"w{h}", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": h, "tbr": t}
          for h, t in [(2160, 16000), (1440, 9000), (1080, 4000)]],
        {"format_id": "a1", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "tbr": 130},
        {"format_id": "a2", "ext": "webm", "vcodec": "none", "acodec": "opus", "tbr": 140},
    ],
}


def prepare_folders():
    data, config = util.data_dir(), util.config_dir()
    with open(os.path.join(data, "downloads.json"), "w") as f:
        json.dump(fake_list(), f)
    settings = dict(folder=DL, schedule_enabled=True, schedule_start="02:00", schedule_stop="07:00",
                    confirm_browser=True, cookies_browser="")
    with open(os.path.join(config, "settings.json"), "w") as f:
        json.dump(settings, f)


def patch():
    tray.create = lambda app: None
    dialogs.ytdlp_command = lambda *a, **k: ["yt-dlp"]
    dialogs.probe_media = lambda item, playlist=False, proxy=None: dict(VIDEO_INFO)
    dialogs.probe = lambda item, proxy=None: (int(5.7 * GB), True, "ubuntu-24.10-desktop-amd64.iso",
                                              "application/x-iso9660-image")
    dialogs._page_title = lambda url, proxy=None: ("Python 3 Documentation", url, "text/html")


def _sheet(dialog):
    """The visible card of an Adw.Dialog (the dialog widget itself covers the whole window)."""
    full = dialog.get_width()
    todo = [dialog]
    while todo:
        w = todo.pop(0)
        if w.get_width() < full - 1 and w.get_width() > 50:
            return w
        c = w.get_first_child()
        while c:
            todo.append(c)
            c = c.get_next_sibling()
    return dialog


def save(widget, name):
    if isinstance(widget, Adw.Dialog):
        widget = _sheet(widget)
    if isinstance(widget, Gtk.Window):
        widget.set_focus(None)  # no selected text in the address box; capture after it redraws
    GLib.timeout_add(400, lambda: _capture(widget, name))


def _capture(widget, name, tries=[0]):
    """Returns True (call again) while the widget hasn't been drawn yet."""
    w, h = widget.get_width(), widget.get_height()
    snap = Gtk.Snapshot()
    snap.scale(SCALE, SCALE)
    Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        widget.queue_draw()
        tries[0] += 1
        return tries[0] < 30
    tries[0] = 0
    renderer = Gsk.CairoRenderer.new()
    renderer.realize_for_display(Gdk.Display.get_default())
    # Only the part that is drawn: a window may be taller than what's in it while it resizes.
    child = widget.get_child() if isinstance(widget, Gtk.Window) else None
    ok, rect = child.compute_bounds(widget) if child else (False, None)
    if ok:
        bounds = Graphene.Rect().init(0, 0, w * SCALE, (rect.get_y() + rect.get_height()) * SCALE)
    else:
        bounds = node.get_bounds()
    try:
        texture = renderer.render_texture(node, bounds)
    finally:
        renderer.unrealize()
    path = os.path.join(OUT, name + ("-dark" if DARK else "") + ".png")
    texture.save_to_png(path)
    print("saved", path, f"{texture.get_width()}x{texture.get_height()}")
    return False


def main():
    os.makedirs(OUT, exist_ok=True)
    prepare_folders()
    patch()
    from tondar.app import App

    app = App()
    steps = []

    def live():
        for it in app.manager.items:
            if it.filename in LIVE:
                it.status = core.DOWNLOADING
                it.speed, it.eta = LIVE[it.filename]

    def later(delay, fn):
        steps.append((delay, fn))

    def run_steps():
        if not steps:
            app.quit()
            return False
        delay, fn = steps.pop(0)

        def go():
            live()
            try:
                fn()
            except Exception:  # noqa: BLE001 - one picture failing must not stop the rest
                traceback.print_exc()
            GLib.timeout_add(100, run_steps)
            return False

        GLib.timeout_add(delay, go)
        return False

    def find(name):
        return next(i for i in app.manager.items if i.filename == name)

    state = {}

    def start():
        Gtk.Settings.get_default().set_property("gtk-font-name", "Cantarell 11")
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if DARK else Adw.ColorScheme.FORCE_LIGHT)
        app.manager.tick = lambda: None  # don't start the fake downloads
        live()
        win = app.present_main()
        win.set_default_size(980, 640)

        later(1500, lambda: save(win, "main-window"))
        later(1500, lambda: None)

        def add_video():
            state["add"] = dialogs.AddWindow(app, {"url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ", "kind": "media"})
            state["add"].set_default_size(580, 780)
            state["add"].present()
        later(100, add_video)
        later(2500, lambda: save(state["add"], "new-download-video"))
        later(1500, lambda: state["add"].close())

        def add_file():
            state["add"] = dialogs.AddWindow(app, {"url": "https://releases.ubuntu.com/24.10/ubuntu-24.10-desktop-amd64.iso"})
            state["add"].set_default_size(580, 560)
            state["add"].present()
        later(100, add_file)
        later(2500, lambda: save(state["add"], "new-download-file"))
        later(1500, lambda: state["add"].close())

        def progress():
            app.show_progress(find("ubuntu-24.10-desktop-amd64.iso"), force=True)
        later(100, progress)
        later(1500, lambda: save(next(iter(app.progress_windows.values())), "progress-window"))
        later(1500, lambda: [w.close() for w in list(app.progress_windows.values())])

        def complete():
            from tondar.popups import CompleteWindow
            state["done"] = CompleteWindow(app, find("Sintel (1080p).mkv"))
            state["done"].present()
        later(100, complete)
        later(1500, lambda: save(state["done"], "download-complete"))
        later(1500, lambda: state["done"].close())

        def clone():
            state["clone"] = dialogs.CloneWindow(app, "https://docs.python.org/3/")
            state["clone"].present()
        later(100, clone)
        later(2500, lambda: save(state["clone"], "clone-website"))
        later(1500, lambda: state["clone"].close())

        def tall():
            win.set_default_size(980, 980)
        later(100, tall)

        def prefs(page):
            state["prefs"] = dialogs.PreferencesDialog(app, page)
            state["prefs"].present(win)
        for page, name in [(None, "preferences"), ("scheduler", "scheduler"), ("network", "proxy")]:
            later(100, lambda page=page: prefs(page))
            later(1500, lambda name=name: save(state["prefs"], name))
            later(1500, lambda: state["prefs"].force_close())

        def browser():
            state["browser"] = dialogs.BrowserDialog(app)
            state["browser"].present(win)
        later(100, browser)
        later(1500, lambda: save(state["browser"], "browser-integration"))
        later(1500, lambda: state["browser"].force_close())

        def community():
            from tondar.community import CommunityDialog
            state["community"] = CommunityDialog(app)
            state["community"].present(win)
        later(100, community)
        later(1500, lambda: save(state["community"], "updates-and-news"))
        later(1500, lambda: state["community"].force_close())

        GLib.timeout_add(300, run_steps)
        GLib.timeout_add_seconds(90, lambda: app.quit())  # never hang

    app.connect("activate", lambda *_: None)
    GLib.idle_add(lambda: (start(), False)[1])
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()

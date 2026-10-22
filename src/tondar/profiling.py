"""Timing report for slow-opening windows: run Tondar with --profile.

For each window or dialog opened from a menu or shortcut it writes to profile.txt (in the data
folder) how long our Python code took and, frame by frame, how long GTK spent in each drawing
phase. Off unless --profile is given.
"""

import cProfile
import io
import os
import platform
import pstats
import sys
import time

from gi.repository import GLib, Gtk

from .util import data_dir

PHASES = ("before-paint", "update", "layout", "paint", "after-paint")
WATCH_SECONDS = 1.5

enabled = "--profile" in sys.argv
# GTK's own messages, written there by the Windows launcher (windows/run_tondar.py).
_gtk_log = os.path.join(data_dir(), "profile-gtk.txt") if enabled and sys.platform == "win32" else None
_t0 = time.perf_counter()
_file = None
_busy = False
_described = False


def path():
    return os.path.join(data_dir(), "profile.txt")


def write(text):
    global _file
    if _file is None:
        _file = open(path(), "w", encoding="utf-8", buffering=1)
    _file.write(text + "\n")


def describe(app, win):
    """Write what the timings depend on: versions, renderer, screen, list size."""
    global _described
    if _described:
        return
    _described = True
    try:
        renderer = type(win.get_renderer()).__name__ if win.get_renderer() else "?"
    except Exception:  # noqa: BLE001
        renderer = "?"
    monitor = win.get_display().get_monitor_at_surface(win.get_surface()) if win.get_surface() else None
    write(f"Tondar profile  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    write(f"System: {platform.platform()}  Python {platform.python_version()}  CPU count {os.cpu_count()}")
    write(f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}  "
          f"renderer {renderer}  GSK_RENDERER={os.environ.get('GSK_RENDERER', '')!r}")
    if monitor:
        write(f"Screen: {monitor.get_geometry().width}x{monitor.get_geometry().height} "
              f"scale {monitor.get_scale_factor()}  refresh {monitor.get_refresh_rate() / 1000:.0f} Hz")
    for key in ("GSK_RENDERER", "GDK_DEBUG", "GDK_DISABLE", "GSK_DEBUG", "GDK_BACKEND", "GDK_SCALE"):
        if os.environ.get(key):
            write(f"Environment: {key}={os.environ[key]}")
    surface = win.get_surface()
    if surface is not None:
        write(f"Window scale {surface.get_scale():g}, display {type(win.get_display()).__name__}")
    _check_gpu(win)
    write(f"Downloads in list: {len(app.manager.items)}")
    write(f"Main window first frame: {1000 * (time.perf_counter() - _t0):.0f} ms after start")
    GLib.timeout_add(1500, lambda: _renderer_experiments(win) and False)


def _copy_gtk_log():
    text = "(not on this system)"
    if _gtk_log:
        try:
            with open(_gtk_log, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()[-8000:] or "(none)"
        except OSError as e:
            text = f"(couldn't read: {e})"
    write("GTK messages:\n" + text + "\n")


def _renderer_name(win):
    r = win.get_renderer()
    return type(r).__name__ if r else "none"


def _renderer_experiments(win):
    """Which drawing mode windows get: hidden, shown, and the main window made again."""
    hidden = Gtk.Window(title="test")
    hidden.realize()
    write(f"Test window, realized hidden: {_renderer_name(hidden)}")
    hidden.destroy()

    shown = Gtk.Window(title="Tondar test", default_width=200, default_height=120)

    def on_shown(*_):
        def check():
            write(f"Test window, shown: {_renderer_name(shown)}")
            shown.destroy()
            remake_main()
            return False
        GLib.timeout_add(300, check)

    shown.connect("map", on_shown)
    shown.present()

    def remake_main():
        before = _renderer_name(win)
        win.set_visible(False)
        win.unrealize()

        def after_map(*_):
            def check():
                write(f"Main window made again: {before} -> {_renderer_name(win)}")
                _copy_gtk_log()
                return False
            GLib.timeout_add(300, check)

        handler = []
        handler.append(win.connect("map", lambda *a: (win.disconnect(handler[0]), after_map())))
        win.present()


def _check_gpu(win):
    """Which GPU drawing modes work here, and why the others don't."""
    from gi.repository import Gsk

    surface = win.get_surface()
    try:
        ctx = surface.create_gl_context()
        ctx.realize()
        major, minor = ctx.get_version()
        write(f"OpenGL: works, version {major}.{minor}{' (GLES)' if ctx.get_use_es() else ''}")
    except Exception as e:  # noqa: BLE001
        write(f"OpenGL: fails: {getattr(e, 'message', e)}")
    try:
        chosen = Gsk.Renderer.new_for_surface(surface)
        write(f"GTK's choice for this window: {type(chosen).__name__}")
        chosen.unrealize()
    except Exception as e:  # noqa: BLE001
        write(f"GTK's choice for this window: fails: {getattr(e, 'message', e)}")
    for name in ("GLRenderer", "VulkanRenderer"):
        cls = getattr(Gsk, name, None)
        if cls is None:
            continue
        try:
            renderer = cls()
            renderer.realize(surface)
            renderer.unrealize()
            write(f"{name} on this window: works")
        except Exception as e:  # noqa: BLE001
            write(f"{name} on this window: fails: {getattr(e, 'message', e)}")
    for name in ("NglRenderer", "GLRenderer", "VulkanRenderer"):
        cls = getattr(Gsk, name, None)
        if cls is None:
            write(f"{name}: not in this GTK")
            continue
        try:
            renderer = cls()
            renderer.realize_for_display(win.get_display())
            renderer.unrealize()
            write(f"{name}: works")
        except Exception as e:  # noqa: BLE001
            write(f"{name}: fails: {getattr(e, 'message', e)}")


def wrap(app, name, callback):
    """Return an action callback that records how opening `name` went."""
    if not enabled:
        return callback

    def run(*args):
        global _busy
        if _busy:  # one at a time
            return callback(*args)
        _busy = True
        before = set(_toplevels())
        frames = {}  # window title -> list of (phase, time)
        prof = cProfile.Profile()
        start = time.perf_counter()
        prof.enable()
        try:
            callback(*args)
        finally:
            sync = time.perf_counter() - start
        watched_ids = []  # (window, frame clock, handler ids)
        for win in _toplevels():
            if win.get_frame_clock() is not None:
                _attach(win, frames, watched_ids)
            else:
                win.connect("realize", lambda w: _attach(w, frames, watched_ids))

        def finish():
            global _busy
            prof.disable()
            for win, clock, ids in watched_ids:
                for i in ids:
                    clock.disconnect(i)
            new = [w for w in _toplevels() if w not in before]
            _report(name, start, sync, frames, prof, new)
            _busy = False
            return False

        GLib.timeout_add(int(WATCH_SECONDS * 1000), finish)

    return run


def _toplevels():
    model = Gtk.Window.get_toplevels()
    return [model.get_item(i) for i in range(model.get_n_items())]


def _attach(win, frames, watched_ids):
    clock = win.get_frame_clock()
    if clock is None:
        return
    label = f"{type(win).__name__} {win.get_title() or ''}".strip()
    log = frames.setdefault(label, [])
    ids = [clock.connect(phase, lambda _c, phase=phase: log.append((phase, time.perf_counter())))
           for phase in PHASES]
    watched_ids.append((win, clock, ids))


def _report(name, start, sync, frames, prof, new):
    ms = lambda t: f"{1000 * t:.0f}"  # noqa: E731
    write(f"=== {name}  (at {ms(start - _t0)} ms)")
    write(f"Our code when opening: {ms(sync)} ms" + (f"; new windows: {', '.join(f'{type(w).__name__} ({_renderer_name(w)})' for w in new)}"
                                                    if new else ""))
    for label, log in frames.items():
        if not log:
            continue
        write(f"-- frames of {label} (ms): since opening | since last frame | update | layout+draw")
        last_end, frame = start, {}
        for phase, t in log:
            frame[phase] = t
            if phase == "after-paint":
                b = frame.get("before-paint", t)
                u, la, p = frame.get("update", b), frame.get("layout", b), frame.get("paint", b)
                write(f"   {ms(t - start):>5} | {ms(t - last_end):>4} | {ms(max(la - u, 0)):>4} | {ms(max(p - la, 0)):>4}")
                last_end, frame = t, {}
    out = io.StringIO()
    stats = pstats.Stats(prof, stream=out)
    stats.sort_stats("cumulative").print_stats(18)
    write("-- Python, slowest by total time (cumulative):")
    lines = out.getvalue().splitlines()
    first = next((i for i, line in enumerate(lines) if "ncalls" in line), 0)
    write("\n".join(line for line in lines[first:] if line.strip()))
    write("")

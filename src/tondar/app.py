import base64
import json
import os
import subprocess
import sys
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, VERSION, ipc  # noqa: E402
from .core import COMPLETED, DOWNLOADING, QUEUED, Item, Manager  # noqa: E402
from .community import CommunityDialog  # noqa: E402
from .dialogs import AddWindow, BrowserDialog, CloneWindow, PreferencesDialog  # noqa: E402
from .popups import CompleteWindow, ProgressWindow  # noqa: E402
from .media import audio_selector  # noqa: E402
from .util import MACOS, WINDOWS, clean_page_title, looks_like_media_page, sanitize_filename, unique_path  # noqa: E402
from .window import MainWindow, bring_to_front, open_folder, open_uri  # noqa: E402


class App(Adw.Application):
    def __init__(self):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if WINDOWS or MACOS:  # no D-Bus: single instance is handled by ipc.py
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.manager = None
        self.window = None
        self.tray = None
        self.progress_windows = {}  # item id -> ProgressWindow
        # Links from the browser wait here while a New Download window for another link is open:
        # with one window per link they all opened on the same spot, the main window came up
        # over the older ones, and only the last link was ever downloaded.
        self.browser_dialog = None
        self.pending = []
        GLib.set_application_name("Tondar")

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.manager = Manager(lambda fn, *a: GLib.idle_add(fn, *a))
        self.manager.on_finished.append(self._on_finished)
        self.manager.on_removed.append(self._close_progress)
        self.manager.on_schedule_started.append(self._on_schedule_started)
        self.manager.on_schedule_done.append(self._on_schedule_done)
        self._shutdown_timer = 0
        # Stay alive without windows so the browser extension can always reach us.
        self.hold()
        if WINDOWS or MACOS:
            ipc.serve(lambda args: GLib.idle_add(self.handle_args, args))
        if not WINDOWS:
            from .bridge import register_installed

            register_installed()

        for name, cb, accels in [
            ("add", lambda *_: self.open_add_dialog({}), ["<Primary>n"]),
            ("clone", lambda *_: self.open_clone_dialog(""), ["<Primary><Shift>n"]),
            ("start-all", lambda *_: self.manager.start_all(), []),
            ("pause-all", lambda *_: self.manager.pause_all(), []),
            ("clear-completed", lambda *_: self._clear_completed(), []),
            ("clear-queued", lambda *_: self.present_main().confirm_clear_queued(), []),
            ("community", lambda *_: CommunityDialog(self).present(self.present_main()), []),
            ("preferences", lambda *_: PreferencesDialog(self).present(self.present_main()), ["<Primary>comma"]),
            ("browser", lambda *_: BrowserDialog(self).present(self.present_main()), []),
            ("scheduler", lambda *_: PreferencesDialog(self, "scheduler").present(self.present_main()), []),
            ("proxy", lambda *_: PreferencesDialog(self, "network").present(self.present_main()), []),
            ("ytdlp", lambda *_: self._open_ytdlp(), []),
            ("about", lambda *_: self._about(), []),
            ("quit", lambda *_: self.quit_app(), ["<Primary>q"]),
            ("show", lambda *_: self.present_main(), []),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

        for name, cb in [("open-item", self._open_item), ("open-item-folder", self._open_item_folder),
                         ("show-progress", self._show_progress_action)]:
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", cb)
            self.add_action(action)

        from . import tray

        self.tray = tray.create(self)
        self._tray_tick = 0
        GLib.timeout_add(500, self._tick)

    def do_activate(self):
        self.present_main()

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        if any(a in ("-h", "--help") for a in args):
            command_line.print_literal("Usage: tondar [--background] [URL…]\n")
            return 0
        return self.handle_args(args)

    def handle_args(self, args):
        """Command line of this launch, or one forwarded from a second launch."""
        show, requests = True, []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--background":
                show = False
            elif arg == "--add" and i + 1 < len(args):
                i += 1
                try:
                    requests.append(json.loads(base64.urlsafe_b64decode(args[i] + "==")))
                except ValueError:
                    pass
                show = False
            elif arg == "--new-download":  # from the launcher's right-click menu
                GLib.idle_add(lambda: self.open_add_dialog({}) and False)
                show = False
            elif arg == "--clone":
                GLib.idle_add(lambda: self.open_clone_dialog("") and False)
                show = False
            elif "://" in arg:
                requests.append({"url": arg})
            i += 1
        if show:
            self.present_main()
        for req in requests:
            self.handle_request(req)
        return 0  # also ends the GLib.idle_add call when forwarded on Windows

    # --- windows -------------------------------------------------------------------------
    def present_main(self):
        if not self.window:
            self.window = MainWindow(self)
        self.window.present()
        return self.window

    def open_add_dialog(self, request, from_browser=False):
        if from_browser:
            if self.browser_dialog is not None:
                self.pending.append(request)
                self.browser_dialog.update_pending(len(self.pending))
                bring_to_front(self.browser_dialog)
                return False
            win = AddWindow(self, request)
            self.browser_dialog = win
            # "destroy" doesn't come while Python still holds the window: watch the closing itself.
            win.connect("close-request", lambda w: GLib.idle_add(self._browser_dialog_closed, w) and False)
            win.update_pending(len(self.pending))
        else:
            win = AddWindow(self, request)
        bring_to_front(win)
        return False

    def _browser_dialog_closed(self, win):
        if self.browser_dialog is win and not win.get_visible():
            self.browser_dialog = None
            if self.pending:
                self.open_add_dialog(self.pending.pop(0), True)
        return False

    def add_pending_now(self):
        """"Add All": the links still waiting get the default choices."""
        waiting, self.pending = self.pending, []
        added = [self.quick_add(req, show=False) for req in waiting]
        if self.browser_dialog:
            self.browser_dialog.update_pending(0)
        n = sum(1 for a in added if a)
        if n and self.window and self.window.get_visible():
            self.window.toast(f"Added {n} more download{'s' if n != 1 else ''}")

    def quick_add(self, req, show=True):
        """Add a link from the browser with the default choices (no New Download window)."""
        m = self.manager
        url = (req.get("url") or "").strip()
        if not url:
            return None
        name = sanitize_filename(req.get("filename") or "", "")
        media = (req.get("kind") == "media" or looks_like_media_page(url) or req.get("clip")
                 or req.get("container") or req.get("audio"))
        item = Item(
            url=url, kind="media" if media else "http", referer=req.get("referer", ""),
            user_agent=req.get("user_agent", ""), cookies=req.get("cookies", []), page_url=req.get("page_url", ""),
            max_segments=int(m.settings["segments"]), size=int(req.get("size") or -1), popup=True,
        )
        clip = req.get("clip") if isinstance(req.get("clip"), dict) else None
        if clip:
            item.clip_start = _num(clip.get("start"), -1)
            item.clip_end = _num(clip.get("end"), -1)
            if item.clip_start <= 0:
                item.clip_start = -1 if item.clip_end < 0 else 0
        if media:
            container = req.get("container") or ""
            audio = bool(req.get("audio"))
            item.media_format = audio_selector(container) if audio else "bv*+ba/b"
            item.container = container
            item.title = sanitize_filename(clean_page_title(req.get("title") or ""), "")
            item.folder, item.auto_folder = m.pick_folder(item.title or url, "media", audio)
        else:
            item.folder, item.auto_folder = m.pick_folder(name or url)
            if name:
                item.filename = unique_path(item.folder, name, m.taken_paths())
        added = m.add(item, start=True)
        if show and added is not item and self.window and self.window.get_visible():
            self.window.toast(f"Already in the list: “{added.display_name}”")
        if added is item or added.status not in (COMPLETED,):
            self.show_progress(added, force=added is not item)
        return added

    def open_clone_dialog(self, url):
        bring_to_front(CloneWindow(self, url))
        return False

    def show_progress(self, item, force=False):
        """The window that follows one download (also opened from the list with "Progress Window")."""
        if not force and not self.manager.settings.get("progress_window", True):
            return
        win = self.progress_windows.get(item.id)
        if win is None:
            win = ProgressWindow(self, item)
            self.progress_windows[item.id] = win
            win.connect("close-request", lambda w, i=item.id: self.progress_windows.pop(i, None) and False)
        bring_to_front(win)

    def _close_progress(self, item):
        win = self.progress_windows.pop(item.id, None)
        if win:
            win.close()

    def _show_progress_action(self, _a, param):
        item = self._find(param.get_string())
        if item:
            self.show_progress(item, force=True)

    def handle_request(self, req):
        """A link sent from the browser extension (or the command line)."""
        url = (req.get("url") or "").strip()
        if not url:
            return
        if req.get("kind") == "site":
            self.open_clone_dialog(url)
            return
        media = (req.get("kind") == "media" or looks_like_media_page(url) or req.get("clip")
                 or req.get("container") or req.get("audio"))
        if self.manager.settings["confirm_browser"] or media:  # videos always need a quality choice
            self.open_add_dialog(req, from_browser=True)
            return
        if not self.manager.settings.get("progress_window", True):
            win = self.present_main()
            bring_to_front(win)  # show the new download in the list
        self.quick_add(req)

    # --- periodic update --------------------------------------------------------------------
    def _tick(self):
        # An exception escaping a GLib timeout removes it for good: downloads would sit in
        # "Waiting in queue" and the window would stop updating.
        for step in (self.manager.tick, self._refresh_window, self._refresh_progress, self._refresh_tray):
            try:
                step()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        return True

    def _refresh_tray(self):
        self._tray_tick += 1
        if not self.tray or self._tray_tick % 4:
            return
        active = [i for i in self.manager.items if i.status == DOWNLOADING]
        waiting = sum(1 for i in self.manager.items if i.status == QUEUED)
        tip = "Tondar"
        if active:
            done = sum(max(i.done, 0) for i in active)
            total = sum(i.size for i in active if i.size > 0)
            tip += f" — {len(active)} downloading" + (f" · {min(100, done * 100 // total)}%" if total else "")
        if waiting:
            tip += f"{' ·' if active else ' —'} {waiting} waiting"
        self.tray.set_tooltip(tip)

    def _refresh_window(self):
        if self.window and self.window.get_visible():
            self.window.refresh()

    def _refresh_progress(self):
        for win in list(self.progress_windows.values()):
            try:
                win.refresh()
            except Exception:  # noqa: BLE001 - one window must not stop the others
                traceback.print_exc()

    # --- notifications -------------------------------------------------------------------------
    def _notify(self, nid, title, body, item=None):
        if not self.manager.settings["notify"]:
            return
        n = Gio.Notification.new(title)
        n.set_body(body)
        if item:
            n.set_default_action(f"app.open-item::{item.id}")
            n.add_button("Open Folder", f"app.open-item-folder::{item.id}")
        else:
            n.set_default_action("app.show")
        self.send_notification(nid, n)

    def _on_finished(self, item):
        self._close_progress(item)
        if item.popup and self.manager.settings.get("complete_window", True):
            bring_to_front(CompleteWindow(self, item))
            return
        title = "Website saved" if item.kind == "site" else "Download complete"
        self._notify(f"done-{item.id}", title, item.display_name, item)

    # --- scheduler -----------------------------------------------------------------------------
    def _on_schedule_started(self, count):
        if count:
            self._notify("schedule", "Scheduled downloads started", f"{count} download{'s' if count != 1 else ''}")

    def _on_schedule_done(self):
        action = self.manager.settings["schedule_done_action"]
        self._notify("schedule", "Scheduled downloads finished", "")
        if action == "quit":
            self.quit_app()
        elif action == "shutdown":
            self._start_shutdown_countdown()

    def _start_shutdown_countdown(self, seconds=60):
        win = self.present_main()
        dialog = Adw.AlertDialog(heading="Shutting Down", body=f"Scheduled downloads are finished. "
                                 f"The computer will shut down in {seconds} seconds.")
        dialog.add_response("cancel", "Cancel Shutdown")
        dialog.add_response("now", "Shut Down Now")
        dialog.set_response_appearance("now", Adw.ResponseAppearance.DESTRUCTIVE)
        left = [seconds]

        def tick():
            left[0] -= 1
            if left[0] <= 0:
                self._shutdown_timer = 0
                dialog.force_close()
                self._power_off()
                return False
            dialog.set_body(f"Scheduled downloads are finished. The computer will shut down in {left[0]} seconds.")
            return True

        def on_response(_d, response):
            if self._shutdown_timer:
                GLib.source_remove(self._shutdown_timer)
                self._shutdown_timer = 0
            if response == "now":
                self._power_off()

        dialog.connect("response", on_response)
        self._shutdown_timer = GLib.timeout_add_seconds(1, tick)
        dialog.present(win)

    def _power_off(self):
        self.manager.shutdown()
        if WINDOWS:
            cmd, kw = ["shutdown", "/s", "/t", "0"], {"creationflags": subprocess.CREATE_NO_WINDOW}
        elif MACOS:
            cmd, kw = ["osascript", "-e", 'tell application "System Events" to shut down'], {}
        else:
            cmd, kw = ["systemctl", "poweroff"], {}
        try:
            subprocess.run(cmd, check=True, timeout=30, **kw)
        except (OSError, subprocess.SubprocessError):
            self._notify("schedule", "Couldn't shut down", "Your system didn't allow Tondar to power off.")

    def notify_background(self):
        self._notify("background", "Tondar is still running",
                     "Downloads continue in the background. Click the Tondar icon in the notification area "
                     "(or open Tondar again) to see them.")

    def _find(self, item_id):
        return next((i for i in self.manager.items if i.id == item_id), None)

    def _open_item(self, _a, param):
        item = self._find(param.get_string())
        if item and item.status == COMPLETED and os.path.exists(item.open_path):
            open_uri(item.open_path)

    def _open_item_folder(self, _a, param):
        item = self._find(param.get_string())
        if item and item.kind == "site" and os.path.isdir(item.path):
            open_uri(item.path)
        elif item:
            open_folder(item.path if os.path.exists(item.path) else item.folder)

    # --- misc actions ---------------------------------------------------------------------------
    def _clear_completed(self):
        self.manager.remove_many([i for i in self.manager.items if i.status == COMPLETED])

    def _open_ytdlp(self):
        dialog = PreferencesDialog(self)
        dialog.present(self.present_main())
        dialog._update_ytdlp()

    def _about(self):
        about = Adw.AboutDialog(
            application_name="Tondar", application_icon=APP_ID, version=VERSION,
            comments="Fast download manager with browser integration",
            license_type=Gtk.License.GPL_3_0, developer_name="Tondar",
        )
        about.present(self.present_main())

    def quit_app(self):
        if self.tray:
            self.tray.remove()
            self.tray = None
        self.manager.shutdown()
        self.quit()


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    if (WINDOWS or MACOS) and not ipc.acquire_instance(argv[1:]):
        return 0  # an instance is already running (or starting) and took over
    return App().run(argv)


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

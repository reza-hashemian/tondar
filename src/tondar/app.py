import base64
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, VERSION, ipc  # noqa: E402
from .core import COMPLETED, Item, Manager  # noqa: E402
from .dialogs import AddWindow, BrowserDialog, PreferencesDialog  # noqa: E402
from .util import WINDOWS, looks_like_media_page, sanitize_filename, unique_path  # noqa: E402
from .window import MainWindow, open_folder, open_uri  # noqa: E402


class App(Adw.Application):
    def __init__(self):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if WINDOWS:  # no D-Bus: single instance is handled by ipc.py
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.manager = None
        self.window = None
        GLib.set_application_name("Tondar")

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.manager = Manager(lambda fn, *a: GLib.idle_add(fn, *a))
        self.manager.on_finished.append(self._on_finished)
        self.manager.on_schedule_started.append(self._on_schedule_started)
        self.manager.on_schedule_done.append(self._on_schedule_done)
        self._shutdown_timer = 0
        # Stay alive without windows so the browser extension can always reach us.
        self.hold()
        if WINDOWS:
            ipc.serve(lambda args: GLib.idle_add(self.handle_args, args))

        for name, cb, accels in [
            ("add", lambda *_: self.open_add_dialog({}), ["<Primary>n"]),
            ("start-all", lambda *_: self.manager.start_all(), []),
            ("pause-all", lambda *_: self.manager.pause_all(), []),
            ("clear-completed", lambda *_: self._clear_completed(), []),
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

        for name, cb in [("open-item", self._open_item), ("open-item-folder", self._open_item_folder)]:
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", cb)
            self.add_action(action)

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

    def open_add_dialog(self, request):
        AddWindow(self, request).present()
        return False

    def handle_request(self, req):
        """A link sent from the browser extension (or the command line)."""
        url = (req.get("url") or "").strip()
        if not url:
            return
        media = req.get("kind") == "media" or looks_like_media_page(url)
        if self.manager.settings["confirm_browser"] or media:  # videos always need a quality choice
            self.open_add_dialog(req)
            return
        m = self.manager
        name = sanitize_filename(req.get("filename") or "", "")
        item = Item(
            url=url, kind="http", referer=req.get("referer", ""), user_agent=req.get("user_agent", ""),
            cookies=req.get("cookies", []), page_url=req.get("page_url", ""),
            max_segments=int(m.settings["segments"]), size=int(req.get("size") or -1),
        )
        item.folder = m.folder_for(name or url)
        if name:
            item.filename = unique_path(item.folder, name, m.taken_paths())
        m.add(item, start=True)
        self._notify("download-added", "Download started", item.display_name)

    # --- periodic update --------------------------------------------------------------------
    def _tick(self):
        self.manager.tick()
        if self.window and self.window.get_visible():
            self.window.refresh()
        return True

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
        self._notify(f"done-{item.id}", "Download complete", item.display_name, item)

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
        else:
            cmd, kw = ["systemctl", "poweroff"], {}
        try:
            subprocess.run(cmd, check=True, timeout=30, **kw)
        except (OSError, subprocess.SubprocessError):
            self._notify("schedule", "Couldn't shut down", "Your system didn't allow Tondar to power off.")

    def notify_background(self):
        self._notify("background", "Tondar is still running",
                     "Downloads continue in the background. Open Tondar again to see them.")

    def _find(self, item_id):
        return next((i for i in self.manager.items if i.id == item_id), None)

    def _open_item(self, _a, param):
        item = self._find(param.get_string())
        if item and item.status == COMPLETED and os.path.exists(item.path):
            open_uri(item.path)

    def _open_item_folder(self, _a, param):
        item = self._find(param.get_string())
        if item:
            open_folder(item.path if os.path.exists(item.path) else item.folder)

    # --- misc actions ---------------------------------------------------------------------------
    def _clear_completed(self):
        for item in [i for i in self.manager.items if i.status == COMPLETED]:
            self.manager.remove(item, False)

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
        self.manager.shutdown()
        self.quit()


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    if WINDOWS and ipc.forward(argv[1:]):
        return 0  # an instance is already running and took over
    return App().run(argv)

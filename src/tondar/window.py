import os
import time

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .core import COMPLETED, DOWNLOADING, ERROR, PAUSED, PAUSING, QUEUED
from .util import CATEGORY_ICONS, human_size, human_time

FILTERS = [
    ("all", "All Downloads", "folder-download-symbolic"),
    ("active", "Downloading", "network-receive-symbolic"),
    ("unfinished", "Unfinished", "content-loading-symbolic"),
    ("completed", "Completed", "object-select-symbolic"),
    ("scheduled", "Scheduled", "alarm-symbolic"),
    (None, None, None),
    ("Video", "Video", "video-x-generic-symbolic"),
    ("Music", "Music", "audio-x-generic-symbolic"),
    ("Compressed", "Compressed", "package-x-generic-symbolic"),
    ("Documents", "Documents", "x-office-document-symbolic"),
    ("Programs", "Programs", "application-x-executable-symbolic"),
    ("Other", "Other", "text-x-generic-symbolic"),
]

ROW_MENU = """
<interface>
  <menu id="menu">
    <section>
      <item><attribute name="label">Open</attribute><attribute name="action">row.open</attribute></item>
      <item><attribute name="label">Open Folder</attribute><attribute name="action">row.open-folder</attribute></item>
    </section>
    <section>
      <item><attribute name="label">Copy Address</attribute><attribute name="action">row.copy-url</attribute></item>
      <item><attribute name="label">Refresh Download Address…</attribute><attribute name="action">row.change-url</attribute></item>
      <item><attribute name="label">Download Again</attribute><attribute name="action">row.restart</attribute></item>
    </section>
    <section>
      <item><attribute name="label">Add to Schedule</attribute><attribute name="action">row.schedule</attribute></item>
      <item><attribute name="label">Remove from Schedule</attribute><attribute name="action">row.unschedule</attribute></item>
    </section>
    <section>
      <item><attribute name="label">Remove From List</attribute><attribute name="action">row.remove</attribute></item>
      <item><attribute name="label">Delete File</attribute><attribute name="action">row.delete</attribute></item>
    </section>
  </menu>
</interface>
"""


def open_uri(path, parent=None):
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
    launcher.launch(parent, None, None)


def open_folder(path, parent=None):
    if os.path.isfile(path):
        Gtk.FileLauncher.new(Gio.File.new_for_path(path)).open_containing_folder(parent, None, None)
    else:
        open_uri(os.path.dirname(path) if not os.path.isdir(path) else path, parent)


class DownloadRow(Gtk.ListBoxRow):
    def __init__(self, win, item):
        super().__init__()
        self.win = win
        self.item = item

        box = Gtk.Box(spacing=12, margin_top=10, margin_bottom=10, margin_start=12, margin_end=8)
        self.icon = Gtk.Image(pixel_size=36, valign=Gtk.Align.CENTER)
        box.append(self.icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, hexpand=True, valign=Gtk.Align.CENTER)
        self.name = Gtk.Label(xalign=0, ellipsize=3)  # Pango.EllipsizeMode.MIDDLE
        self.name.add_css_class("heading")
        self.bar = Gtk.ProgressBar()
        self.info = Gtk.Label(xalign=0, ellipsize=3)
        self.info.add_css_class("caption")
        self.info.add_css_class("dim-label")
        text.append(self.name)
        text.append(self.bar)
        text.append(self.info)
        box.append(text)

        self.toggle = Gtk.Button(valign=Gtk.Align.CENTER)
        self.toggle.add_css_class("flat")
        self.toggle.add_css_class("circular")
        self.toggle.connect("clicked", self._on_toggle)
        box.append(self.toggle)

        folder = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Open Folder")
        folder.add_css_class("flat")
        folder.add_css_class("circular")
        folder.connect("clicked", lambda *_: self._open_folder())
        box.append(folder)

        menu_model = Gtk.Builder.new_from_string(ROW_MENU, -1).get_object("menu")
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu_model, valign=Gtk.Align.CENTER)
        more.add_css_class("flat")
        more.add_css_class("circular")
        box.append(more)

        self.popover = Gtk.PopoverMenu(menu_model=menu_model, has_arrow=False)
        self.popover.set_parent(box)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_right_click)
        self.add_controller(click)

        group = Gio.SimpleActionGroup()
        for name, cb in [
            ("open", self._open), ("open-folder", self._open_folder), ("copy-url", self._copy_url),
            ("change-url", self._change_url), ("restart", self._restart),
            ("schedule", lambda: self._set_scheduled(True)), ("unschedule", lambda: self._set_scheduled(False)),
            ("remove", lambda: self.win.remove_item(item, False)),
            ("delete", lambda: self.win.remove_item(item, True)),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(action)
        self.actions = group
        self.insert_action_group("row", group)

        self.set_child(box)
        self._state = None
        self.update()

    def _on_right_click(self, gesture, _n, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def update(self):
        it = self.item
        sched = self.win.manager.settings
        state = (it.status, it.done, it.size, round(it.speed), it.filename, it.title, it.error, it.scheduled,
                 sched["schedule_enabled"], sched["schedule_start"])
        if state == self._state:
            return
        self._state = state
        self.name.set_label(it.display_name)
        self.name.set_tooltip_text(it.url)
        self.icon.set_from_icon_name(CATEGORY_ICONS.get(it.category, "text-x-generic"))
        self.bar.set_fraction(it.progress)
        self.bar.set_visible(it.status != COMPLETED)
        self.info.remove_css_class("error")

        size = human_size(it.size) if it.size >= 0 else "unknown size"
        if it.status == DOWNLOADING:
            if it.size < 0 and it.done == 0:
                info = "Connecting…"
                self.bar.pulse()
            else:
                info = f"{human_size(it.done)} of {size}  ·  {human_size(it.speed)}/s"
                if it.eta is not None:
                    info += f"  ·  {human_time(it.eta)} left"
        elif it.status == QUEUED:
            info = "Waiting in queue"
        elif it.status == PAUSING:
            info = "Pausing…"
        elif it.status == PAUSED and it.scheduled:
            info = f"Scheduled  ·  starts at {sched['schedule_start']}" if sched["schedule_enabled"] \
                else "Scheduled  ·  scheduler is off (Preferences → Scheduler)"
            if it.done:
                info += f"  ·  {human_size(it.done)} of {size}"
        elif it.status == PAUSED:
            info = f"Paused  ·  {human_size(it.done)} of {size}" if it.done else "Not started"
            if it.done and it.kind == "http" and not it.resumable:
                info += "  ·  server can't resume, will restart"
        elif it.status == COMPLETED:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(it.finished or it.created))
            info = f"{human_size(it.size)}  ·  {when}"
        else:
            info = f"Failed: {it.error}"
            self.info.add_css_class("error")
        self.info.set_label(info)

        running = it.status in (DOWNLOADING, QUEUED)
        self.toggle.set_visible(it.status not in (COMPLETED, PAUSING))
        self.toggle.set_icon_name("media-playback-pause-symbolic" if running else (
            "view-refresh-symbolic" if it.status == ERROR else "media-playback-start-symbolic"))
        self.toggle.set_tooltip_text("Pause" if running else ("Retry" if it.status == ERROR else "Resume"))
        done = it.status == COMPLETED
        self.actions.lookup_action("open").set_enabled(done)
        self.actions.lookup_action("schedule").set_enabled(not done and not it.scheduled)
        self.actions.lookup_action("unschedule").set_enabled(it.scheduled)
        self.actions.lookup_action("change-url").set_enabled(not done and it.status not in (DOWNLOADING, PAUSING))

    def _on_toggle(self, _btn):
        if self.item.status in (DOWNLOADING, QUEUED):
            self.win.manager.pause(self.item)
        else:
            self.win.manager.start(self.item)
        self.update()

    def _open(self):
        if self.item.status == COMPLETED and os.path.exists(self.item.path):
            open_uri(self.item.path, self.win)
        elif self.item.status == COMPLETED:
            self.win.toast("File was moved or deleted")

    def _open_folder(self):
        it = self.item
        if it.filename and os.path.exists(it.path):
            open_folder(it.path, self.win)
        elif it.folder and os.path.isdir(it.folder):
            open_uri(it.folder, self.win)
        else:
            self.win.toast("Folder does not exist yet")

    def _copy_url(self):
        self.get_clipboard().set(self.item.url)
        self.win.toast("Address copied")

    def _restart(self):
        it = self.item
        if it.status in (DOWNLOADING, QUEUED, PAUSING):
            self.win.toast("Pause the download first")
            return
        if it.kind == "http" and it.filename:
            try:
                os.unlink(it.path + ".part")
            except OSError:
                pass
        it.done, it.segments, it.size = 0, [], -1
        if it.kind == "media":
            it.filename = ""
        it.status = PAUSED
        self.win.manager.start(it)
        self.update()

    def _set_scheduled(self, value):
        self.item.scheduled = value
        m = self.win.manager
        if value and self.item.status in (QUEUED, DOWNLOADING):
            m.pause(self.item)
        m.changed()
        self.update()
        if value and not m.settings["schedule_enabled"]:
            self.win.toast("Added — turn on the scheduler in Preferences → Scheduler")

    def _change_url(self):
        dialog = Adw.AlertDialog(
            heading="Refresh Download Address",
            body="If the link has expired, paste a fresh link to the same file. The download continues where it stopped.",
        )
        entry = Gtk.Entry(text=self.item.url, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Update")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def on_response(_d, response):
            url = entry.get_text().strip()
            if response == "ok" and url:
                self.item.url = url
                self.win.manager.changed()
                self.win.manager.start(self.item)
                self.update()

        dialog.connect("response", on_response)
        dialog.present(self.win)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Tondar", default_width=1000, default_height=640)
        self.app = app
        self.manager = app.manager
        self.rows = {}
        self.filter = "all"
        self.search = ""

        self.split = Adw.OverlaySplitView(min_sidebar_width=200, max_sidebar_width=240)

        # Sidebar
        side = Adw.ToolbarView()
        side_header = Adw.HeaderBar(show_title=False)
        side.add_top_bar(side_header)
        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.add_css_class("navigation-sidebar")
        divide = False
        for key, label, icon in FILTERS:
            if key is None:
                divide = True
                continue
            row = Gtk.ListBoxRow()
            if divide:
                row.set_header(Gtk.Separator(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6))
                divide = False
            row.key = key
            b = Gtk.Box(spacing=12)
            b.append(Gtk.Image(icon_name=icon))
            b.append(Gtk.Label(label=label, xalign=0))
            row.set_child(b)
            self.sidebar.append(row)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))
        self.sidebar.connect("row-selected", self._on_filter)
        side.set_content(Gtk.ScrolledWindow(child=self.sidebar, vexpand=True))
        self.split.set_sidebar(side)

        # Content
        content = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", visible=False, tooltip_text="Categories")
        self.split.bind_property("show-sidebar", self.sidebar_btn, "active", 2 | 1)  # SYNC_CREATE | BIDIRECTIONAL
        header.pack_start(self.sidebar_btn)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Download (Ctrl+N)", action_name="app.add")
        add.add_css_class("suggested-action")
        header.pack_start(add)
        header.pack_start(Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Resume All", action_name="app.start-all"))
        header.pack_start(Gtk.Button(icon_name="media-playback-pause-symbolic", tooltip_text="Pause All", action_name="app.pause-all"))

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search downloads", width_chars=24)
        self.search_entry.connect("search-changed", self._on_search)
        header.set_title_widget(self.search_entry)

        menu = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("Add Download…", "app.add")
        s1.append("Remove Completed", "app.clear-completed")
        s2 = Gio.Menu()
        s2.append("Preferences", "app.preferences")
        s2.append("Scheduler", "app.scheduler")
        s2.append("Proxy", "app.proxy")
        s2.append("Browser Integration", "app.browser")
        s2.append("Install / Update yt-dlp", "app.ytdlp")
        s3 = Gio.Menu()
        s3.append("About Tondar", "app.about")
        s3.append("Quit", "app.quit")
        for s in (s1, s2, s3):
            menu.append_section(None, s)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True))
        content.add_top_bar(header)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
        self.list.add_css_class("boxed-list")
        self.list.set_filter_func(self._filter_row)
        self.list.set_sort_func(lambda a, b: (b.item.created > a.item.created) - (b.item.created < a.item.created))
        self.list.connect("row-activated", lambda _l, row: row._open())
        clamp = Adw.Clamp(maximum_size=1100, child=self.list, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        scrolled = Gtk.ScrolledWindow(child=clamp, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)

        self.empty = Adw.StatusPage(
            icon_name="folder-download-symbolic", title="No Downloads",
            description="Press + or Ctrl+N to add a link, or click the download button that appears on videos in your browser.",
        )
        self.stack = Gtk.Stack()
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(self.empty, "empty")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        content.set_content(self.toasts)

        status = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        self.status_label = Gtk.Label(xalign=0, hexpand=True)
        self.status_label.add_css_class("caption")
        self.status_label.add_css_class("dim-label")
        status.append(self.status_label)
        content.add_bottom_bar(status)
        self.split.set_content(content)
        self.set_content(self.split)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.add_setter(self.sidebar_btn, "visible", True)
        self.add_breakpoint(bp)

        for item in self.manager.items:
            self._add_row(item)
        self.manager.on_added.append(self._on_added)
        self.manager.on_removed.append(self._on_removed)
        self._refresh_empty()

        drop = Gtk.DropTarget.new(str, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self.connect("close-request", self._on_close)

    # --- list management ------------------------------------------------------------
    def _add_row(self, item):
        row = DownloadRow(self, item)
        self.rows[item.id] = row
        self.list.append(row)

    def _on_added(self, item):
        self._add_row(item)
        self._refresh_empty()

    def _on_removed(self, item):
        row = self.rows.pop(item.id, None)
        if row:
            self.list.remove(row)
        self._refresh_empty()

    def _refresh_empty(self):
        visible = any(self._matches(r.item) for r in self.rows.values())
        self.stack.set_visible_child_name("list" if visible else "empty")

    def _matches(self, item):
        f = self.filter
        if f == "active" and item.status not in (DOWNLOADING, QUEUED, PAUSING):
            return False
        if f == "unfinished" and item.status == COMPLETED:
            return False
        if f == "completed" and item.status != COMPLETED:
            return False
        if f == "scheduled" and (not item.scheduled or item.status == COMPLETED):
            return False
        if f not in ("all", "active", "unfinished", "completed", "scheduled") and item.category != f:
            return False
        if self.search:
            return self.search in (item.display_name + " " + item.url).lower()
        return True

    def _filter_row(self, row):
        return self._matches(row.item)

    def _on_filter(self, _box, row):
        if row is None:
            return
        self.filter = row.key
        self.list.invalidate_filter()
        self._refresh_empty()
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def _on_search(self, entry):
        self.search = entry.get_text().strip().lower()
        self.list.invalidate_filter()
        self._refresh_empty()

    def refresh(self):
        for row in self.rows.values():
            row.update()
        if self.filter in ("active", "unfinished", "completed", "scheduled"):
            self.list.invalidate_filter()
            self._refresh_empty()
        active = sum(1 for i in self.manager.items if i.status == DOWNLOADING)
        queued = sum(1 for i in self.manager.items if i.status == QUEUED)
        text = f"{len(self.manager.items)} downloads"
        if active:
            text += f"  ·  {active} active  ·  {human_size(self.manager.total_speed())}/s"
        if queued:
            text += f"  ·  {queued} queued"
        st = self.manager.settings
        if st["schedule_enabled"]:
            text += f"  ·  scheduler on ({st['schedule_start']}{'–' + st['schedule_stop'] if st['schedule_stop'] else ''})"
        if st["proxy_mode"] == "manual" and st["proxy_host"]:
            text += f"  ·  proxy {st['proxy_host']}:{st['proxy_port']}"
        limit = int(self.manager.settings["speed_limit_kb"])
        if limit:
            text += f"  ·  limited to {human_size(limit * 1024)}/s"
        self.status_label.set_label(text)

    def remove_item(self, item, delete_file):
        if not delete_file:
            self.manager.remove(item, False)
            self.toast(f"Removed “{item.display_name}”")
            return
        dialog = Adw.AlertDialog(heading="Delete File?", body=f"“{item.display_name}” will be permanently deleted from disk.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, r: r == "delete" and self.manager.remove(item, True))
        dialog.present(self)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def _on_drop(self, _target, value, _x, _y):
        url = value.strip().splitlines()[0] if value else ""
        if "://" in url:
            GLib.idle_add(self.app.open_add_dialog, {"url": url})
            return True
        return False

    def _on_close(self, _win):
        if self.manager.settings["background"]:
            self.set_visible(False)
            if self.manager.active_count():
                self.app.notify_background()
            return True
        self.app.quit_app()
        return True

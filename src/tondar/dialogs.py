import os
import shutil
import sys
import threading
import time

from gi.repository import Adw, Gio, GLib, Gtk

from . import APP_ID
from .core import Item
from .http_task import probe
from .media import (
    PLAYLIST_HINT, YTDLP_URL, install_ytdlp, is_playlist, playlist_choices, playlist_entries, probe_media,
    ffmpeg_available, quality_choices, ytdlp_command, ytdlp_version,
)
from .net import display_proxy, test_proxy
from .util import MACOS, WINDOWS, app_dir, clean_page_title, human_size, human_time, looks_like_media_page, sanitize_filename
from .window import show_in_folder

MODES = ["File", "Video / stream (yt-dlp)"]


class AddWindow(Adw.Window):
    """The "new download" window (also shown for links sent from the browser)."""

    def __init__(self, app, request):
        super().__init__(application=app, title="New Download", default_width=580, default_height=560)
        self.app = app
        self.manager = app.manager
        self.request = request
        self._generation = 0
        self._probe_timer = 0
        self._name_edited = False
        self._setting_name = False
        self._folder_fixed = False
        self._choices = []
        self._probe_size = -1
        self._playlist = None  # (entries, check buttons) when a playlist was found
        self._videos_row = None

        if app.window and app.window.get_visible():
            self.set_transient_for(app.window)
            self.set_modal(True)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())

        page = Adw.PreferencesPage()
        g1 = Adw.PreferencesGroup()
        self.url_row = Adw.EntryRow(title="Address")
        self.url_row.connect("changed", self._on_url_changed)
        g1.add(self.url_row)

        self.mode_row = Adw.ComboRow(title="Type", model=Gtk.StringList.new(MODES))
        self.mode_row.connect("notify::selected", lambda *_: self._on_mode_changed())
        g1.add(self.mode_row)

        self.quality_row = Adw.ComboRow(title="Quality", model=Gtk.StringList.new(["Best quality"]), visible=False)
        self.quality_row.connect("notify::selected", lambda *_: self._update_folder_row())
        g1.add(self.quality_row)

        self.info_row = Adw.ActionRow(title="Details", subtitle="Enter a link")
        self.spinner = Adw.Spinner(visible=False)
        self.info_row.add_suffix(self.spinner)
        g1.add(self.info_row)

        self.playlist_row = Adw.SwitchRow(
            title="Download entire playlist", subtitle="Otherwise only the video in the link", active=True, visible=False)
        self.playlist_row.connect("notify::active", lambda *_: self._start_probe())
        g1.add(self.playlist_row)
        self.g1 = g1
        page.add(g1)

        g2 = Adw.PreferencesGroup()
        self.name_row = Adw.EntryRow(title="File name")
        self.name_row.connect("changed", self._on_name_changed)
        g2.add(self.name_row)

        self.folder_row = Adw.ActionRow(title="Save to")
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Choose Folder")
        pick.add_css_class("flat")
        pick.connect("clicked", self._pick_folder)
        self.folder_row.add_suffix(pick)
        self.folder_row.set_activatable_widget(pick)
        g2.add(self.folder_row)

        self.seg_row = Adw.SpinRow.new_with_range(1, 32, 1)
        self.seg_row.set_title("Connections")
        self.seg_row.set_subtitle("More connections is usually faster")
        self.seg_row.set_value(int(self.manager.settings["segments"]))
        g2.add(self.seg_row)
        page.add(g2)
        view.set_content(page)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        later = Gtk.Button(label="Download Later")
        later.connect("clicked", lambda *_: self._submit(False))
        sched = Gtk.Button(tooltip_text="Start automatically at the scheduled time (Preferences → Scheduler)")
        sched.set_child(Adw.ButtonContent(icon_name="alarm-symbolic", label="Schedule"))
        sched.connect("clicked", lambda *_: self._submit(False, scheduled=True))
        self.start_btn = Gtk.Button(label="Start Download")
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", lambda *_: self._submit(True))
        buttons.append(later)
        buttons.append(sched)
        buttons.append(self.start_btn)
        view.add_bottom_bar(buttons)
        self.set_content(view)
        self.set_default_widget(self.start_btn)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"), Gtk.CallbackAction.new(lambda *_: self.close())))
        self.add_controller(esc)

        self._folder = self.manager.settings["folder"]
        self._update_folder_row()

        url = request.get("url", "")
        if request.get("kind") == "media" or looks_like_media_page(url):
            self.mode_row.set_selected(1)
        if request.get("filename"):
            self._set_name(request["filename"])
            self._name_edited = True
        elif request.get("title") and self.is_media:
            self._set_name(sanitize_filename(clean_page_title(request["title"])))
        self.url_row.set_text(url)
        if not url:
            self._paste_from_clipboard()

    @property
    def is_media(self):
        return self.mode_row.get_selected() == 1

    # --- helpers ----------------------------------------------------------------------
    def _paste_from_clipboard(self):
        clipboard = self.get_clipboard()

        def done(cb, res):
            try:
                text = (cb.read_text_finish(res) or "").strip()
            except GLib.Error:
                return
            if text.startswith(("http://", "https://", "ftp://")) and " " not in text and not self.url_row.get_text():
                self.url_row.set_text(text)

        clipboard.read_text_async(None, done)

    def _set_name(self, name):
        self._setting_name = True
        self.name_row.set_text(name)
        self._setting_name = False
        self._update_folder_row()

    def _on_name_changed(self, _row):
        if not self._setting_name:
            self._name_edited = True
        self._update_folder_row()

    def _target_folder(self):
        if self._folder_fixed:
            return self._folder
        name = self.name_row.get_text()
        audio = self.is_media and self._selected_format().startswith("ba")
        return self.manager.folder_for(name, "media" if self.is_media else "http", audio)

    def _save_folder(self):
        """Where files go; playlists get their own sub-folder."""
        folder = self._target_folder()
        if self._playlist:
            folder = os.path.join(folder, sanitize_filename(self.name_row.get_text().strip(), "Playlist"))
        return folder

    def _update_folder_row(self):
        self.folder_row.set_subtitle(self._save_folder().replace(os.path.expanduser("~"), "~", 1))

    def _pick_folder(self, _btn):
        dialog = Gtk.FileDialog(title="Save To", initial_folder=Gio.File.new_for_path(self._target_folder()
                                if os.path.isdir(self._target_folder()) else self.manager.settings["folder"]))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self._folder, self._folder_fixed = folder.get_path(), True
            self._update_folder_row()

        dialog.select_folder(self, None, done)

    def _selected_format(self):
        i = self.quality_row.get_selected()
        if self._choices and 0 <= i < len(self._choices):
            return self._choices[i][1]
        return "bv*+ba/b"

    def _base_item(self, url):
        r = self.request
        same = url == r.get("url")
        return Item(
            url=url,
            referer=r.get("referer", "") if same else "",
            user_agent=r.get("user_agent", ""),
            cookies=r.get("cookies", []) if same else [],
            page_url=r.get("page_url", ""),
        )

    # --- probing ------------------------------------------------------------------------
    def _on_url_changed(self, _row):
        if self._probe_timer:
            GLib.source_remove(self._probe_timer)
        self._probe_timer = GLib.timeout_add(600, self._start_probe)

    def _on_mode_changed(self):
        self.quality_row.set_visible(self.is_media)
        self.seg_row.set_title("Connections" if not self.is_media else "Parallel fragments")
        self._update_folder_row()
        self._start_probe()

    def _start_probe(self):
        self._probe_timer = 0
        self._generation += 1
        gen = self._generation
        url = self.url_row.get_text().strip()
        if "://" not in url:
            self.info_row.set_subtitle("Enter a link")
            self.spinner.set_visible(False)
            return False
        item = self._base_item(url)
        self.spinner.set_visible(True)
        media = self.is_media
        if media and not ytdlp_command():
            self.spinner.set_visible(False)
            self.info_row.set_subtitle("yt-dlp is not installed — use the menu: Install / Update yt-dlp")
            return False
        hint = media and bool(PLAYLIST_HINT.search(url))
        self.playlist_row.set_visible(hint)
        want_playlist = hint and self.playlist_row.get_active()
        self.info_row.set_subtitle(
            "Reading the playlist…" if want_playlist else
            "Looking up the video (this can take a few seconds)…" if media else "Checking link…")

        def work():
            try:
                proxy = self.manager.proxy_for(url)
                result = probe_media(item, playlist=want_playlist, proxy=proxy) if media else probe(item, proxy=proxy)
                err = None
            except Exception as e:  # noqa: BLE001
                result, err = None, str(e) or e.__class__.__name__
            GLib.idle_add(self._probe_done, gen, media, result, err)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _probe_done(self, gen, media, result, err):
        if gen != self._generation:
            return False
        self.spinner.set_visible(False)
        if err:
            self.info_row.set_subtitle(f"Couldn't check the link: {err[:200]}")
            return False
        self._clear_playlist()
        if media and is_playlist(result):
            self._show_playlist(result)
        elif media:
            info = result
            self._choices = quality_choices(info)
            labels = [f"{label}  ·  ~{human_size(size)}" if size else label for label, _, size in self._choices]
            self.quality_row.set_model(Gtk.StringList.new(labels))
            self.quality_row.set_selected(0)
            parts = [info.get("extractor_key") or ""]
            if info.get("duration"):
                parts.append(human_time(info["duration"]))
            if info.get("uploader"):
                parts.append(info["uploader"])
            self.info_row.set_subtitle("  ·  ".join(p for p in parts if p) or "Ready")
            if not self._name_edited and info.get("title"):
                self._set_name(sanitize_filename(info["title"]))
        else:
            size, ranges, name, ctype = result
            self._probe_size = size
            if ctype == "text/html" and not self.request.get("filename"):
                self.info_row.set_subtitle("This link is a web page, not a file — switched to video mode")
                self.mode_row.set_selected(1)
                return False
            text = human_size(size) if size >= 0 else "Unknown size"
            text += "  ·  resumable" if ranges else "  ·  server doesn't support resume"
            self.info_row.set_subtitle(f"{text}  ·  {ctype}")
            if not self._name_edited and name:
                self._set_name(name)
        return False

    # --- playlists ------------------------------------------------------------------------------
    def _clear_playlist(self):
        self._playlist = None
        if self._videos_row:
            self.g1.remove(self._videos_row)
            self._videos_row = None
        self.name_row.set_title("File name")
        self.start_btn.set_label("Start Download")
        self.start_btn.set_sensitive(True)

    def _show_playlist(self, info):
        entries = playlist_entries(info)
        if not entries:
            self.info_row.set_subtitle("No videos found in this list. For a channel, open its “Videos” tab or a playlist.")
            return
        self._choices = playlist_choices()
        self.quality_row.set_model(Gtk.StringList.new([c[0] for c in self._choices]))
        self.quality_row.set_selected(0)
        parts = ["Playlist", f"{len(entries)} videos", info.get("uploader") or info.get("channel") or ""]
        self.info_row.set_subtitle("  ·  ".join(p for p in parts if p))

        row = Adw.ExpanderRow(title="Videos", expanded=len(entries) <= 8)
        toggle = Gtk.Button(label="Select None", valign=Gtk.Align.CENTER)
        toggle.add_css_class("flat")
        row.add_suffix(toggle)
        checks = []
        for i, (_url, title, duration) in enumerate(entries, 1):
            check = Gtk.CheckButton(active=not title.startswith(("[Private", "[Deleted")), valign=Gtk.Align.CENTER)
            check.connect("toggled", lambda *_: self._update_selection())
            video = Adw.ActionRow(title=f"{i}. {title}", use_markup=False, subtitle=human_time(duration) if duration else "")
            video.add_prefix(check)
            video.set_activatable_widget(check)
            row.add_row(video)
            checks.append(check)

        def on_toggle(_b):
            select = not any(c.get_active() for c in checks)
            for c in checks:
                c.set_active(select)

        toggle.connect("clicked", on_toggle)
        self._toggle_btn = toggle
        self._videos_row = row
        self._playlist = (entries, checks)
        self.g1.add(row)
        self.name_row.set_title("Playlist folder name")
        if not self._name_edited:
            self._set_name(sanitize_filename(info.get("title") or "Playlist"))
        self._update_selection()

    def _update_selection(self):
        entries, checks = self._playlist
        n = sum(c.get_active() for c in checks)
        self._videos_row.set_subtitle(f"{n} of {len(entries)} selected")
        self._toggle_btn.set_label("Select None" if n else "Select All")
        self.start_btn.set_label(f"Download {n} Videos" if n != 1 else "Download 1 Video")
        self.start_btn.set_sensitive(n > 0)
        self._update_folder_row()

    def _submit_playlist(self, start, scheduled=False):
        entries, checks = self._playlist
        folder = self._save_folder()
        fmt = self._selected_format()
        pad = len(str(len(entries)))
        now = time.time()
        r = self.request
        selected = [(i, e) for i, (e, c) in enumerate(zip(entries, checks), 1) if c.get_active()]
        for n, (i, (url, title, _d)) in enumerate(selected):
            item = Item(
                url=url, kind="media", folder=folder, media_format=fmt,
                title=sanitize_filename(f"{i:0{pad}} - {title}"),
                max_segments=int(self.seg_row.get_value()),
                user_agent=r.get("user_agent", ""), cookies=r.get("cookies", []),
                page_url=self.url_row.get_text().strip(),
                created=now - n * 0.001,  # keeps playlist order in the newest-first list
                scheduled=scheduled,
            )
            self.manager.add(item, start=start)
        if self.app.window and self.app.window.get_visible():
            self.app.window.toast(f"{'Scheduled' if scheduled else 'Added'} {len(selected)} videos from “{os.path.basename(folder)}”")
        self.close()

    # --- submit ------------------------------------------------------------------------------
    def _submit(self, start, scheduled=False):
        url = self.url_row.get_text().strip()
        if "://" not in url:
            self.url_row.add_css_class("error")
            return
        if self._playlist:
            self._submit_playlist(start, scheduled)
            return
        item = self._base_item(url)
        item.folder = self._target_folder()
        item.max_segments = int(self.seg_row.get_value())
        name = sanitize_filename(self.name_row.get_text().strip(), "")
        if self.is_media:
            item.kind = "media"
            item.title = name
            item.media_format = self._selected_format()
        else:
            item.filename = name
            item.size = self._probe_size
        item.scheduled = scheduled
        self.manager.add(item, start=start)
        if self.app.window and self.app.window.get_visible():
            self.app.window.toast(f"{'Scheduled' if scheduled else 'Added'} “{item.display_name}”")
        if scheduled and not self.manager.settings["schedule_enabled"]:
            self.app.window and self.app.window.toast("Turn on the scheduler in Preferences → Scheduler")
        self.close()


PROXY_MODES = [("system", "System settings"), ("none", "No proxy"), ("manual", "Manual")]
DONE_ACTIONS = [("nothing", "Do nothing"), ("quit", "Quit Tondar"), ("shutdown", "Shut down the computer")]
# Iranian week order; values are Python weekdays (Monday = 0)
WEEK = [("Sat", 5), ("Sun", 6), ("Mon", 0), ("Tue", 1), ("Wed", 2), ("Thu", 3), ("Fri", 4)]


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, app, page_name=None):
        super().__init__(title="Preferences")
        self.app = app
        s = app.manager.settings
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic", name="general")

        g = Adw.PreferencesGroup(title="Downloads")
        self.folder_row = Adw.ActionRow(title="Download folder", subtitle=s["folder"])
        btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        btn.add_css_class("flat")
        btn.connect("clicked", self._pick_folder)
        self.folder_row.add_suffix(btn)
        self.folder_row.set_activatable_widget(btn)
        g.add(self.folder_row)
        g.add(self._switch("categorize", "Sort into sub-folders", "Video, Music, Compressed, Documents, Programs…"))
        g.add(self._spin("max_active", "Simultaneous downloads", 1, 20))
        g.add(self._spin("segments", "Connections per download", 1, 32, "Default for new downloads"))
        g.add(self._spin("speed_limit_kb", "Speed limit (KB/s)", 0, 1_000_000, "0 means unlimited", step=50))
        page.add(g)

        g = Adw.PreferencesGroup(title="Behavior")
        g.add(self._switch("background", "Keep running when window is closed",
                           "Needed so the browser extension works without the window open"))
        autostart = self._switch("autostart", "Start on login", "Runs hidden in the background")
        autostart.connect("notify::active", lambda r, _p: set_autostart(r.get_active()))
        g.add(autostart)
        g.add(self._switch("confirm_browser", "Ask before downloading from the browser",
                           "Show the “New Download” window for links sent by the extension"))
        g.add(self._switch("notify", "Notify when a download finishes"))
        page.add(g)

        g = Adw.PreferencesGroup(title="Video downloads", description="Videos from YouTube and most other sites are downloaded with yt-dlp.")
        self.ytdlp_row = Adw.ActionRow(title="yt-dlp", subtitle="Checking…")
        self.ytdlp_btn = Gtk.Button(label="Install / Update", valign=Gtk.Align.CENTER)
        self.ytdlp_btn.connect("clicked", lambda *_: self._update_ytdlp())
        self.ytdlp_row.add_suffix(self.ytdlp_btn)
        g.add(self.ytdlp_row)
        ffmpeg = Adw.ActionRow(title="ffmpeg", subtitle="Installed" if ffmpeg_available()
                               else "Not installed — needed for HD YouTube. Run: sudo apt install ffmpeg")
        g.add(ffmpeg)
        page.add(g)
        self.add(page)
        self.add(self._network_page())
        self.add(self._scheduler_page())
        if page_name:
            self.set_visible_page_name(page_name)

        threading.Thread(target=lambda: GLib.idle_add(self._show_version, ytdlp_version()), daemon=True).start()
        self.connect("closed", lambda *_: app.manager.save_settings())

    # --- Network page -----------------------------------------------------------------------
    def _network_page(self):
        s = self.app.manager.settings
        page = Adw.PreferencesPage(title="Network", icon_name="network-wired-symbolic", name="network")
        g = Adw.PreferencesGroup(
            title="Proxy",
            description="Used for every download, video lookups and yt-dlp updates. "
                        "For a proxy on another computer in your network, enter that computer's IP address "
                        "(for example 192.168.1.10) and make sure the proxy app allows connections from the LAN.")
        modes = [m for m, _ in PROXY_MODES]
        mode_row = Adw.ComboRow(title="Proxy", model=Gtk.StringList.new([label for _, label in PROXY_MODES]))
        mode_row.set_selected(modes.index(s["proxy_mode"]) if s["proxy_mode"] in modes else 0)
        g.add(mode_row)
        page.add(g)

        manual = Adw.PreferencesGroup(title="Manual proxy")
        type_row = Adw.ComboRow(title="Type", model=Gtk.StringList.new(["HTTP / HTTPS", "SOCKS5"]))
        type_row.set_selected(1 if s["proxy_type"] == "socks5" else 0)
        type_row.connect("notify::selected", lambda r, _p: self._set("proxy_type", "socks5" if r.get_selected() else "http"))
        manual.add(type_row)
        host = Adw.EntryRow(title="Address (IP or host name)", text=s["proxy_host"])
        host.connect("changed", lambda r: self._set("proxy_host", r.get_text().strip()))
        manual.add(host)
        manual.add(self._spin("proxy_port", "Port", 1, 65535))
        user = Adw.EntryRow(title="Username (optional)", text=s["proxy_user"])
        user.connect("changed", lambda r: self._set("proxy_user", r.get_text()))
        manual.add(user)
        pwd = Adw.PasswordEntryRow(title="Password (optional)", text=s["proxy_pass"])
        pwd.connect("changed", lambda r: self._set("proxy_pass", r.get_text()))
        manual.add(pwd)
        page.add(manual)

        def on_mode(r, _p):
            self._set("proxy_mode", modes[r.get_selected()])
            manual.set_sensitive(modes[r.get_selected()] == "manual")

        mode_row.connect("notify::selected", on_mode)
        manual.set_sensitive(s["proxy_mode"] == "manual")

        g = Adw.PreferencesGroup()
        self.test_row = Adw.ActionRow(title="Test connection", subtitle="Checks that the internet is reachable with these settings")
        self.test_btn = Gtk.Button(label="Test", valign=Gtk.Align.CENTER)
        self.test_btn.connect("clicked", lambda *_: self._test_proxy())
        self.test_row.add_suffix(self.test_btn)
        g.add(self.test_row)
        page.add(g)
        return page

    def _test_proxy(self):
        proxy = self.app.manager.proxy_for("https://www.google.com/")
        self.test_btn.set_sensitive(False)
        self.test_row.set_subtitle(f"Testing via {display_proxy(proxy)}…")

        def work():
            try:
                text = f"✓ Works — {test_proxy(proxy)} ms via {display_proxy(proxy)}"
            except Exception as e:  # noqa: BLE001
                reason = getattr(e, "reason", None) or e
                text = f"✗ Failed via {display_proxy(proxy)}: {reason}"
            GLib.idle_add(done, text)

        def done(text):
            self.test_btn.set_sensitive(True)
            self.test_row.set_subtitle(text)
            return False

        threading.Thread(target=work, daemon=True).start()

    # --- Scheduler page -------------------------------------------------------------------
    def _scheduler_page(self):
        s = self.app.manager.settings
        page = Adw.PreferencesPage(title="Scheduler", icon_name="alarm-symbolic", name="scheduler")
        g = Adw.PreferencesGroup(
            description="Scheduled downloads start by themselves at the chosen time — handy for night-time internet. "
                        "Add downloads with the “Schedule” button in the New Download window, "
                        "or with “Add to Schedule” in a download's menu. Tondar must be running "
                        "(turn on “Start on login” in General).")
        g.add(self._switch("schedule_enabled", "Enable scheduler", reset_session=True))
        page.add(g)

        times = Adw.PreferencesGroup(title="When")
        times.add(self._time_row("Start at", "schedule_start", s["schedule_start"] or "02:00"))
        has_stop = bool(s["schedule_stop"])
        stop_switch = Adw.SwitchRow(title="Stop at a set time", subtitle="Unfinished downloads pause and continue next time",
                                    active=has_stop)
        stop_row = self._time_row("Stop at", "schedule_stop", s["schedule_stop"] or "07:00")
        stop_row.set_sensitive(has_stop)

        def on_stop(r, _p):
            stop_row.set_sensitive(r.get_active())
            self._set("schedule_stop", stop_row.time_value() if r.get_active() else "")
            self._set("schedule_last", "")

        stop_switch.connect("notify::active", on_stop)
        times.add(stop_switch)
        times.add(stop_row)

        days_row = Adw.ActionRow(title="Days")
        box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        box.add_css_class("linked")
        chosen = set(s["schedule_days"])
        toggles = []

        def on_day(*_):
            self._set("schedule_days", sorted(v for (_, v), t in zip(WEEK, toggles) if t.get_active()))
            self._set("schedule_last", "")

        for label, value in WEEK:
            t = Gtk.ToggleButton(label=label, active=value in chosen)
            t.connect("toggled", on_day)
            toggles.append(t)
            box.append(t)
        days_row.add_suffix(box)
        times.add(days_row)
        page.add(times)

        what = Adw.PreferencesGroup(title="What")
        what.add(self._switch("schedule_all", "Also start all other unfinished downloads",
                              "Otherwise only downloads added to the schedule"))
        actions = [a for a, _ in DONE_ACTIONS]
        done_row = Adw.ComboRow(title="When scheduled downloads finish",
                                model=Gtk.StringList.new([label for _, label in DONE_ACTIONS]))
        done_row.set_selected(actions.index(s["schedule_done_action"]) if s["schedule_done_action"] in actions else 0)
        done_row.connect("notify::selected", lambda r, _p: self._set("schedule_done_action", actions[r.get_selected()]))
        what.add(done_row)
        page.add(what)
        return page

    def _time_row(self, title, key, value):
        row = Adw.ActionRow(title=title)
        try:
            h, m = (int(x) for x in value.split(":"))
        except ValueError:
            h, m = 2, 0
        box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        hs = Gtk.SpinButton.new_with_range(0, 23, 1)
        ms = Gtk.SpinButton.new_with_range(0, 59, 1)
        for spin, v in ((hs, h), (ms, m)):
            spin.set_value(v)
            spin.set_wrap(True)
            spin.set_numeric(True)
            spin.set_width_chars(2)
            spin.connect("output", lambda sp: sp.set_text(f"{int(sp.get_value()):02}") or True)
        box.append(hs)
        box.append(Gtk.Label(label=":"))
        box.append(ms)
        row.add_suffix(box)
        row.time_value = lambda: f"{int(hs.get_value()):02}:{int(ms.get_value()):02}"

        def changed(*_):
            if row.get_sensitive():
                self._set(key, row.time_value())
                self._set("schedule_last", "")

        hs.connect("value-changed", changed)
        ms.connect("value-changed", changed)
        return row

    def _switch(self, key, title, subtitle=None, reset_session=False):
        row = Adw.SwitchRow(title=title, active=bool(self.app.manager.settings[key]))
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::active", lambda r, _p: self._set(key, r.get_active()))
        if reset_session:
            row.connect("notify::active", lambda *_: self._set("schedule_last", ""))
        return row

    def _spin(self, key, title, lo, hi, subtitle=None, step=1):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_value(int(self.app.manager.settings[key]))
        row.connect("notify::value", lambda r, _p: self._set(key, int(r.get_value())))
        return row

    def _set(self, key, value):
        self.app.manager.settings[key] = value
        self.app.manager.apply_settings()

    def _pick_folder(self, _btn):
        def done(d, res):
            try:
                path = d.select_folder_finish(res).get_path()
            except GLib.Error:
                return
            self._set("folder", path)
            self.folder_row.set_subtitle(path)

        Gtk.FileDialog(title="Download Folder").select_folder(self.get_root(), None, done)

    def _show_version(self, version):
        self.ytdlp_row.set_subtitle(f"Version {version}" if version else "Not installed")
        return False

    def _update_ytdlp(self):
        self.ytdlp_btn.set_sensitive(False)
        self.ytdlp_row.set_subtitle("Downloading latest version…")

        def work():
            try:
                version, err = install_ytdlp(self.app.manager.proxy_for(YTDLP_URL)), None
            except Exception as e:  # noqa: BLE001
                version, err = None, str(e)
            GLib.idle_add(done, version, err)

        def done(version, err):
            self.ytdlp_btn.set_sensitive(True)
            self.ytdlp_row.set_subtitle(f"Updated to {version}" if version else f"Failed: {err}")
            return False

        threading.Thread(target=work, daemon=True).start()


def autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", f"{APP_ID}.desktop")


def launch_command():
    exe = shutil.which("tondar")
    if exe:
        return exe
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f"env PYTHONPATH={src} {sys.executable} -m tondar"


def set_autostart(enabled):
    if MACOS:
        from .macos import set_login_item

        set_login_item(enabled)
        return
    if WINDOWS:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, "Tondar", 0, winreg.REG_SZ, f'"{sys.executable}" --background')
            else:
                try:
                    winreg.DeleteValue(key, "Tondar")
                except FileNotFoundError:
                    pass
        return
    path = autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(
                "[Desktop Entry]\nType=Application\nName=Tondar Download Manager\n"
                f"Exec={launch_command()} --background\nIcon={APP_ID}\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
    elif os.path.exists(path):
        os.unlink(path)


def extension_dir():
    for path in (os.path.join(app_dir(), "extension"), "/usr/share/tondar/extension",
                 os.path.join(app_dir(), "..", "Resources", "extension"),  # Tondar.app
                 os.path.join(app_dir(), "build", "extension")):
        if os.path.isdir(os.path.join(path, "chrome")):
            return os.path.realpath(path)
    return None


class BrowserDialog(Adw.Dialog):
    def __init__(self, app):
        super().__init__(title="Browser Integration", content_width=560, content_height=620)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        ext = extension_dir()

        g = Adw.PreferencesGroup(
            title="Google Chrome / Chromium / Brave / Edge",
            description="1. Open chrome://extensions\n2. Turn on “Developer mode” (top right)\n"
                        "3. Click “Load unpacked” and choose the folder below",
        )
        g.add(self._path_row("Extension folder", os.path.join(ext, "chrome") if ext else None, app))
        g.add(self._copy_row("Extensions page", "chrome://extensions", app))
        page.add(g)

        g = Adw.PreferencesGroup(
            title="Firefox (ESR / Developer Edition)",
            description="1. Open about:config and set xpinstall.signatures.required to false\n"
                        "2. Open about:addons → ⚙ → “Install Add-on From File…”\n3. Choose the file below",
        )
        g.add(self._path_row("Add-on file", os.path.join(ext, "tondar-firefox.xpi") if ext else None, app))
        page.add(g)

        g = Adw.PreferencesGroup(
            title="What you get",
            description="• Browser downloads are taken over by Tondar automatically\n"
                        "• A “Download” button appears on videos in web pages\n"
                        "• Right-click any link → “Download with Tondar”\n"
                        "• The toolbar icon lists every video found on the current page",
        )
        page.add(g)
        view.set_content(page)
        self.set_child(view)

    def _path_row(self, title, path, app):
        row = Adw.ActionRow(title=title, subtitle=path or "Not found — build it with tools/build-extension.py",
                            subtitle_selectable=True)
        if path:
            btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Show in Files")
            btn.add_css_class("flat")
            btn.connect("clicked", lambda *_: show_in_folder(path, app.window))
            row.add_suffix(btn)
            row.add_suffix(self._copy_btn(path))
        return row

    def _copy_row(self, title, text, app):
        row = Adw.ActionRow(title=title, subtitle=text)
        row.add_suffix(self._copy_btn(text))
        return row

    def _copy_btn(self, text):
        btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy")
        btn.add_css_class("flat")
        btn.connect("clicked", lambda b: b.get_clipboard().set(text))
        return btn

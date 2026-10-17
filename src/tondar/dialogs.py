import html
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import Adw, Gio, GLib, Gtk

from . import APP_ID
from .core import Item
from .http_task import probe
from .media import (
    PLAYLIST_HINT, YTDLP_URL, audio_selector, container_choices, describe_formats, find_page_media, format_time,
    install_ytdlp, is_playlist, parse_time, playlist_choices, playlist_entries, probe_media, ffmpeg_available,
    quality_choices, ytdlp_command, ytdlp_version, BROWSERS, is_bot_check,
)
from .net import display_proxy, test_proxy
from .util import (
    MACOS, WINDOWS, app_dir, category_for, clean_page_title, human_size, human_time, looks_like_media_page,
    sanitize_filename,
)
from .window import show_in_folder

MODES = ["File", "Video / stream (yt-dlp)"]


class AddWindow(Adw.Window):
    """The "new download" window (also shown for links sent from the browser)."""

    def __init__(self, app, request):
        super().__init__(application=app, title="New Download", default_width=580, default_height=700)
        self.app = app
        self.manager = app.manager
        self.request = request
        self._generation = 0
        self._probe_timer = 0
        self._name_edited = False
        self._setting_name = False
        self._folder_fixed = False
        self._folder_picked = False  # chosen by hand in this window: remembered for the next downloads
        self._folder_reset = False  # "use the default folder" pressed: forget the remembered one
        self._guest = False  # the video was found without logging in (yt-dlp's generic extractor)
        self._links = []  # direct links found in the page when yt-dlp couldn't get the video
        self._choices = []
        self._probe_size = -1
        self._playlist = None  # (entries, check buttons) when a playlist was found
        self._videos_row = None
        self._info = None  # what yt-dlp found out about the video
        self._duration = 0
        self._containers = [("Automatic (best quality)", "")]
        self._want_container = request.get("container") or ""

        if app.window and app.window.get_visible():
            self.set_transient_for(app.window)
            self.set_modal(True)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        # More links sent from the browser while this window is open wait for their turn.
        self.pending_banner = Adw.Banner(button_label="Add All Now")
        self.pending_banner.connect("button-clicked", lambda *_: self.app.add_pending_now())
        view.add_top_bar(self.pending_banner)

        page = Adw.PreferencesPage()
        g1 = Adw.PreferencesGroup()
        self.url_row = Adw.EntryRow(title="Address")
        self.url_row.connect("changed", self._on_url_changed)
        g1.add(self.url_row)

        self.mode_row = Adw.ComboRow(title="Type", model=Gtk.StringList.new(MODES))
        self.mode_row.connect("notify::selected", lambda *_: self._on_mode_changed())
        g1.add(self.mode_row)

        self.quality_row = Adw.ComboRow(title="Quality", model=Gtk.StringList.new(["Best quality"]), visible=False)
        self.quality_row.connect("notify::selected", lambda *_: (self._update_format_choices(), self._update_folder_row()))
        g1.add(self.quality_row)

        self.format_row = Adw.ComboRow(title="Format", subtitle="The type of file to save",
                                       model=Gtk.StringList.new([c[0] for c in self._containers]), visible=False)
        g1.add(self.format_row)

        self.info_row = Adw.ActionRow(title="Details", subtitle="Enter a link")
        self.spinner = Adw.Spinner(visible=False)
        self.info_row.add_suffix(self.spinner)
        self.retry_btn = Gtk.Button(label="Try Again", valign=Gtk.Align.CENTER, visible=False)
        self.retry_btn.connect("clicked", lambda *_: self._start_probe())
        self.info_row.add_suffix(self.retry_btn)
        g1.add(self.info_row)

        self.formats_row = Adw.ActionRow(title="Formats on this site", subtitle_selectable=True, visible=False)
        self.formats_row.add_prefix(Gtk.Image(icon_name="video-x-generic-symbolic"))
        g1.add(self.formats_row)

        self.playlist_row = Adw.SwitchRow(
            title="Download entire playlist", subtitle="Otherwise only the video in the link", active=True, visible=False)
        self.playlist_row.connect("notify::active", lambda *_: self._start_probe())
        g1.add(self.playlist_row)
        self.g1 = g1
        page.add(g1)

        # A part of the video only ("from 1:20 to 2:05")
        gc = Adw.PreferencesGroup()
        self.clip_row = Adw.ExpanderRow(title="Download only a part", subtitle="Choose where the clip starts and ends",
                                        show_enable_switch=True, enable_expansion=False)
        self.clip_row.add_prefix(Gtk.Image(icon_name="edit-cut-symbolic"))
        self.clip_start_row = Adw.EntryRow(title="From  (for example 1:20)")
        self.clip_end_row = Adw.EntryRow(title="To  (for example 2:05 — leave empty for the end)")
        self.clip_hint = Adw.ActionRow(title="How it's cut", subtitle="The clip starts at the nearest key frame, "
                                       "which can be a second or two before the time you set")
        self.clip_hint.add_css_class("dim-label")
        for r in (self.clip_start_row, self.clip_end_row, self.clip_hint):
            self.clip_row.add_row(r)
        self.clip_start_row.connect("changed", lambda *_: self._update_clip())
        self.clip_end_row.connect("changed", lambda *_: self._update_clip())
        self.clip_row.connect("notify::enable-expansion", lambda *_: self._update_clip())
        gc.add(self.clip_row)
        self.clip_group = gc
        page.add(gc)

        g2 = Adw.PreferencesGroup()
        self.name_row = Adw.EntryRow(title="File name")
        self.name_row.connect("changed", self._on_name_changed)
        g2.add(self.name_row)

        self.folder_row = Adw.ActionRow(title="Save to")
        self.reset_btn = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, visible=False,
                                    tooltip_text="Use the default download folder again")
        self.reset_btn.add_css_class("flat")
        self.reset_btn.connect("clicked", self._reset_folder)
        self.folder_row.add_suffix(self.reset_btn)
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
        remembered = self.manager.remembered_folder()
        if remembered:
            # The folder picked by hand last time: every new download goes there until another one is picked.
            self._folder, self._folder_fixed = remembered, True
        self._update_folder_row()

        clip = request.get("clip") if isinstance(request.get("clip"), dict) else None
        if clip:
            start, end = _num(clip.get("start"), 0), _num(clip.get("end"), -1)
            self.clip_start_row.set_text(format_time(start) if start > 0 else "")
            self.clip_end_row.set_text(format_time(end) if end > 0 else "")
            self.clip_row.set_enable_expansion(True)
            self.clip_row.set_expanded(True)

        url = request.get("url", "")
        # A format picked on the page (MKV, audio only…) needs yt-dlp, also for a direct video file.
        if request.get("kind") == "media" or looks_like_media_page(url) or request.get("container") or request.get("audio"):
            self.mode_row.set_selected(1)
        if request.get("filename"):
            self._set_name(request["filename"])
            self._name_edited = True
        elif request.get("title") and self.is_media:
            self._set_name(sanitize_filename(clean_page_title(request["title"])))
        self.url_row.set_text(url)
        if not url:
            self._paste_from_clipboard()
        self._update_clip_visibility()
        self._update_clip()

    @property
    def is_media(self):
        return self.mode_row.get_selected() == 1

    def update_pending(self, count):
        if count:
            self.pending_banner.set_title(
                f"{count} more link{'s' if count != 1 else ''} from the browser — "
                f"{'they open' if count != 1 else 'it opens'} here next")
        self.pending_banner.set_revealed(count > 0)

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
        self._update_clip_visibility()

    # --- format and clip ----------------------------------------------------------------------
    def _selected_container(self):
        i = self.format_row.get_selected()
        return self._containers[i][1] if self.format_row.get_visible() and 0 <= i < len(self._containers) else ""

    def _update_format_choices(self):
        fmt = self._selected_format()
        audio = fmt.startswith("ba")
        if not self.is_media or fmt.startswith("link:"):
            self.format_row.set_visible(False)
            return
        if self._playlist:
            choices = [("Automatic (best audio)", "")] if audio else [
                ("Automatic (best quality)", ""), ("MP4  ·  repackaged if needed, same quality", "mp4"),
                ("MKV  ·  repackaged, same quality", "mkv")]
        else:
            choices = container_choices(self._info, audio)
        current = self._selected_container() or self._want_container
        self._containers = choices
        self.format_row.set_model(Gtk.StringList.new([c[0] for c in choices]))
        values = [c[1] for c in choices]
        self.format_row.set_selected(values.index(current) if current in values else 0)
        self.format_row.set_visible(len(choices) > 1)

    def _clip_possible(self):
        if self._playlist:
            return False
        if self.is_media:
            return True
        name = self.name_row.get_text().strip() or self.url_row.get_text().strip()
        return category_for(name) in ("Video", "Music")

    def _update_clip_visibility(self):
        self.clip_group.set_visible(self._clip_possible())

    def _clip_values(self):
        """(ok, start, end) in seconds; -1 = from the start / to the end. Marks wrong fields."""
        for r in (self.clip_start_row, self.clip_end_row):
            r.remove_css_class("error")
        if not self.clip_row.get_enable_expansion() or not self.clip_group.get_visible():
            return True, -1.0, -1.0
        a, b = self.clip_start_row.get_text().strip(), self.clip_end_row.get_text().strip()
        start = parse_time(a) if a else 0.0
        end = parse_time(b) if b else -1.0
        ok = True
        if start is None:
            self.clip_start_row.add_css_class("error")
            ok = False
        if end is None or (end >= 0 and start is not None and end <= start):
            self.clip_end_row.add_css_class("error")
            ok = False
        if ok and self._duration and start >= self._duration:
            self.clip_start_row.add_css_class("error")
            ok = False
        if ok and self._duration and end > self._duration:
            end = -1.0  # past the end: up to the end
        if not ok:
            return False, -1.0, -1.0
        if start == 0 and end < 0:
            return True, -1.0, -1.0  # the whole video
        return True, start, end

    def _update_clip(self):
        on = self.clip_row.get_enable_expansion()
        if not on:
            self.clip_row.set_subtitle("Choose where the clip starts and ends")
            return
        ok, start, end = self._clip_values()
        length = f"Video length {format_time(self._duration)}  ·  " if self._duration else ""
        if not ok:
            self.clip_row.set_subtitle(length + "Write times like 1:20 or 1:02:03; the end must come after the start")
        elif start < 0 and end < 0:
            self.clip_row.set_subtitle(length + "Enter a start and/or an end time")
        else:
            stop = end if end >= 0 else (self._duration or 0)
            span = f"  ·  {human_time(stop - max(0, start))}" if stop > max(0, start) else ""
            self.clip_row.set_subtitle(
                f"{length}{format_time(max(0, start))} – {format_time(end) if end >= 0 else 'end'}{span}")

    def _target_folder(self):
        if self._folder_fixed:
            return self._folder
        # No name yet (link not checked): guess the category from the link itself.
        name = self.name_row.get_text().strip() or self.url_row.get_text().strip()
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
        self.folder_row.set_title("Save to  ·  last chosen folder" if self._folder_fixed and not self._folder_picked
                                  else "Save to")
        self.reset_btn.set_visible(self._folder_fixed)

    def _reset_folder(self, _btn):
        self._folder, self._folder_fixed = self.manager.settings["folder"], False
        self._folder_picked, self._folder_reset = False, True
        self._update_folder_row()

    def _remember_folder(self):
        """Called when a download is added: the next ones go to the same folder."""
        if not self.manager.settings.get("remember_folder", True):
            return
        if self._folder_picked:
            self.manager.remember_folder(self._folder)
        elif self._folder_reset:
            self.manager.remember_folder(None)

    def _pick_folder(self, _btn):
        dialog = Gtk.FileDialog(title="Save To", initial_folder=Gio.File.new_for_path(self._target_folder()
                                if os.path.isdir(self._target_folder()) else self.manager.settings["folder"]))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self._folder, self._folder_fixed = folder.get_path(), True
            self._folder_picked, self._folder_reset = True, False
            self._update_folder_row()

        dialog.select_folder(self, None, done)

    def _selected_format(self):
        i = self.quality_row.get_selected()
        if self._choices and 0 <= i < len(self._choices):
            return self._choices[i][1]
        return "bv*+ba/b"

    def _selected_link(self):
        """The direct link chosen in the quality list (no-login mode), or None."""
        fmt = self._selected_format()
        if fmt.startswith("link:"):
            i = int(fmt[5:])
            return self._links[i] if 0 <= i < len(self._links) else None
        return None

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
        self._update_format_choices()
        self._update_clip_visibility()
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
        self.retry_btn.set_visible(False)
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
            proxy = self.manager.proxy_for(url)
            try:
                result = probe_media(item, playlist=want_playlist, proxy=proxy) if media else probe(item, proxy=proxy)
                err = None
            except Exception as e:  # noqa: BLE001
                result, err = None, str(e) or e.__class__.__name__
            if media and err and not is_bot_check(err):
                # The site wants a login (or yt-dlp doesn't know it): list the video links that
                # the page shows to any visitor instead.
                try:
                    links = find_page_media(item, url, proxy)
                except Exception:  # noqa: BLE001
                    links = []
                if links:
                    result, err = {"_type": "tondar_links", "links": links, "error": err}, None
            GLib.idle_add(self._probe_done, gen, media, result, err)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _probe_done(self, gen, media, result, err):
        if gen != self._generation:
            return False
        self.spinner.set_visible(False)
        self._links, self._guest, self._cookie_mode = [], False, ""
        self._info, self._duration = None, 0
        self.formats_row.set_visible(False)
        self.info_row.set_tooltip_text(None)
        if err:
            self.info_row.set_subtitle(err[:900] if is_bot_check(err) or "\n•" in err
                                       else f"Couldn't check the link: {err[:200]}")
            self.retry_btn.set_visible(True)
            return False
        self._clear_playlist()
        try:
            return self._show_probe(media, result)
        finally:
            self._update_format_choices()
            self._update_clip_visibility()
            self._update_clip()

    def _show_probe(self, media, result):
        if media and result.get("_type") == "tondar_links":
            self._show_links(result)
        elif media and is_playlist(result):
            self._guest = bool(result.get("_tondar_guest"))
            self._cookie_mode = result.get("_tondar_cookies", "")
            self._show_playlist(result)
        elif media:
            info = result
            self._info = info
            self._duration = info.get("duration") or 0
            self._guest = bool(info.get("_tondar_guest"))
            self._cookie_mode = info.get("_tondar_cookies", "")
            formats = describe_formats(info)
            self.formats_row.set_subtitle(formats)
            self.formats_row.set_visible(bool(formats))
            self._choices = quality_choices(info)
            labels = [f"{label}  ·  ~{human_size(size)}" if size else label for label, _, size in self._choices]
            self.quality_row.set_model(Gtk.StringList.new(labels))
            want_audio = self.request.get("audio") or self._want_container in ("mp3", "m4a", "opus")
            audio_rows = [i for i, c in enumerate(self._choices) if c[1].startswith("ba")]
            self.quality_row.set_selected(audio_rows[0] if want_audio and audio_rows else 0)
            parts = [info.get("extractor_key") or ""]
            if info.get("duration"):
                parts.append(human_time(info["duration"]))
            if info.get("uploader"):
                parts.append(info["uploader"])
            if self._guest:
                parts.append("found without logging in")
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

    def _show_links(self, result):
        """No-login mode: offer the video links found in the page as the "quality" choices."""
        self._links = result["links"]
        self._choices = []
        for i, link in enumerate(self._links):
            path = link["url"].split("?", 1)[0].rstrip("/")
            tail = path.rsplit("/", 1)[-1]
            host = link["url"].split("/")[2] if link["url"].count("/") >= 2 else ""
            short = tail if len(tail) <= 40 else tail[:37] + "…"
            self._choices.append((f"{link['label']}  ·  {host}  ·  {short}", f"link:{i}", 0))
        self.quality_row.set_model(Gtk.StringList.new([c[0] for c in self._choices]))
        self.quality_row.set_selected(0)
        n = len(self._links)
        self.info_row.set_subtitle(
            f"No login needed: found {n} video link{'s' if n != 1 else ''} on the page — pick one under Quality")
        self.info_row.set_tooltip_text(f"yt-dlp said: {result.get('error') or ''}"[:500])
        if not self._name_edited and self.request.get("title"):
            self._set_name(sanitize_filename(clean_page_title(self.request["title"])))

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
        container = self._selected_container()
        if fmt.startswith("ba") and container:
            fmt = audio_selector(container)
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
                scheduled=scheduled, guest=self._guest, container=container, cookie_mode=self._cookie_mode,
            )
            self.manager.add(item, start=start)
        self._remember_folder()
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
        ok, clip_start, clip_end = self._clip_values()
        if not ok:
            self.clip_row.set_expanded(True)
            return
        clip = clip_start >= 0 or clip_end >= 0
        item = self._base_item(url)
        item.folder = self._target_folder()
        item.auto_folder = not self._folder_fixed
        item.max_segments = int(self.seg_row.get_value())
        name = sanitize_filename(self.name_row.get_text().strip(), "")
        link = self._selected_link() if self.is_media else None
        if link:
            # A video link found in the page (no login): download that link itself.
            r = self.request
            item.url, item.page_url = link["url"], url
            item.referer = r.get("referer") or url
            item.cookies = r.get("cookies", [])
            if link["kind"] == "media" or clip:
                item.kind, item.title, item.media_format = "media", _stem(name), "bv*+ba/b"
            else:
                ext = link["url"].split("?", 1)[0].rsplit(".", 1)[-1].lower()
                if name and len(ext) <= 5 and not name.lower().endswith("." + ext):
                    name = f"{name}.{ext}"
                item.filename = name  # empty: named by the server
                if item.auto_folder:
                    item.folder = self.manager.folder_for(name or link["url"])
        elif self.is_media:
            item.kind = "media"
            item.title = name
            fmt, container = self._selected_format(), self._selected_container()
            if fmt.startswith("ba") and container:
                fmt = audio_selector(container)
            item.media_format, item.container = fmt, container
            item.guest = self._guest
            item.cookie_mode = self._cookie_mode
        elif clip:
            # Part of a video file: yt-dlp (with ffmpeg) fetches just that part.
            item.kind, item.title, item.media_format = "media", _stem(name), "bv*+ba/b"
        else:
            item.filename = name
            item.size = self._probe_size
        item.clip_start, item.clip_end = clip_start, clip_end
        item.scheduled = scheduled
        item.popup = True
        added = self.manager.add(item, start=start)
        self._remember_folder()
        if start and added is item:
            self.app.show_progress(item)
        if self.app.window and self.app.window.get_visible():
            if added is not item:
                self.app.window.toast(f"Already in the list: “{added.display_name}”")
            else:
                self.app.window.toast(f"{'Scheduled' if scheduled else 'Added'} “{item.display_name}”")
        if scheduled and not self.manager.settings["schedule_enabled"]:
            self.app.window and self.app.window.toast("Turn on the scheduler in Preferences → Scheduler")
        self.close()


CLONE_DEPTHS = [
    ("The whole website", -1),
    ("This page only", 0),
    ("This page and the pages it links to", 1),
    ("Two clicks deep", 2),
    ("Three clicks deep", 3),
]


class CloneWindow(Adw.Window):
    """"Clone Website": saves a whole site (pages, pictures, styles, scripts, fonts) for offline use."""

    def __init__(self, app, url=""):
        super().__init__(application=app, title="Clone Website", default_width=580, default_height=720)
        self.app = app
        self.manager = app.manager
        self._generation = 0
        self._timer = 0
        self._title = ""
        self._name_edited = False
        self._setting_name = False
        self._folder = self.manager.folder_for("", "site")
        if app.window and app.window.get_visible():
            self.set_transient_for(app.window)
            self.set_modal(True)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()

        g = Adw.PreferencesGroup(
            description="Saves the website's pages with their pictures, styles, scripts and fonts, and links them "
                        "together so the copy opens in your browser without internet.")
        self.url_row = Adw.EntryRow(title="Website address")
        self.url_row.connect("changed", self._on_url_changed)
        g.add(self.url_row)
        self.info_row = Adw.ActionRow(title="Website", subtitle="Enter an address, like https://example.com")
        self.info_row.add_prefix(Gtk.Image(icon_name="web-browser-symbolic"))
        self.spinner = Adw.Spinner(visible=False)
        self.info_row.add_suffix(self.spinner)
        g.add(self.info_row)
        page.add(g)

        g = Adw.PreferencesGroup(title="What to save")
        self.depth_row = Adw.ComboRow(title="Pages", model=Gtk.StringList.new([d[0] for d in CLONE_DEPTHS]))
        self.depth_row.connect("notify::selected", lambda *_: self._update_depth())
        g.add(self.depth_row)
        self.pages_row = Adw.SpinRow.new_with_range(1, 100000, 50)
        self.pages_row.set_title("At most")
        self.pages_row.set_subtitle("pages, so a huge site doesn't fill your disk")
        self.pages_row.set_value(1000)
        g.add(self.pages_row)
        self.external_row = Adw.SwitchRow(
            title="Pictures, styles and fonts from other servers", active=True,
            subtitle="Many sites keep these on a CDN; without them pages look broken offline")
        g.add(self.external_row)
        self.files_row = Adw.SwitchRow(title="Files the pages link to", active=True,
                                       subtitle="PDF, ZIP, videos, music… on the same website")
        g.add(self.files_row)
        self.size_row = Adw.SpinRow.new_with_range(0, 100000, 10)
        self.size_row.set_title("Skip files larger than (MB)")
        self.size_row.set_subtitle("0 means no limit")
        self.size_row.set_value(200)
        g.add(self.size_row)
        self.robots_row = Adw.SwitchRow(title="Respect robots.txt", active=True,
                                        subtitle="Skip the pages the website asks download tools not to visit")
        g.add(self.robots_row)
        page.add(g)

        g = Adw.PreferencesGroup(title="Where")
        self.name_row = Adw.EntryRow(title="Folder name")
        self.name_row.connect("changed", lambda *_: self._on_name_changed())
        g.add(self.name_row)
        self.folder_row = Adw.ActionRow(title="Save in")
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Choose Folder")
        pick.add_css_class("flat")
        pick.connect("clicked", self._pick_folder)
        self.folder_row.add_suffix(pick)
        self.folder_row.set_activatable_widget(pick)
        g.add(self.folder_row)
        self.seg_row = Adw.SpinRow.new_with_range(1, 16, 1)
        self.seg_row.set_title("Files at the same time")
        self.seg_row.set_subtitle("More is faster; some sites block too many")
        self.seg_row.set_value(6)
        g.add(self.seg_row)
        page.add(g)

        note = Gtk.Label(label="Pages that are put together by JavaScript in the browser may look incomplete offline. "
                               "Only clone sites you're allowed to copy.", wrap=True, xalign=0,
                         margin_start=12, margin_end=12)
        note.add_css_class("caption")
        note.add_css_class("dim-label")
        g = Adw.PreferencesGroup()
        g.add(note)
        page.add(g)
        view.set_content(page)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        later = Gtk.Button(label="Clone Later")
        later.connect("clicked", lambda *_: self._submit(False))
        self.start_btn = Gtk.Button()
        self.start_btn.set_child(Adw.ButtonContent(icon_name="folder-download-symbolic", label="Start Cloning"))
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", lambda *_: self._submit(True))
        for b in (cancel, later, self.start_btn):
            buttons.append(b)
        view.add_bottom_bar(buttons)
        self.set_content(view)
        self.set_default_widget(self.start_btn)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"), Gtk.CallbackAction.new(lambda *_: self.close())))
        self.add_controller(esc)
        self._update_folder_row()
        self._update_depth()
        if url:
            self.url_row.set_text(url)

    # --- helpers ----------------------------------------------------------------------------------
    def _url(self):
        url = self.url_row.get_text().strip()
        if url and "://" not in url and "." in url and " " not in url:
            url = "https://" + url
        return url

    def _update_depth(self):
        depth = CLONE_DEPTHS[self.depth_row.get_selected()][1]
        self.pages_row.set_sensitive(depth != 0)

    def _on_name_changed(self):
        if not self._setting_name:
            self._name_edited = True
        self._update_folder_row()

    def _set_name(self, name):
        self._setting_name = True
        self.name_row.set_text(name)
        self._setting_name = False
        self._update_folder_row()

    def _update_folder_row(self):
        name = sanitize_filename(self.name_row.get_text().strip(), "")
        path = os.path.join(self._folder, name) if name else self._folder
        self.folder_row.set_subtitle(path.replace(os.path.expanduser("~"), "~", 1))

    def _pick_folder(self, _btn):
        start = self._folder if os.path.isdir(self._folder) else self.manager.settings["folder"]
        dialog = Gtk.FileDialog(title="Save In", initial_folder=Gio.File.new_for_path(start))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self._folder = folder.get_path()
            self._update_folder_row()

        dialog.select_folder(self, None, done)

    def _on_url_changed(self, _row):
        self.url_row.remove_css_class("error")
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(600, self._probe)
        url = self._url()
        host = urllib.parse.urlsplit(url).hostname if "://" in url else ""
        if host and not self._name_edited:
            self._set_name(sanitize_filename(host, "website"))

    def _probe(self):
        self._timer = 0
        self._generation += 1
        gen = self._generation
        url = self._url()
        if "://" not in url:
            self.spinner.set_visible(False)
            self.info_row.set_title("Website")
            self.info_row.set_subtitle("Enter an address, like https://example.com")
            return False
        self.spinner.set_visible(True)
        self.info_row.set_subtitle("Opening the page…")
        proxy = self.manager.proxy_for(url)

        def work():
            try:
                title, final, ctype = _page_title(url, proxy)
                err = None
            except Exception as e:  # noqa: BLE001
                title = final = ctype = None
                err = str(e) or e.__class__.__name__
            GLib.idle_add(self._probe_done, gen, title, final, ctype, err)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _probe_done(self, gen, title, final, ctype, err):
        if gen != self._generation:
            return False
        self.spinner.set_visible(False)
        if err:
            self.info_row.set_title("Website")
            self.info_row.set_subtitle(f"Couldn't open it: {err[:200]}")
            return False
        host = urllib.parse.urlsplit(final).hostname or ""
        self._title = title or host
        self.info_row.set_title(title or host)
        if ctype not in ("text/html", "application/xhtml+xml"):
            self.info_row.set_subtitle(f"{host}  ·  this address is a file ({ctype}), not a web page")
        else:
            self.info_row.set_subtitle(f"{host}  ·  ready to clone")
        return False

    def _submit(self, start):
        url = self._url()
        if "://" not in url:
            self.url_row.add_css_class("error")
            return
        host = urllib.parse.urlsplit(url).hostname or "website"
        name = sanitize_filename(self.name_row.get_text().strip(), "") or sanitize_filename(host, "website")
        depth = CLONE_DEPTHS[self.depth_row.get_selected()][1]
        item = Item(
            url=url, kind="site", folder=self._folder, filename=name, title=self._title,
            clone_depth=depth, clone_max_pages=1 if depth == 0 else int(self.pages_row.get_value()),
            clone_external=self.external_row.get_active(), clone_files=self.files_row.get_active(),
            clone_max_mb=int(self.size_row.get_value()), clone_robots=self.robots_row.get_active(),
            max_segments=int(self.seg_row.get_value()), popup=True,
        )
        added = self.manager.add(item, start=start)
        if self.app.window and self.app.window.get_visible():
            self.app.window.toast(f"Already in the list: “{added.display_name}”" if added is not item
                                  else f"{'Cloning' if start else 'Added'} “{item.display_name}”")
        if start and added is item:
            self.app.show_progress(item)
        self.close()


def _page_title(url, proxy):
    """(title, final url, content type) of a web page; reads only its beginning."""
    from .http_task import DEFAULT_UA
    from .net import proxy_handlers

    opener = urllib.request.build_opener(*proxy_handlers(proxy))
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(req, timeout=20) as r:
        ctype = r.headers.get_content_type()
        raw = r.read(256 * 1024) if ctype in ("text/html", "application/xhtml+xml") else b""
        final = r.geturl()
        charset = r.headers.get_content_charset() or "utf-8"
    m = re.search(rb"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = ""
    if m:
        try:
            title = html.unescape(m.group(1).decode(charset, "replace"))
        except LookupError:
            title = html.unescape(m.group(1).decode("utf-8", "replace"))
        title = " ".join(title.split())[:150]
    return title, final, ctype


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stem(name):
    """A file name without its video/audio extension (yt-dlp adds the right one)."""
    base, dot, ext = name.rpartition(".")
    return base if dot and category_for(name) in ("Video", "Music") else name


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
        remember = self._switch("remember_folder", "Remember the folder I choose",
                                "New downloads go to the folder last picked in the New Download window")
        g.add(remember)
        self.last_row = Adw.ActionRow(title="Last chosen folder", subtitle_selectable=True)
        forget = Gtk.Button(label="Forget", valign=Gtk.Align.CENTER, tooltip_text="Use the download folder above again")
        forget.connect("clicked", lambda *_: self._forget_folder())
        self.last_row.add_suffix(forget)
        self._forget_btn = forget
        g.add(self.last_row)
        remember.connect("notify::active", lambda *_: self._show_last_folder())
        self._show_last_folder()
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
        g.add(self._switch("progress_window", "Show a progress window",
                           "For downloads you start yourself: speed, time left, Pause and Cancel"))
        g.add(self._switch("complete_window", "Show a window when a download finishes",
                           "With buttons to open the file or its folder"))
        g.add(self._switch("notify", "Notify when a download finishes", "Only when no window is shown for it"))
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
        names = ["Don't use"] + [b.capitalize() for b in BROWSERS]
        signin = Adw.ComboRow(
            title="Sign-in from browser",
            subtitle="When YouTube asks to confirm you're not a bot, use your sign-in from this browser. "
                     "Close Chrome / Edge first — they lock it while open.",
            model=Gtk.StringList.new(names))
        current = self.app.manager.settings.get("cookies_browser", "")
        signin.set_selected(BROWSERS.index(current) + 1 if current in BROWSERS else 0)
        signin.connect("notify::selected", lambda r, _p: self._set(
            "cookies_browser", BROWSERS[r.get_selected() - 1] if r.get_selected() else ""))
        g.add(signin)
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
            self._forget_folder()  # the newest choice wins: the new download folder is used from now on

        Gtk.FileDialog(title="Download Folder").select_folder(self.get_root(), None, done)

    def _show_last_folder(self):
        s = self.app.manager.settings
        last = s.get("last_folder") or ""
        self.last_row.set_subtitle(last or "None — the download folder above is used")
        self.last_row.set_sensitive(bool(s.get("remember_folder", True)))
        self._forget_btn.set_sensitive(bool(last))

    def _forget_folder(self):
        self._set("last_folder", "")
        self._show_last_folder()

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

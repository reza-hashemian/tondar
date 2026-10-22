"""The window for many links at once (selected together in the browser): one folder and one
set of choices for all of them, a check box to leave some out, and all go into the queue."""

import os
import time
import urllib.parse

from gi.repository import Adw, Gio, GLib, Gtk

from .core import Item
from .util import category_for, looks_like_media_page, sanitize_filename


def guess_name(url, text=""):
    """What to call a link in the list: the file name in its address, else the link's text."""
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    except ValueError:
        path = ""
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if "." in name.strip("."):
        return name
    return text or name or url


class BatchWindow(Adw.Window):
    def __init__(self, app, request):
        super().__init__(application=app, title="Download Links", default_width=620, default_height=760)
        self.app = app
        self.manager = app.manager
        self.request = request
        self._folder_fixed = False
        self._folder_picked = False

        seen, self.links = set(), []
        for link in request.get("links") or []:
            url = (link.get("url") if isinstance(link, dict) else str(link or "")).strip()
            if "://" in url and url not in seen:
                seen.add(url)
                self.links.append((url, guess_name(url, (link.get("text") if isinstance(link, dict) else "") or "")))

        if app.window and app.window.get_visible():
            self.set_transient_for(app.window)
            self.set_modal(True)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()

        # One set of choices for all of them
        g = Adw.PreferencesGroup(title="Save")
        self.sub_row = Adw.EntryRow(title="Put them in a new folder (optional, e.g. the series name)")
        self.sub_row.connect("changed", lambda *_: self._update_folder_row())
        g.add(self.sub_row)
        self.folder_row = Adw.ActionRow(title="Save to")
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Choose Folder")
        pick.add_css_class("flat")
        pick.connect("clicked", self._pick_folder)
        self.folder_row.add_suffix(pick)
        self.folder_row.set_activatable_widget(pick)
        g.add(self.folder_row)
        self.seg_row = Adw.SpinRow.new_with_range(1, 32, 1)
        self.seg_row.set_title("Connections")
        self.seg_row.set_subtitle("For each file")
        self.seg_row.set_value(int(self.manager.settings["segments"]))
        g.add(self.seg_row)
        page.add(g)
        # The links, each with a check box
        host = urllib.parse.urlparse(request.get("page_url") or request.get("url") or "").hostname or ""
        self.list_group = Adw.PreferencesGroup(
            title=f"{len(self.links)} links", description=f"Selected on {host}" if host else None)
        self.toggle = Gtk.Button(label="Select None", valign=Gtk.Align.CENTER)
        self.toggle.add_css_class("flat")
        self.toggle.connect("clicked", self._on_toggle)
        self.list_group.set_header_suffix(self.toggle)
        self.checks = []
        pad = len(str(len(self.links)))
        for i, (url, name) in enumerate(self.links, 1):
            check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
            check.connect("toggled", lambda *_: self._update())
            kind = "Video page (yt-dlp)" if looks_like_media_page(url) else category_for(url)
            row = Adw.ActionRow(title=f"{i:0{pad}}. {name}", use_markup=False,
                                subtitle=f"{kind}  ·  {urllib.parse.urlparse(url).hostname or ''}",
                                title_lines=1, tooltip_text=url)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.list_group.add(row)
            self.checks.append(check)

        page.add(self.list_group)
        view.set_content(page)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        later = Gtk.Button(label="Download Later")
        later.connect("clicked", lambda *_: self._submit(False))
        sched = Gtk.Button(tooltip_text="Start automatically at the scheduled time (Preferences → Scheduler)")
        sched.set_child(Adw.ButtonContent(icon_name="alarm-symbolic", label="Schedule"))
        sched.connect("clicked", lambda *_: self._submit(False, scheduled=True))
        self.start_btn = Gtk.Button()
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", lambda *_: self._submit(True))
        self.action_buttons = (later, sched, self.start_btn)
        for b in self.action_buttons:
            buttons.append(b)
        view.add_bottom_bar(buttons)
        self.set_content(view)
        self.set_default_widget(self.start_btn)

        keys = Gtk.ShortcutController()
        keys.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                           Gtk.CallbackAction.new(lambda *_: self.close())))
        self.add_controller(keys)

        remembered = self.manager.remembered_folder()
        self._folder = remembered or self.manager.settings["folder"]
        self._folder_fixed = bool(remembered)
        self._update()

    # --- selection -------------------------------------------------------------------------
    def _selected(self):
        return [link for link, check in zip(self.links, self.checks) if check.get_active()]

    def _on_toggle(self, _btn):
        select = not any(c.get_active() for c in self.checks)
        for c in self.checks:
            c.set_active(select)

    def _update(self):
        n = len(self._selected())
        self.list_group.set_title(f"{n} of {len(self.links)} links selected")
        self.toggle.set_label("Select None" if n else "Select All")
        self.start_btn.set_label(f"Download {n} Files" if n != 1 else "Download 1 File")
        for b in self.action_buttons:
            b.set_sensitive(n > 0)
        self._update_folder_row()

    # --- folder ----------------------------------------------------------------------------
    def _kind(self, url):
        return "media" if looks_like_media_page(url) else "http"

    def _base_folder(self):
        if self._folder_fixed:
            return self._folder
        selected = self._selected() or self.links
        url, name = selected[0] if selected else ("", "")
        return self.manager.folder_for(name or url, self._kind(url))

    def _subfolder(self):
        return sanitize_filename(self.sub_row.get_text().strip(), "")

    def _update_folder_row(self):
        folder = self._base_folder()
        if self._subfolder():
            folder = os.path.join(folder, self._subfolder())
        elif not self._folder_fixed and self.manager.settings["categorize"]:
            folder = os.path.join(self.manager.settings["folder"], "…  (sorted by file type)")
        self.folder_row.set_subtitle(folder.replace(os.path.expanduser("~"), "~", 1))

    def _pick_folder(self, _btn):
        start = self._base_folder()
        dialog = Gtk.FileDialog(title="Save To", initial_folder=Gio.File.new_for_path(
            start if os.path.isdir(start) else self.manager.settings["folder"]))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self._folder, self._folder_fixed, self._folder_picked = folder.get_path(), True, True
            self._update_folder_row()

        dialog.select_folder(self, None, done)

    # --- submit -----------------------------------------------------------------------------
    def _submit(self, start, scheduled=False):
        selected = self._selected()
        if not selected:
            return
        r = self.request
        sub = self._subfolder()
        base = self._base_folder()
        now = time.time()
        added = 0
        for n, (url, name) in enumerate(selected):
            kind = self._kind(url)
            if sub:
                folder, auto = os.path.join(base, sub), False
            elif self._folder_fixed:
                folder, auto = self._folder, False
            else:  # each file to its own category folder, corrected once the real name is known
                folder, auto = self.manager.folder_for(name, kind), True
            item = Item(
                url=url, kind=kind, folder=folder, auto_folder=auto,
                referer=r.get("referer", ""), user_agent=r.get("user_agent", ""), cookies=r.get("cookies", []),
                page_url=r.get("page_url", ""), max_segments=int(self.seg_row.get_value()),
                media_format="bv*+ba/b" if kind == "media" else "",
                created=now - n * 0.001,  # keeps the page's order in the newest-first list
                scheduled=scheduled,
            )
            if self.manager.add(item, start=start) is item:
                added += 1
        if self._folder_picked and self.manager.settings.get("remember_folder", True):
            self.manager.remember_folder(self._folder)
        win = self.app.window
        if win and win.get_visible():
            text = f"{'Scheduled' if scheduled else 'Added'} {added} download{'s' if added != 1 else ''}"
            if added < len(selected):
                text += f" ({len(selected) - added} already in the list)"
            win.toast(text)
            if scheduled and not self.manager.settings["schedule_enabled"]:
                win.toast("Turn on the scheduler in Preferences → Scheduler")
        self.close()


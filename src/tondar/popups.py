"""The windows that follow one download: progress while it runs, and "Download Complete" with
Open / Open Folder / Close when it's done."""

import os
import time
import urllib.parse

from gi.repository import Adw, Gdk, GLib, Gtk

from .core import COMPLETED, DOWNLOADING, ERROR, PAUSED, PAUSING, QUEUED
from .media import ext_name, format_time
from .util import human_size, human_time

SYMBOLIC = {
    "Video": "video-x-generic-symbolic",
    "Music": "audio-x-generic-symbolic",
    "Compressed": "package-x-generic-symbolic",
    "Documents": "x-office-document-symbolic",
    "Programs": "application-x-executable-symbolic",
    "Websites": "web-browser-symbolic",
    "Other": "text-x-generic-symbolic",
}

def _open_icon(item, site):
    # Adwaita's document-open is a folder: it looked just like "Open Folder" next to it.
    if site:
        return "web-browser-symbolic"
    if item.category in ("Video", "Music"):
        return "media-playback-start-symbolic"
    return SYMBOLIC.get(item.category, "text-x-generic-symbolic")


CSS = """
.tondar-tile { background-color: alpha(@accent_bg_color, 0.14); border-radius: 18px; min-width: 60px; min-height: 60px; }
.tondar-tile image { color: @accent_color; }
.tondar-tile.paused { background-color: alpha(@window_fg_color, 0.08); }
.tondar-tile.paused image { color: alpha(@window_fg_color, 0.6); }
.tondar-tile.failed { background-color: alpha(@error_color, 0.14); }
.tondar-tile.failed image { color: @error_color; }
progressbar.tondar-bar trough, progressbar.tondar-bar progress { min-height: 10px; border-radius: 999px; }
progressbar.tondar-bar.paused progress { background-color: alpha(@window_fg_color, 0.35); }
.tondar-percent { font-size: 32px; font-weight: 800; font-feature-settings: "tnum"; }
.tondar-stat { padding: 10px 12px; }
.tondar-stat-value { font-weight: 700; font-size: 15px; font-feature-settings: "tnum"; }
.tondar-badge { background-color: @success_bg_color; color: @success_fg_color; border-radius: 999px;
  min-width: 80px; min-height: 80px; }
.tondar-badge.site { background-color: @accent_bg_color; color: @accent_fg_color; }
.tondar-done-title { font-size: 22px; font-weight: 800; }
"""

_css_done = False


def install_css():
    global _css_done
    if _css_done:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS) if hasattr(provider, "load_from_string") else provider.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_done = True


def _label(text="", *classes, **kw):
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _host(url):
    try:
        return urllib.parse.urlsplit(url).hostname or url
    except ValueError:
        return url


def _type_label(item):
    if item.kind == "site":
        return "Website"
    if item.kind == "media":
        if item.container:
            return f"Video · {ext_name(item.container)}" if not item.media_format.startswith("ba") \
                else f"Audio · {ext_name(item.container)}"
        return "Audio" if (item.media_format or "").startswith("ba") else "Video"
    ext = item.filename.rsplit(".", 1)[-1] if "." in item.filename else ""
    return f"{item.category} · {ext.upper()}" if ext and len(ext) <= 5 else item.category


def clip_text(item):
    start = format_time(max(0, item.clip_start))
    end = "end" if item.clip_end < 0 else format_time(item.clip_end)
    return f"{start} – {end}"


class _Stat(Gtk.Box):
    """One small card: a value with a caption under it."""

    def __init__(self, caption):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.add_css_class("card")
        self.add_css_class("tondar-stat")
        self.value = _label("—", "tondar-stat-value", xalign=0, ellipsize=3)
        self.caption = _label(caption, "caption", "dim-label", xalign=0)
        self.append(self.value)
        self.append(self.caption)


class ProgressWindow(Adw.Window):
    """A window of its own for one running download."""

    def __init__(self, app, item):
        super().__init__(application=app, title=f"Tondar · {item.display_name}"[:120],
                         default_width=500, resizable=False)
        install_css()
        self.app = app
        self.item = item
        self._state = None

        view = Adw.ToolbarView()
        self.heading = Adw.WindowTitle(title="Downloading")
        header = Adw.HeaderBar(title_widget=self.heading)
        view.add_top_bar(header)

        self.toasts = Adw.ToastOverlay()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=6, margin_bottom=18, margin_start=24, margin_end=24)

        # File: icon, name, where it comes from
        top = Gtk.Box(spacing=16)
        self.tile = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.tile.add_css_class("tondar-tile")
        self.icon = Gtk.Image(pixel_size=30, hexpand=True, vexpand=True,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.tile.append(self.icon)
        top.append(self.tile)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        self.name = _label("", "title-4", xalign=0, ellipsize=3, max_width_chars=36)
        self.source = _label("", "dim-label", xalign=0, ellipsize=3, max_width_chars=40)
        names.append(self.name)
        names.append(self.source)
        top.append(names)
        body.append(top)

        # Percent and bar
        meter = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        line = Gtk.Box(spacing=8)
        self.percent = _label("0%", "tondar-percent", xalign=0, hexpand=True)
        self.state_label = _label("", "dim-label", valign=Gtk.Align.END, margin_bottom=6)
        line.append(self.percent)
        line.append(self.state_label)
        meter.append(line)
        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("tondar-bar")
        meter.append(self.bar)
        self.amount = _label("", "caption", "dim-label", xalign=0, ellipsize=3)
        meter.append(self.amount)
        body.append(meter)

        # Speed · time left · size (files for a website)
        stats = Gtk.Box(spacing=10, homogeneous=True)
        self.speed = _Stat("Speed")
        self.left = _Stat("Time left")
        self.size = _Stat("Pages and files" if item.kind == "site" else "Size")
        for s in (self.speed, self.left, self.size):
            stats.append(s)
        self.stats = stats
        body.append(stats)

        # Error text (only when it failed)
        self.error = _label("", "error", xalign=0, wrap=True, selectable=True, visible=False, max_width_chars=50)
        body.append(self.error)

        # Details
        details = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        details.add_css_class("boxed-list")
        self.folder_row = Adw.ActionRow(title="Saving to", subtitle_selectable=True)
        folder_btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Open Folder")
        folder_btn.add_css_class("flat")
        folder_btn.connect("clicked", lambda *_: self._open_folder())
        self.folder_row.add_suffix(folder_btn)
        details.append(self.folder_row)
        if item.is_clip:
            details.append(Adw.ActionRow(title="Only this part", subtitle=clip_text(item)))
        body.append(details)

        self.toasts.set_child(body)
        view.set_content(self.toasts)

        # Buttons
        bar = Gtk.Box(spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        hide = Gtk.Button(label="Hide", tooltip_text="Keep downloading in the background (the main window lists it)")
        hide.add_css_class("flat")
        hide.connect("clicked", lambda *_: self.close())
        bar.append(hide)
        bar.append(Gtk.Box(hexpand=True))
        self.cancel_btn = Gtk.Button(label="Cancel")
        self.cancel_btn.connect("clicked", lambda *_: self._cancel())
        bar.append(self.cancel_btn)
        self.toggle_btn = Gtk.Button()
        self.toggle_btn.add_css_class("suggested-action")
        self.toggle_btn.connect("clicked", lambda *_: self._toggle())
        bar.append(self.toggle_btn)
        view.add_bottom_bar(bar)
        self.set_content(view)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                          Gtk.CallbackAction.new(lambda *_: self.close() or True)))
        self.add_controller(esc)
        self.refresh()

    # --- updates ----------------------------------------------------------------------------------
    def refresh(self):
        it = self.item
        state = (it.status, it.done, it.size, round(it.speed), it.files_done, it.files_total, it.filename, it.title,
                 it.error, it.folder)
        if state == self._state:
            if it.status == DOWNLOADING and it.size <= 0 and it.kind != "site":
                self.bar.pulse()
            return
        self._state = state
        site = it.kind == "site"
        self.name.set_label("\u200e" + it.display_name)
        self.name.set_tooltip_text(it.display_name)
        self.source.set_label(_host(it.page_url or it.url) + "  ·  " + _type_label(it))
        self.icon.set_from_icon_name(SYMBOLIC.get(it.category, "text-x-generic-symbolic"))
        home = os.path.expanduser("~")
        self.folder_row.set_subtitle((it.path if site else it.folder).replace(home, "~", 1))

        for c in ("paused", "failed"):
            self.tile.remove_css_class(c)
            self.bar.remove_css_class(c)
        failed = it.status == ERROR
        self.stats.set_visible(not failed)
        self.error.set_visible(failed)
        known = (it.files_total > 0) if site else (it.size > 0)
        fraction = it.progress if known else 0.0

        if it.status == DOWNLOADING:
            title = "Cloning Website" if site else "Downloading"
            self.state_label.set_label("Connecting…" if it.done == 0 and not it.files_done else "")
        elif it.status == QUEUED:
            title = "Waiting in Queue"
            limit = int(self.app.manager.settings["max_active"])
            self.state_label.set_label(f"starts when one of the {limit} running downloads is done"
                                       if limit > 1 else "starts after the running download")
        elif it.status in (PAUSED, PAUSING):
            title = "Paused" if it.status == PAUSED else "Pausing…"
            self.state_label.set_label("")
            self.tile.add_css_class("paused")
            self.bar.add_css_class("paused")
        elif failed:
            title = "Download Failed"
            self.state_label.set_label("")
            self.tile.add_css_class("failed")
            self.icon.set_from_icon_name("dialog-error-symbolic")
            self.error.set_label(it.error or "Something went wrong")
        else:
            title = "Download Complete"
            fraction, known = 1.0, True
            self.state_label.set_label("")
        self.heading.set_title(title)
        self.heading.set_subtitle(f"{int(fraction * 100)}%" if known else "")

        if known:
            self.percent.set_label(f"{int(fraction * 100)}%")
            self.bar.set_fraction(fraction)
        else:
            self.percent.set_label(human_size(it.done) if it.done else "—")
            if it.status == DOWNLOADING:
                self.bar.pulse()
            else:
                self.bar.set_fraction(0)

        if site:
            self.amount.set_label(f"{it.files_done} of {it.files_total} files saved  ·  {human_size(it.done)}"
                                  + (f"  ·  {it.files_failed} couldn't be saved" if it.files_failed else ""))
            self.size.value.set_label(f"{it.files_done} / {it.files_total}" if it.files_total else "—")
        else:
            total = human_size(it.size) if it.size > 0 else "unknown size"
            self.amount.set_label(f"{human_size(it.done)} of {total}")
            self.size.value.set_label(human_size(it.size) if it.size > 0 else human_size(it.done) if it.done else "—")
        running = it.status == DOWNLOADING
        self.speed.value.set_label(f"{human_size(it.speed)}/s" if running and it.speed > 0 else "—")
        self.left.value.set_label(human_time(it.eta) if running and it.eta is not None else "—")

        self.toggle_btn.set_visible(it.status != PAUSING)
        if failed:
            self.toggle_btn.set_label("Retry")
        elif it.status in (DOWNLOADING, QUEUED):
            self.toggle_btn.set_label("Pause")
        else:
            self.toggle_btn.set_label("Resume")
        self.cancel_btn.set_label("Remove" if failed else "Cancel")

    # --- actions ----------------------------------------------------------------------------------
    def _toggle(self):
        m = self.app.manager
        if self.item.status in (DOWNLOADING, QUEUED):
            m.pause(self.item)
        else:
            m.start(self.item)
        self.refresh()

    def _cancel(self):
        it = self.item
        site = it.kind == "site"
        dialog = Adw.AlertDialog(
            heading="Cancel This Download?",
            body=("The website copy stops here. Files saved so far stay in its folder." if site else
                  "It is removed from the list and the part downloaded so far is deleted."))
        dialog.add_response("keep", "Keep Downloading")
        dialog.add_response("cancel", "Cancel Download")
        dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")

        def on_response(_d, response):
            if response == "cancel":
                self.app.manager.remove(it, delete_file=False)
                self.close()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _open_folder(self):
        from .window import open_folder, open_uri

        it = self.item
        if it.kind == "site" and os.path.isdir(it.path):
            open_uri(it.path, self)
        elif it.filename and os.path.exists(it.path):
            open_folder(it.path, self)
        elif os.path.isdir(it.folder):
            open_uri(it.folder, self)
        else:
            self.toasts.add_toast(Adw.Toast(title="The folder is made when the download starts"))


class CompleteWindow(Adw.Window):
    """"Download Complete": open the file, open its folder, or close."""

    def __init__(self, app, item):
        site = item.kind == "site"
        super().__init__(application=app, title=f"Tondar · {'Website Saved' if site else 'Download Complete'}",
                         default_width=440, resizable=False)
        install_css()
        self.app = app
        self.item = item

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_title=False)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay()

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_bottom=24, margin_start=28, margin_end=28)
        badge = Gtk.Box(halign=Gtk.Align.CENTER)
        badge.add_css_class("tondar-badge")
        if site:
            badge.add_css_class("site")
        badge.append(Gtk.Image(icon_name="web-browser-symbolic" if site else "object-select-symbolic", pixel_size=40,
                               hexpand=True, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER))
        body.append(badge)
        body.append(_label("Website Saved" if site else "Download Complete", "tondar-done-title", margin_top=14))
        name = _label("\u200e" + item.display_name, "heading", wrap=True, wrap_mode=2, justify=Gtk.Justification.CENTER,
                      max_width_chars=40, lines=3, ellipsize=3, selectable=False)
        name.set_tooltip_text(item.display_name)
        body.append(name)
        body.append(_label(self._meta(), "dim-label", wrap=True, justify=Gtk.Justification.CENTER))

        details = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=16)
        details.add_css_class("boxed-list")
        home = os.path.expanduser("~")
        where = item.path if site else item.folder
        details.append(Adw.ActionRow(title="Saved in", subtitle=where.replace(home, "~", 1), subtitle_selectable=True))
        if item.is_clip:
            details.append(Adw.ActionRow(title="Only this part", subtitle=clip_text(item)))
        if site and item.files_failed:
            details.append(Adw.ActionRow(
                title=f"{item.files_failed} file{'s' if item.files_failed != 1 else ''} couldn't be saved",
                subtitle="They're listed in _tondar-failed.txt in the website's folder"))
        body.append(details)
        self.toasts.set_child(body)
        view.set_content(self.toasts)

        buttons = Gtk.Box(spacing=10, homogeneous=True, margin_top=4, margin_bottom=20, margin_start=28, margin_end=28)
        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda *_: self.close())
        folder = Gtk.Button()
        folder.set_child(Adw.ButtonContent(icon_name="folder-open-symbolic", label="Open Folder"))
        folder.connect("clicked", lambda *_: self._open_folder())
        self.open_btn = Gtk.Button()
        self.open_btn.set_child(Adw.ButtonContent(icon_name=_open_icon(item, site),
                                                  label="Open Website" if site else "Open"))
        self.open_btn.add_css_class("suggested-action")
        self.open_btn.connect("clicked", lambda *_: self._open())
        for b in (close, folder, self.open_btn):
            b.add_css_class("pill")
            buttons.append(b)
        view.add_bottom_bar(buttons)
        self.set_content(view)
        self.set_default_widget(self.open_btn)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                          Gtk.CallbackAction.new(lambda *_: self.close() or True)))
        self.add_controller(esc)
        GLib.idle_add(lambda: self.open_btn.grab_focus() and False)

    def _meta(self):
        it = self.item
        parts = []
        if it.kind == "site":
            parts.append(f"{it.files_done} files")
            parts.append(human_size(it.size if it.size > 0 else it.done))
            parts.append(_host(it.url))
        else:
            if it.size > 0:
                parts.append(human_size(it.size))
            parts.append(_type_label(it))
            parts.append(_host(it.page_url or it.url))
        if it.finished and it.created and it.finished > it.created:
            took = it.finished - it.created
            if took < 24 * 3600:
                parts.append(f"took {human_time(took)}")
        return "  ·  ".join(p for p in parts if p)

    def _open(self):
        from .window import open_uri

        path = self.item.open_path
        if os.path.exists(path):
            open_uri(path, self)
            self.close()
        else:
            self.toasts.add_toast(Adw.Toast(title="The file was moved or deleted"))

    def _open_folder(self):
        from .window import open_folder, open_uri

        it = self.item
        if it.kind == "site" and os.path.isdir(it.path):
            open_uri(it.path, self)
        elif os.path.exists(it.path):
            open_folder(it.path, self)
        elif os.path.isdir(it.folder):
            open_uri(it.folder, self)
        else:
            self.toasts.add_toast(Adw.Toast(title="The folder was moved or deleted"))
            return
        self.close()

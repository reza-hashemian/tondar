"""The "Updates & News" window (GitHub releases, star, Telegram channel) and the
occasional reminder in the main window to follow the channel."""

import os
import random
import time

from gi.repository import Adw, Gdk, GLib, Gtk

from . import APP_ID, VERSION

GITHUB_URL = "https://github.com/reza-hashemian/tondar"
RELEASES_URL = GITHUB_URL + "/releases/latest"
TELEGRAM_URL = "https://t.me/RezaUplink"
TELEGRAM_NAME = "@RezaUplink"

REMINDER_EVERY = 4 * 24 * 3600  # seconds between two reminders
REMINDER_DELAY = 20  # seconds the window is open before one shows

GITHUB_LOGO = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
<rect width="48" height="48" rx="12" fill="#24292f"/>
<g transform="translate(10 10) scale(1.75)"><path fill="#fff" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></g>
</svg>"""

TELEGRAM_LOGO = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">
<defs><linearGradient id="g" x1="0.5" y1="0" x2="0.5" y2="1">
<stop offset="0" stop-color="#2AABEE"/><stop offset="1" stop-color="#229ED9"/></linearGradient></defs>
<circle cx="120" cy="120" r="120" fill="url(#g)"/>
<path fill="#fff" d="M54.3 118.8c35-15.2 58.3-25.3 70-30.2 33.3-13.9 40.3-16.3 44.8-16.4 1 0 3.2.2 4.7 1.4 1.2 1 1.5 2.3 1.7 3.3s.4 3.1.2 4.7c-1.8 19-9.6 65.1-13.6 86.3-1.7 9-5 12-8.2 12.3-7 .6-12.3-4.6-19-9-10.6-6.9-16.5-11.2-26.8-18-11.9-7.8-4.2-12.1 2.6-19.1 1.8-1.8 32.5-29.8 33.1-32.3.1-.3.1-1.5-.6-2.1-.7-.6-1.7-.4-2.5-.2-1.1.2-17.9 11.4-50.6 33.5-4.8 3.3-9.1 4.9-13 4.8-4.3-.1-12.5-2.4-18.7-4.4-7.5-2.4-13.5-3.7-13-7.9.3-2.2 3.3-4.4 8.9-6.7z"/>
</svg>"""

# (text, button, url) shown now and then at the bottom of the main window.
REMINDERS = [
    (f"📢 Follow {TELEGRAM_NAME} on Telegram for Tondar news and new versions", "Join", TELEGRAM_URL),
    (f"🚀 New features land first on {TELEGRAM_NAME} — follow the channel", "Join", TELEGRAM_URL),
    ("⭐ Enjoying Tondar? A star on GitHub helps others find it", "Star", GITHUB_URL),
]


def logo(svg, size):
    try:
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg))
    except GLib.Error:  # no SVG loader: a plain icon instead
        return Gtk.Image(icon_name="emblem-favorite-symbolic", pixel_size=size)
    return Gtk.Image(paintable=texture, pixel_size=size)


def app_icon(size):
    """Tondar's icon; from the source tree when it isn't installed (running from a checkout)."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    for name in (APP_ID, "io.github.tondar.Tondar"):
        if theme.has_icon(name):
            return Gtk.Image(icon_name=name, pixel_size=size)
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "io.github.tondar.Tondar.svg")
    if os.path.exists(path):
        return Gtk.Image(file=path, pixel_size=size)
    return Gtk.Image(icon_name="folder-download-symbolic", pixel_size=size)


def open_url(url):
    from .window import open_url as _open

    _open(url)


class CommunityDialog(Adw.Dialog):
    def __init__(self, app):
        super().__init__(title="Updates & News", content_width=480)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=6, margin_bottom=24, margin_start=24, margin_end=24)

        # Version and update check
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top.append(app_icon(88))
        title = Gtk.Label(label="Tondar")
        title.add_css_class("title-1")
        top.append(title)
        version = Gtk.Label(label=f"Version {VERSION}")
        version.add_css_class("dim-label")
        top.append(version)
        box.append(top)

        update = Gtk.Button(halign=Gtk.Align.CENTER)
        update.set_child(Adw.ButtonContent(icon_name="software-update-available-symbolic",
                                           label="Get the Latest Version"))
        update.add_css_class("pill")
        update.add_css_class("suggested-action")
        update.connect("clicked", lambda *_: open_url(RELEASES_URL))
        box.append(update)
        hint = Gtk.Label(label="New versions are published on GitHub. Compare the version above with the "
                               "newest one there and download it if yours is older.",
                         wrap=True, justify=Gtk.Justification.CENTER)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)

        # Support
        group = Adw.PreferencesGroup(
            title="Support Tondar ❤",
            description="Tondar is free and made by one developer in their spare time. "
                        "A star and a follow take a few seconds and keep it going.",
        )
        group.add(self._link_row(
            GITHUB_LOGO, "Give Tondar a Star on GitHub",
            "Free and open source. Every ⭐ helps more people find it.", "Star", GITHUB_URL))
        group.add(self._link_row(
            TELEGRAM_LOGO, f"Join {TELEGRAM_NAME} on Telegram",
            "News, new versions and tips — be the first to know.", "Join", TELEGRAM_URL))
        box.append(group)

        thanks = Gtk.Label(label="Thank you for using Tondar! 🙏", margin_top=6)
        thanks.add_css_class("dim-label")
        box.append(thanks)

        view.set_content(Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                            propagate_natural_height=True))
        self.set_child(view)

    def _link_row(self, svg, title, subtitle, button, url):
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
        icon = logo(svg, 40)
        icon.set_margin_top(6)
        icon.set_margin_bottom(6)
        row.add_prefix(icon)
        btn = Gtk.Button(label=button, valign=Gtk.Align.CENTER)
        btn.add_css_class("pill")
        btn.connect("clicked", lambda *_: open_url(url))
        row.add_suffix(btn)
        row.connect("activated", lambda *_: open_url(url))
        return row


class Reminder:
    """Now and then (every few days, after the main window has been open a little while)
    a toast asks to follow the Telegram channel or star the project."""

    def __init__(self, window):
        self.window = window
        self.settings = window.manager.settings
        self.visible_since = None
        if not self.settings.get("support_last"):
            # Not on the very first day.
            self.settings["support_last"] = time.time()
            window.manager.save_settings()

    def tick(self):
        now = time.time()
        if self.visible_since is None:
            self.visible_since = now
        if now - self.visible_since < REMINDER_DELAY:
            return
        if now - float(self.settings.get("support_last") or 0) < REMINDER_EVERY:
            return
        self.settings["support_last"] = now
        self.window.manager.save_settings()
        text, button, url = random.choice(REMINDERS)
        toast = Adw.Toast(title=text, button_label=button, timeout=12, priority=Adw.ToastPriority.HIGH)
        toast.connect("button-clicked", lambda *_: open_url(url))
        self.window.toasts.add_toast(toast)

    def hidden(self):
        self.visible_since = None

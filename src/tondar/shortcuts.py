"""The "Keyboard Shortcuts" window (Ctrl+? or F1)."""

from gi.repository import Adw, Gtk

from .util import MACOS

SHORTCUTS = [
    ("Downloads", [
        ("<Primary>n", "New download"),
        ("<Primary>v", "New download with the copied link"),
        ("<Primary><Shift>n", "Clone a website"),
        ("<Primary>r", "Resume all"),
        ("<Primary>p", "Pause all"),
        ("<Primary><Shift>BackSpace", "Remove completed from the list"),
        ("<Primary><Shift>Delete", "Remove all queued"),
    ]),
    ("Finding", [
        ("<Primary>f", "Search downloads"),
        ("<Primary>1", "All downloads"),
        ("<Primary>2", "Downloading"),
        ("<Primary>3", "Unfinished"),
        ("<Primary>4", "Completed"),
        ("<Primary>5", "Scheduled"),
        ("<Primary>6", "Video  (Ctrl+7 Music, Ctrl+8 Compressed…)"),
    ]),
    ("Windows", [
        ("<Primary>comma", "Preferences"),
        ("<Primary>j", "Scheduler"),
        ("<Primary>b", "Browser integration"),
        ("<Primary>question", "Keyboard shortcuts"),
        ("<Primary>w", "Close the window (downloads keep going)"),
        ("<Primary>q", "Quit Tondar"),
    ]),
]


def _keys(accel):
    try:
        return Gtk.ShortcutLabel(accelerator=accel, valign=Gtk.Align.CENTER)
    except (AttributeError, TypeError):  # removed from a future GTK: plain text instead
        ok, key, mods = Gtk.accelerator_parse(accel)
        label = Gtk.Label(label=Gtk.accelerator_get_label(key, mods) if ok else accel)
        label.add_css_class("dim-label")
        return label


class ShortcutsDialog(Adw.Dialog):
    def __init__(self):
        super().__init__(title="Keyboard Shortcuts", content_width=520, content_height=640)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        for title, items in SHORTCUTS:
            group = Adw.PreferencesGroup(title=title)
            for accel, text in items:
                row = Adw.ActionRow(title=text)
                row.add_suffix(_keys(accel))
                group.add(row)
            page.add(group)
        if MACOS:
            page.set_description("Ctrl means ⌘ Command on a Mac.")
        view.set_content(page)
        self.set_child(view)

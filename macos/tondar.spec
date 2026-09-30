# PyInstaller spec for the macOS build (run from the repository root with Homebrew's GTK 4):
#   pyinstaller --noconfirm macos/tondar.spec
# Produces dist/Tondar.app with Contents/MacOS/Tondar (the app) and tondar-native-host (browser bridge).
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")
with open(os.path.join(SRC, "tondar", "__init__.py")) as f:
    VERSION = re.search(r'^VERSION = "(.+)"', f.read(), re.M).group(1)

gi_config = {
    "gi": {
        "icons": ["Adwaita", "hicolor"],
        "themes": ["Adwaita"],
        "languages": ["en_US"],
        "module-versions": {"Gtk": "4.0", "Gdk": "4.0", "Gsk": "4.0"},
    },
}

app = Analysis(
    [os.path.join(ROOT, "windows", "run_tondar.py")],
    pathex=[SRC],
    hiddenimports=["gi.repository.Gtk", "gi.repository.Adw", "gi.repository.Gio", "gi.repository.GLib"],
    hooksconfig=gi_config,
    datas=[
        (os.path.join(ROOT, "data", "io.github.tondar.Tondar.svg"), "share/icons/hicolor/scalable/apps"),
    ],
    excludes=["tkinter"],
)

host = Analysis(
    [os.path.join(ROOT, "native-host", "tondar_native_host.py")],
    pathex=[SRC],
    hiddenimports=["tondar.ipc"],
    excludes=["gi", "tkinter"],
)

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="Tondar", console=False)
host_exe = EXE(PYZ(host.pure), host.scripts, [], exclude_binaries=True, name="tondar-native-host", console=True)

coll = COLLECT(
    app_exe, app.binaries, app.datas,
    host_exe, host.binaries, host.datas,
    name="Tondar",
)

BUNDLE(
    coll,
    name="Tondar.app",
    icon=os.path.join(ROOT, "build", "Tondar.icns"),
    bundle_identifier="io.github.tondar.Tondar",
    version=VERSION,
    info_plist={
        "CFBundleName": "Tondar",
        "CFBundleDisplayName": "Tondar",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)

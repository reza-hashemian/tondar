# PyInstaller spec for the Windows build (run from the repository root inside MSYS2 UCRT64):
#   pyinstaller --noconfirm windows/tondar.spec
# Produces dist/Tondar/ with Tondar.exe (the app) and tondar-native-host.exe (browser bridge).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

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
)

host = Analysis(
    [os.path.join(ROOT, "native-host", "tondar_native_host.py")],
    pathex=[SRC],
    hiddenimports=["tondar.ipc"],
    excludes=["gi", "tkinter"],
)

app_exe = EXE(
    PYZ(app.pure), app.scripts, [],
    exclude_binaries=True, name="Tondar", console=False,
    icon=os.path.join(ROOT, "data", "tondar.ico"),
)
host_exe = EXE(
    PYZ(host.pure), host.scripts, [],
    exclude_binaries=True, name="tondar-native-host", console=True,
)

COLLECT(
    app_exe, app.binaries, app.datas,
    host_exe, host.binaries, host.datas,
    name="Tondar",
)

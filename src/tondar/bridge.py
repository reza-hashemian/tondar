"""Tell the installed browsers where the native messaging bridge is (macOS and Linux).

Windows does this in the installer (registry keys). On Linux the .deb already covers Chrome,
Chromium, Edge and Firefox system-wide; Brave, Opera, Vivaldi and Yandex only read their own
per-user folder, so those manifests are written here each time Tondar starts.
"""

import json
import os
import sys

CHROME_ID = "beoabpicfajnboiblppakbnbmlhbkgpf"
FIREFOX_ID = "tondar@tondar.dm"
LINUX_HOST = "/usr/lib/tondar/tondar-native-host"

# Each browser's user-data folder; NativeMessagingHosts goes inside it.
MAC_CHROMIUM = ["Google/Chrome", "Chromium", "Microsoft Edge", "BraveSoftware/Brave-Browser", "Vivaldi",
                "com.operasoftware.Opera", "com.operasoftware.OperaGX", "Yandex/YandexBrowser"]
LINUX_CHROMIUM = ["google-chrome", "chromium", "microsoft-edge", "BraveSoftware/Brave-Browser", "vivaldi",
                  "opera", "yandex-browser"]


def _write(folder, manifest):
    path = os.path.join(folder, "com.tondar.host.json")
    text = json.dumps(manifest, indent=2)
    try:
        with open(path) as f:
            if f.read() == text:
                return
    except OSError:
        pass
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    except OSError:
        pass


def register(host):
    """Write the bridge manifest for every browser that has a profile on this computer."""
    if not os.path.exists(host):
        return
    base = {"name": "com.tondar.host", "description": "Tondar Download Manager", "path": host, "type": "stdio"}
    chromium = dict(base, allowed_origins=[f"chrome-extension://{CHROME_ID}/"])
    if sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
        for browser in MAC_CHROMIUM:
            # Chrome's folder is written even before Chrome first runs: Opera reads it too.
            if browser == "Google/Chrome" or os.path.isdir(os.path.join(root, browser)):
                _write(os.path.join(root, browser, "NativeMessagingHosts"), chromium)
        _write(os.path.join(root, "Mozilla", "NativeMessagingHosts"), dict(base, allowed_extensions=[FIREFOX_ID]))
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        for browser in LINUX_CHROMIUM:
            if os.path.isdir(os.path.join(root, browser)):
                _write(os.path.join(root, browser, "NativeMessagingHosts"), chromium)


def register_installed():
    """Called at startup: the bundled bridge on macOS, the .deb's bridge on Linux."""
    if sys.platform == "darwin":
        if getattr(sys, "frozen", False):
            register(os.path.join(os.path.dirname(sys.executable), "tondar-native-host"))
    elif sys.platform != "win32":
        register(LINUX_HOST)

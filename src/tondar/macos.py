"""macOS integration for the Tondar.app build: browser bridge, login item, focus."""

import ctypes
import json
import os
import plistlib
import sys

from . import APP_ID

CHROME_ID = "beoabpicfajnboiblppakbnbmlhbkgpf"
FIREFOX_ID = "tondar@tondar.dm"
SUPPORT = os.path.expanduser("~/Library/Application Support")
# Browser profile folders under ~/Library/Application Support that read Chrome-style manifests
CHROMIUM_BROWSERS = ["Google/Chrome", "Chromium", "Microsoft Edge", "BraveSoftware/Brave-Browser", "Vivaldi"]
LAUNCH_AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{APP_ID}.plist")


def executable(name):
    """A program in Tondar.app/Contents/MacOS."""
    return os.path.join(os.path.dirname(sys.executable), name)


def register_native_host():
    """Point the installed browsers at the bridge inside the app, wherever the app was copied to."""
    host = executable("tondar-native-host")
    if not os.path.exists(host):
        return
    base = {"name": "com.tondar.host", "description": "Tondar Download Manager", "path": host, "type": "stdio"}
    targets = [(b, dict(base, allowed_origins=[f"chrome-extension://{CHROME_ID}/"])) for b in CHROMIUM_BROWSERS]
    targets.append(("Mozilla", dict(base, allowed_extensions=[FIREFOX_ID])))
    for browser, manifest in targets:
        if browser not in ("Google/Chrome", "Mozilla") and not os.path.isdir(os.path.join(SUPPORT, browser)):
            continue
        folder = os.path.join(SUPPORT, browser, "NativeMessagingHosts")
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "com.tondar.host.json"), "w") as f:
                json.dump(manifest, f, indent=2)
        except OSError:
            pass


def set_login_item(enabled):
    if not enabled:
        if os.path.exists(LAUNCH_AGENT):
            os.unlink(LAUNCH_AGENT)
        return
    os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
    with open(LAUNCH_AGENT, "wb") as f:
        plistlib.dump({"Label": APP_ID, "ProgramArguments": [sys.executable, "--background"],
                       "RunAtLoad": True, "ProcessType": "Interactive"}, f)


def activate():
    """[NSApp activateIgnoringOtherApps:YES] — macOS doesn't bring a background app forward by itself."""
    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    except OSError:
        return
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    send = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
    send_bool = ctypes.cast(objc.objc_msgSend,
                            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool))
    app = send(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))
    if app:
        send_bool(app, objc.sel_registerName(b"activateIgnoringOtherApps:"), True)

"""macOS integration for the Tondar.app build: login item, focus."""

import ctypes
import os
import plistlib
import sys

from . import APP_ID

LAUNCH_AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{APP_ID}.plist")


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

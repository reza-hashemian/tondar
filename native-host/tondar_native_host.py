#!/usr/bin/python3
"""Native messaging bridge: browser extension -> Tondar app.

The browser starts this program for each message. It passes the download to the
running Tondar instance (starting it in the background if needed) and exits.
Installed as /usr/lib/tondar/tondar-native-host on Linux, as tondar-native-host.exe
next to Tondar.exe on Windows and next to Tondar in Tondar.app/Contents/MacOS on macOS.
"""
import base64
import json
import os
import shutil
import struct
import subprocess
import sys

VERSION = "1.3.1"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    (length,) = struct.unpack("=I", raw)
    return json.loads(sys.stdin.buffer.read(length))


def send(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("=I", len(data)) + data)
    sys.stdout.buffer.flush()


def tondar_command():
    if getattr(sys, "frozen", False):  # Windows/macOS build: the app sits next to us
        return [os.path.join(os.path.dirname(sys.executable), "Tondar.exe" if WINDOWS else "Tondar")]
    exe = shutil.which("tondar") or ("/usr/bin/tondar" if os.path.exists("/usr/bin/tondar") else None)
    if exe:
        return [exe]
    src = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "src")
    return [sys.executable, "-c", f"import sys; sys.path.insert(0, {src!r}); from tondar.app import main; sys.exit(main(sys.argv))"]


def launch(args):
    cmd = tondar_command() + args
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if not WINDOWS:
        subprocess.Popen(cmd, start_new_session=True, **quiet)
        return
    # Browsers run native hosts inside a job that is killed when we exit; the app must break away.
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **quiet)
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **quiet)


def main():
    msg = read_message() or {}
    cmd = msg.get("cmd")
    if cmd == "ping":
        send({"ok": True, "version": VERSION})
    elif cmd == "add" and isinstance(msg.get("item"), dict):
        payload = base64.urlsafe_b64encode(json.dumps(msg["item"]).encode()).decode().rstrip("=")
        args = ["--add", payload]
        if WINDOWS or MACOS:
            if WINDOWS:
                # We were started by the browser, which has the focus: pass the right to take it to Tondar.
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            from tondar import ipc  # bundled into the .exe

            if not ipc.forward(args):
                launch(args)
        else:
            launch(args)
        send({"ok": True})
    else:
        send({"ok": False, "error": "unknown command"})


if __name__ == "__main__":
    main()

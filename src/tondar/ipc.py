"""Single-instance support for Windows and macOS (Linux uses D-Bus through Gio.Application).

The running instance listens on 127.0.0.1 and writes the port plus a random token to a
file only this user can read. A second launch sends its command line there and exits.

A lock file closes the gap while the first instance is still starting up: before, two quick
clicks in the browser could start two copies of Tondar on the same downloads list. One copy
downloaded a file while the other kept showing it as "Waiting in queue".
"""

import json
import os
import secrets
import socket
import sys
import threading
import time

from .util import data_dir

_lock_file = None  # kept open (and locked) for as long as this instance runs


def _try_lock(f):
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def acquire_instance(args, wait=30):
    """Become the only running instance, or hand `args` to the one that runs.

    Returns True when this process should start the app, False when another instance took
    over (or is starting and got the arguments)."""
    global _lock_file
    if forward(args):
        return False
    f = open(os.path.join(data_dir(), "instance.lock"), "a+")
    deadline = time.monotonic() + wait
    while not _try_lock(f):
        # Another instance holds the lock: it is starting up. Hand over as soon as it listens.
        time.sleep(0.2)
        if forward(args):
            f.close()
            return False
        if time.monotonic() > deadline:
            f.close()
            return False  # the other instance hangs; a second copy would only make things worse
    _lock_file = f
    return True


def _info_file():
    return os.path.join(data_dir(), "instance.json")


def forward(args):
    """Send args to the running instance. Returns True if one received them."""
    try:
        with open(_info_file()) as f:
            info = json.load(f)
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=3) as s:
            s.sendall(json.dumps({"token": info["token"], "args": args}).encode() + b"\n")
            return s.makefile().readline().strip() == "ok"
    except (OSError, ValueError, KeyError):
        return False


def serve(on_args):
    """Start listening in a background thread. on_args(list) is called from that thread."""
    token = secrets.token_hex(16)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    tmp = _info_file() + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"port": server.getsockname()[1], "token": token}, f)
    os.replace(tmp, _info_file())  # a second launch must never read half a file

    def handle(conn):
        with conn:
            try:
                conn.settimeout(5)
                msg = json.loads(conn.makefile().readline())
                if not secrets.compare_digest(str(msg.get("token", "")), token):
                    return
                conn.sendall(b"ok\n")
                on_args([str(a) for a in msg.get("args", [])])
            except (OSError, ValueError):
                pass

    def loop():
        while True:
            conn, _ = server.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()

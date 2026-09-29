"""Single-instance support for Windows (Linux uses D-Bus through Gio.Application).

The running instance listens on 127.0.0.1 and writes the port plus a random token to a
file only this user can read. A second launch sends its command line there and exits.
"""

import json
import os
import secrets
import socket
import threading

from .util import data_dir


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
    with open(_info_file(), "w") as f:
        json.dump({"port": server.getsockname()[1], "token": token}, f)

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

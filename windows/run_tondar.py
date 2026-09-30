# Entry point for the PyInstaller (Windows) build.
import os
import sys

if sys.stderr is None:  # windowed build: keep tracebacks somewhere they can be found
    _log = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Tondar", "tondar.log")
    os.makedirs(os.path.dirname(_log), exist_ok=True)
    if os.path.exists(_log) and os.path.getsize(_log) > 1024 * 1024:
        os.replace(_log, _log + ".old")
    sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

from tondar.app import main  # noqa: E402

sys.exit(main(sys.argv))

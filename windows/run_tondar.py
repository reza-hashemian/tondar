# Entry point for the PyInstaller (Windows and macOS) builds.
import os
import sys

if "--profile" in sys.argv:
    # GTK's own notes on how it picks its drawing mode (read when GTK starts, so set them first).
    os.environ.setdefault("GDK_DEBUG", "opengl:vulkan")
    os.environ.setdefault("GSK_DEBUG", "renderer")
    if sys.platform == "win32":
        # A windowed program starts with the C runtime's stderr switched off, and GTK writes its
        # messages there: point it at a file (tondar/profiling.py copies it into the report).
        try:
            import ctypes

            _dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Tondar")
            os.makedirs(_dir, exist_ok=True)
            _crt = ctypes.CDLL("ucrtbase")
            _crt.__acrt_iob_func.restype = ctypes.c_void_p
            _crt.__acrt_iob_func.argtypes = [ctypes.c_uint]
            _crt._wfreopen.restype = ctypes.c_void_p
            _crt._wfreopen.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
            _crt.setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_size_t]
            _stream = _crt._wfreopen(os.path.join(_dir, "profile-gtk.txt"), "w", _crt.__acrt_iob_func(2))
            if _stream:
                _crt.setvbuf(_stream, None, 4, 0)  # _IONBF: write each message at once
        except Exception:  # noqa: BLE001
            pass

if sys.stderr is None:  # windowed build: keep tracebacks somewhere they can be found
    if sys.platform == "darwin":
        _log = os.path.expanduser("~/Library/Logs/Tondar/tondar.log")
    else:
        _log = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Tondar", "tondar.log")
    os.makedirs(os.path.dirname(_log), exist_ok=True)
    if os.path.exists(_log) and os.path.getsize(_log) > 1024 * 1024:
        os.replace(_log, _log + ".old")
    sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

from tondar.app import main  # noqa: E402

sys.exit(main(sys.argv))

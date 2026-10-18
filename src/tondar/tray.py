"""An icon in the notification area (Windows) / system tray (Linux) with a right-click menu.

Windows: Shell_NotifyIcon through ctypes, run by a hidden window in its own thread.
Linux: a StatusNotifierItem with a com.canonical.dbusmenu menu over D-Bus (KDE, Xfce, Cinnamon,
MATE, Budgie, Ubuntu's GNOME; plain GNOME needs the "AppIndicator" extension).
Menu clicks run the app's actions ("app.add", "app.quit", …) on the GTK main thread.
"""

import os
import sys
import threading

from gi.repository import Gio, GLib

from .util import WINDOWS

# (label, action) — None is a separator
MENU = [
    ("Show Tondar", "show"),
    None,
    ("New Download…", "add"),
    ("Clone Website…", "clone"),
    None,
    ("Resume All", "start-all"),
    ("Pause All", "pause-all"),
    None,
    ("Preferences", "preferences"),
    None,
    ("Quit Tondar", "quit"),
]


def create(app):
    """Start the tray icon for `app`; returns an object with set_tooltip(text) and remove(), or None."""
    try:
        if WINDOWS:
            return WindowsTray(app)
        if sys.platform.startswith("linux") or "bsd" in sys.platform:
            return StatusNotifier(app)
    except Exception as e:  # noqa: BLE001 - a missing tray must never stop the app
        print(f"Tondar: no tray icon: {e}", file=sys.stderr)
    return None


def _run_action(app, name):
    def run():
        app.activate_action(name, None)
        return False

    GLib.idle_add(run)


# --- Windows ------------------------------------------------------------------------------------
class WindowsTray:
    WM_USER, WM_CLOSE, WM_DESTROY, WM_NULL = 0x0400, 0x0010, 0x0002, 0
    WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4

    def __init__(self, app):
        import ctypes
        from ctypes import wintypes as wt

        self.app = app
        self.ct, self.wt = ctypes, wt
        self.tip = "Tondar"
        self.hwnd = None
        self.callback_msg = self.WM_USER + 20
        user32, shell32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("shell32")
        self.user32, self.shell32 = user32, shell32
        LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", self.WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                        ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                        ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                        ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                        ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

        self.WNDCLASSEXW, self.NOTIFYICONDATAW, self.POINT = WNDCLASSEXW, NOTIFYICONDATAW, POINT
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.CreateWindowExW.restype = wt.HWND
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        user32.RegisterClassExW.restype = wt.ATOM
        user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
        user32.RegisterWindowMessageW.restype = wt.UINT
        user32.CreatePopupMenu.restype = wt.HMENU
        user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.DestroyMenu.argtypes = [wt.HMENU]
        user32.SetMenuDefaultItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
        user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
        user32.LoadImageW.restype = wt.HANDLE
        self.kernel32 = ctypes.WinDLL("kernel32")
        self.kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wt.HMODULE
        user32.SetForegroundWindow.argtypes = [wt.HWND]
        user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.LoadIconW.argtypes = [wt.HINSTANCE, wt.LPVOID]
        user32.LoadIconW.restype = wt.HICON
        shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wt.BOOL
        shell32.ExtractIconExW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.HICON),
                                           ctypes.POINTER(wt.HICON), wt.UINT]
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.icon = self._load_icon()
        ready = threading.Event()
        threading.Thread(target=self._thread, args=(ready,), daemon=True, name="tray").start()
        ready.wait(5)
        if not self.hwnd:
            raise OSError("couldn't create the tray window")

    def _load_icon(self):
        ct, wt = self.ct, self.wt
        small, large = wt.HICON(), wt.HICON()
        exe = sys.executable if getattr(sys, "frozen", False) else ""
        if exe and self.shell32.ExtractIconExW(exe, 0, ct.byref(large), ct.byref(small), 1) and small.value:
            return small
        ico = os.path.join(os.path.dirname(__file__), "..", "..", "data", "tondar.ico")
        if os.path.exists(ico):
            h = self.user32.LoadImageW(None, os.path.abspath(ico), 1, 16, 16, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                return wt.HICON(h)
        return self.user32.LoadIconW(None, ct.c_void_p(32512))  # IDI_APPLICATION

    def _data(self, flags):
        nid = self.NOTIFYICONDATAW()
        nid.cbSize = self.ct.sizeof(self.NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags = self.hwnd, 1, flags
        nid.uCallbackMessage = self.callback_msg
        nid.hIcon = self.icon
        nid.szTip = self.tip[:127]
        return nid

    def _add(self):
        nid = self._data(self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP)
        self.shell32.Shell_NotifyIconW(self.NIM_ADD, self.ct.byref(nid))

    def _thread(self, ready):
        ct, user32 = self.ct, self.user32
        self._proc = self.WNDPROC(self._wndproc)  # keep a reference: ctypes callbacks must stay alive
        hinst = self.kernel32.GetModuleHandleW(None)
        wc = self.WNDCLASSEXW()
        wc.cbSize = ct.sizeof(self.WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "TondarTrayWindow"
        user32.RegisterClassExW(ct.byref(wc))
        # A real (hidden) top-level window: message-only windows don't get "TaskbarCreated".
        self.hwnd = user32.CreateWindowExW(0, "TondarTrayWindow", "Tondar", 0, 0, 0, 0, 0, None, None, hinst, None)
        if self.hwnd:
            self._add()
        ready.set()
        msg = (ct.c_byte * 64)()
        while user32.GetMessageW(msg, None, 0, 0) > 0:
            user32.TranslateMessage(msg)
            user32.DispatchMessageW(msg)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self.callback_msg:
                event = lparam & 0xFFFF
                if event in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                    _run_action(self.app, "show")
                elif event in (self.WM_RBUTTONUP, self.WM_CONTEXTMENU):
                    self._menu(hwnd)
                return 0
            if msg == self.taskbar_created and msg:
                self._add()  # Explorer restarted: the icon is gone
                return 0
            if msg == self.WM_CLOSE:
                self.user32.DestroyWindow(hwnd)
                return 0
            if msg == self.WM_DESTROY:
                self.user32.PostQuitMessage(0)
                return 0
        except Exception as e:  # noqa: BLE001
            print(f"Tondar tray: {e}", file=sys.stderr)
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self, hwnd):
        user32 = self.user32
        menu = user32.CreatePopupMenu()
        actions = {}
        for n, entry in enumerate(MENU, start=1):
            if entry is None:
                user32.AppendMenuW(menu, 0x0800, 0, None)  # MF_SEPARATOR
            else:
                actions[n] = entry[1]
                user32.AppendMenuW(menu, 0, n, entry[0])  # MF_STRING
        user32.SetMenuDefaultItem(menu, 1, 0)  # "Show Tondar" in bold, like other apps
        pt = self.POINT()
        user32.GetCursorPos(self.ct.byref(pt))
        user32.SetForegroundWindow(hwnd)  # else the menu doesn't close when clicking elsewhere
        cmd = user32.TrackPopupMenu(menu, 0x0100 | 0x0080 | 0x0002, pt.x, pt.y, 0, hwnd, None)  # RETURNCMD|NONOTIFY|RIGHTBUTTON
        user32.PostMessageW(hwnd, self.WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd in actions:
            _run_action(self.app, actions[cmd])

    def set_tooltip(self, text):
        if text == self.tip or not self.hwnd:
            return
        self.tip = text
        nid = self._data(self.NIF_TIP)
        self.shell32.Shell_NotifyIconW(self.NIM_MODIFY, self.ct.byref(nid))

    def remove(self):
        if not self.hwnd:
            return
        nid = self._data(0)
        self.shell32.Shell_NotifyIconW(self.NIM_DELETE, self.ct.byref(nid))
        self.user32.PostMessageW(self.hwnd, self.WM_CLOSE, 0, 0)
        self.hwnd = None


# --- Linux: StatusNotifierItem + dbusmenu ----------------------------------------------------------
SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/><arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/><arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/><arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/><arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/><arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/><arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/><arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/><arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/><arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/><arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
    <signal name="ItemActivationRequested"><arg type="i" name="id"/><arg type="u" name="timestamp"/></signal>
  </interface>
</node>
"""

WATCHER = "org.kde.StatusNotifierWatcher"


class StatusNotifier:
    def __init__(self, app):
        from . import APP_ID

        self.app = app
        self.icon = APP_ID
        self.tip = "Tondar"
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._ids = [
            self.bus.register_object("/StatusNotifierItem", sni, self._sni_call, self._sni_get, None),
            self.bus.register_object("/MenuBar", menu, self._menu_call, self._menu_get, None),
        ]
        self._owner = Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        # Register now and whenever a panel (the watcher) starts or restarts.
        self._watch = Gio.bus_watch_name_on_connection(
            self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE, lambda *_: self._register(), None)

    def _register(self):
        self.bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None, None)

    # org.kde.StatusNotifierItem
    def _sni_get(self, _conn, _sender, _path, _iface, prop):
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "tondar"),
            "Title": GLib.Variant("s", "Tondar"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", self.icon),
            "IconThemePath": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (self.icon, [], "Tondar", self.tip if self.tip != "Tondar" else "")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/MenuBar"),
        }
        return values.get(prop)

    def _sni_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            _run_action(self.app, "show")
        invocation.return_value(None)

    # com.canonical.dbusmenu
    def _menu_get(self, _conn, _sender, _path, _iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    @staticmethod
    def _props(n):
        entry = MENU[n - 1]
        if entry is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", entry[0]), "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True)}

    def _layout(self):
        children = [GLib.Variant("(ia{sv}av)", (n, self._props(n), [])) for n in range(1, len(MENU) + 1)]
        return (0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, self._layout())))
        elif method == "GetGroupProperties":
            ids = params.unpack()[0] or range(1, len(MENU) + 1)
            props = [(n, self._props(n)) for n in ids if 1 <= n <= len(MENU)]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (props,)))
        elif method == "GetProperty":
            n, name = params.unpack()
            value = self._props(n).get(name) if 1 <= n <= len(MENU) else None
            invocation.return_value(GLib.Variant("(v)", (value or GLib.Variant("s", ""),)))
        elif method == "Event":
            n, event = params.unpack()[:2]
            self._clicked(n, event)
            invocation.return_value(None)
        elif method == "EventGroup":
            for n, event, *_ in params.unpack()[0]:
                self._clicked(n, event)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _clicked(self, n, event):
        if event == "clicked" and 1 <= n <= len(MENU) and MENU[n - 1]:
            _run_action(self.app, MENU[n - 1][1])

    def set_tooltip(self, text):
        if text != self.tip:
            self.tip = text
            self.bus.emit_signal(None, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewToolTip", None)

    def remove(self):
        Gio.bus_unwatch_name(self._watch)
        for i in self._ids:
            self.bus.unregister_object(i)
        Gio.bus_unown_name(self._owner)

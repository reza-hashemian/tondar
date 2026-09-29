"""Proxy support: resolving which proxy to use and a built-in SOCKS5 client for urllib."""

import http.client
import socket
import time
import urllib.parse
import urllib.request


def proxy_url(settings, target_url=""):
    """Return the proxy URL to use for target_url ("http://…", "socks5://…"), or None for direct."""
    mode = settings.get("proxy_mode", "system")
    if mode == "none":
        return None
    if mode == "manual":
        host = (settings.get("proxy_host") or "").strip()
        if not host:
            return None
        scheme = "socks5" if settings.get("proxy_type") == "socks5" else "http"
        auth = ""
        if settings.get("proxy_user"):
            auth = urllib.parse.quote(settings["proxy_user"], safe="")
            if settings.get("proxy_pass"):
                auth += ":" + urllib.parse.quote(settings["proxy_pass"], safe="")
            auth += "@"
        return f"{scheme}://{auth}{host}:{int(settings.get('proxy_port') or 8080)}"
    return _system_proxy(target_url or "https://example.com/")


def _system_proxy(target_url):
    try:  # GNOME proxy settings (Settings → Network → Proxy)
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        first = Gio.ProxyResolver.get_default().lookup(target_url, None)[0]
        if first.startswith("direct"):
            return None
        return "socks5://" + first.split("://", 1)[1] if first.startswith(("socks://", "socks4")) else first
    except Exception:  # noqa: BLE001 - fall back to environment variables
        scheme = urllib.parse.urlparse(target_url).scheme or "https"
        return urllib.request.getproxies().get(scheme)


def proxy_handlers(proxy):
    """urllib handlers that send traffic through `proxy` (None = direct, ignoring env vars)."""
    if not proxy:
        return [urllib.request.ProxyHandler({})]
    p = urllib.parse.urlparse(proxy)
    if p.scheme.startswith("socks"):
        return [urllib.request.ProxyHandler({}), SocksHandler(p)]
    return [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]


def display_proxy(proxy):
    """Proxy URL without the password, for showing in the UI."""
    if not proxy:
        return "direct connection"
    p = urllib.parse.urlparse(proxy)
    return f"{p.scheme}://{p.hostname}:{p.port}"


# --- SOCKS5 ------------------------------------------------------------------------------
class ProxyError(ConnectionError):
    pass


SOCKS_ERRORS = {
    1: "general failure", 2: "connection not allowed", 3: "network unreachable", 4: "host unreachable",
    5: "connection refused", 6: "TTL expired", 7: "command not supported", 8: "address type not supported",
}


def _recv(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ProxyError("SOCKS proxy closed the connection")
        data += chunk
    return data


def socks5_connect(proxy, host, port, timeout):
    """Open a TCP connection to host:port through a SOCKS5 proxy (DNS is resolved by the proxy)."""
    sock = socket.create_connection((proxy.hostname, proxy.port or 1080), timeout)
    try:
        user = urllib.parse.unquote(proxy.username or "").encode()
        pwd = urllib.parse.unquote(proxy.password or "").encode()
        methods = b"\x00\x02" if user else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        ver, method = _recv(sock, 2)
        if ver != 5:
            raise ProxyError("Not a SOCKS5 proxy (is it an HTTP proxy?)")
        if method == 2:
            sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd)
            if _recv(sock, 2)[1] != 0:
                raise ProxyError("SOCKS proxy rejected the username or password")
        elif method != 0:
            raise ProxyError("SOCKS proxy requires a username and password")
        name = host.encode("idna")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + port.to_bytes(2, "big"))
        reply = _recv(sock, 4)
        if reply[1] != 0:
            raise ProxyError(f"SOCKS proxy: {SOCKS_ERRORS.get(reply[1], 'error %d' % reply[1])}")
        atyp = reply[3]
        _recv(sock, {1: 4, 4: 16}.get(atyp) or _recv(sock, 1)[0])
        _recv(sock, 2)
        return sock
    except BaseException:
        sock.close()
        raise


class _SocksHTTPConnection(http.client.HTTPConnection):
    proxy = None

    def connect(self):
        self.sock = socks5_connect(self.proxy, self.host, self.port, self.timeout)


class _SocksHTTPSConnection(http.client.HTTPSConnection):
    proxy = None

    def connect(self):
        sock = socks5_connect(self.proxy, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class SocksHandler(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def __init__(self, proxy):
        urllib.request.HTTPHandler.__init__(self)
        urllib.request.HTTPSHandler.__init__(self)
        self.http_cls = type("SocksHTTP", (_SocksHTTPConnection,), {"proxy": proxy})
        self.https_cls = type("SocksHTTPS", (_SocksHTTPSConnection,), {"proxy": proxy})

    def http_open(self, req):
        return self.do_open(self.http_cls, req)

    def https_open(self, req):
        return self.do_open(self.https_cls, req, context=self._context)


def test_proxy(proxy):
    """Fetch a tiny page through the proxy. Returns latency in ms or raises."""
    opener = urllib.request.build_opener(*proxy_handlers(proxy))
    t = time.monotonic()
    req = urllib.request.Request("https://www.google.com/generate_204", headers={"User-Agent": "Tondar"})
    with opener.open(req, timeout=15) as r:
        r.read()
    return int((time.monotonic() - t) * 1000)

"""PRISM encrypted DNS: a local HTTP proxy that resolves every hostname with
DNS-over-HTTPS (RFC 8484) instead of the system's plain-text DNS.

Qt WebEngine is started with --proxy-server pointing here, so Chromium hands
us hostnames (CONNECT host:443 / GET http://host/...) and never resolves them
itself. We look them up over HTTPS at the chosen provider, then tunnel the
connection. TLS between the page and the site stays end-to-end: the proxy
only sees the hostname, which the DNS provider sees anyway.

Modes:
  secure  - DoH first, fall back to system DNS if the provider is unreachable
  strict  - DoH only; if it fails, the connection fails (no plain DNS leaks)
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import random
import select
import socket
import struct
import threading
import time
from urllib.parse import urlsplit

BUF = 64 * 1024


# ------------------------------------------------------------ DNS wire format

def _build_query(name: str, qtype: int) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0x0100, 1, 0, 0, 0)   # id 0 per RFC 8484, RD set
    qname = b"".join(bytes([len(p)]) + p.encode("idna") for p in name.rstrip(".").split(".")) + b"\0"
    return header + qname + struct.pack(">HH", qtype, 1)


def _skip_name(buf: bytes, i: int) -> int:
    while True:
        n = buf[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2
        i += n + 1


def _parse_answers(buf: bytes, qtype: int) -> tuple[list[str], int]:
    _id, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", buf[:12])
    rcode = flags & 0xF
    i = 12
    for _ in range(qd):
        i = _skip_name(buf, i) + 4
    ips, ttl_min = [], 3600
    for _ in range(an):
        i = _skip_name(buf, i)
        rtype, _cls, ttl, rdlen = struct.unpack(">HHIH", buf[i:i + 10])
        i += 10
        rdata = buf[i:i + rdlen]
        i += rdlen
        if rtype == qtype == 1 and rdlen == 4:
            ips.append(socket.inet_ntop(socket.AF_INET, rdata))
            ttl_min = min(ttl_min, ttl)
        elif rtype == qtype == 28 and rdlen == 16:
            ips.append(socket.inet_ntop(socket.AF_INET6, rdata))
            ttl_min = min(ttl_min, ttl)
    if rcode not in (0, 3):
        raise OSError(f"DNS error code {rcode}")
    return ips, max(30, ttl_min)


# ------------------------------------------------------------------ resolver

class DohResolver:
    def __init__(self, template: str, strict: bool) -> None:
        self.template = template
        self.strict = strict
        u = urlsplit(template)
        self.host, self.path = u.hostname, u.path or "/dns-query"
        self.port = u.port or 443
        self.cache: dict[str, tuple[float, list[str]]] = {}
        self.lock = threading.Lock()
        self.local = threading.local()
        self.queries = 0
        self.failures = 0
        self.fallbacks = 0
        self.last_error = ""

    def _conn(self) -> http.client.HTTPSConnection:
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = http.client.HTTPSConnection(self.host, self.port, timeout=6)
            self.local.conn = conn
        return conn

    def _doh(self, name: str, qtype: int) -> tuple[list[str], int]:
        q = base64.urlsafe_b64encode(_build_query(name, qtype)).rstrip(b"=").decode()
        for attempt in (1, 2):
            conn = self._conn()
            try:
                conn.request("GET", f"{self.path}?dns={q}", headers={"Accept": "application/dns-message"})
                resp = conn.getresponse()
                body = resp.read()
                if resp.status != 200:
                    raise OSError(f"DoH HTTP {resp.status}")
                self.queries += 1
                return _parse_answers(body, qtype)
            except (OSError, http.client.HTTPException):
                conn.close()
                self.local.conn = None
                if attempt == 2:
                    raise
        return [], 60

    def resolve(self, name: str) -> list[str]:
        name = name.lower().strip("[]")
        try:
            ipaddress.ip_address(name)
            return [name]
        except ValueError:
            pass
        if name in ("localhost",) or name.endswith(".localhost"):
            return ["127.0.0.1"]
        with self.lock:
            hit = self.cache.get(name)
            if hit and hit[0] > time.time():
                return hit[1]
        try:
            ips, ttl = self._doh(name, 1)
            if not ips:
                ips6, ttl = self._doh(name, 28)
                ips = ips6
            if not ips:
                raise OSError(f"{name}: no address (NXDOMAIN)")
        except (OSError, http.client.HTTPException, struct.error, IndexError) as exc:
            self.failures += 1
            self.last_error = str(exc)
            if self.strict or "NXDOMAIN" in str(exc):
                raise OSError(f"Encrypted DNS lookup failed: {exc}") from None
            self.fallbacks += 1
            ips = list(dict.fromkeys(ai[4][0] for ai in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)))
            ttl = 60
        with self.lock:
            self.cache[name] = (time.time() + ttl, ips)
        return ips


# --------------------------------------------------------------------- proxy

class DohProxy:
    def __init__(self, template: str, strict: bool) -> None:
        self.resolver = DohResolver(template, strict)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(256)
        self.port = self.sock.getsockname()[1]
        self.connections = 0

    def start(self) -> "DohProxy":
        threading.Thread(target=self._accept, daemon=True, name="doh-proxy").start()
        return self

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _connect(self, host: str, port: int) -> socket.socket:
        ips = self.resolver.resolve(host)
        random.shuffle(ips)
        last: Exception | None = None
        for ip in ips[:4]:
            try:
                return socket.create_connection((ip, port), timeout=10)
            except OSError as exc:
                last = exc
        raise OSError(f"could not connect to {host}:{port}: {last}")

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            client.settimeout(30)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(BUF)
                if not chunk:
                    return
                head += chunk
                if len(head) > 256 * 1024:
                    return
            header, rest = head.split(b"\r\n\r\n", 1)
            lines = header.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                try:
                    upstream = self._connect(host, int(port))
                except OSError as exc:
                    client.sendall(f"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nX-PRISM-Error: {exc}\r\n\r\n".encode("latin-1", "replace"))
                    return
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                u = urlsplit(target)
                if not u.hostname:
                    client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                    return
                try:
                    upstream = self._connect(u.hostname, u.port or 80)
                except OSError as exc:
                    body = f"PRISM encrypted DNS: {exc}".encode()
                    client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nContent-Length: "
                                   + str(len(body)).encode() + b"\r\n\r\n" + body)
                    return
                path = (u.path or "/") + ("?" + u.query if u.query else "")
                kept = [ln for ln in lines[1:] if not ln.lower().startswith(("proxy-connection:", "connection:"))]
                # One request per connection: Chromium may reuse a proxy
                # connection for another host, which a dumb tunnel can't follow.
                req = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close"]) + "\r\n\r\n"
                upstream.sendall(req.encode("latin-1") + rest)
            self._pipe(client, upstream)
        except (OSError, ValueError):
            pass
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        a.settimeout(None)
        b.settimeout(None)
        socks = [a, b]
        while True:
            r, _, x = select.select(socks, [], socks, 120)
            if x or not r:
                return
            for s in r:
                data = s.recv(BUF)
                if not data:
                    return
                (b if s is a else a).sendall(data)

    def stats(self) -> dict:
        r = self.resolver
        return {"port": self.port, "queries": r.queries, "failures": r.failures,
                "fallbacks": r.fallbacks, "cached": len(r.cache), "lastError": r.last_error,
                "connections": self.connections}


# ------------------------------------------------- PRISM's own HTTP requests

# The proxy Chromium uses, once started. PRISM's Python-side requests (header
# checks, API tester, Meta stats, update check) go through it too, so with
# encrypted DNS on, no hostname is ever looked up in plain text.
ACTIVE: DohProxy | None = None


def activate(proxy: DohProxy) -> DohProxy:
    global ACTIVE
    ACTIVE = proxy
    return proxy


def urllib_handlers() -> list:
    """Extra urllib handlers for PRISM's own requests: route them through the
    DoH proxy when encrypted DNS is on (otherwise urllib's defaults apply)."""
    import urllib.request
    if ACTIVE is None:
        return []
    url = f"http://127.0.0.1:{ACTIVE.port}"
    return [urllib.request.ProxyHandler({"http": url, "https": url})]


def resolve(host: str) -> str:
    """One address for host, over DoH when encrypted DNS is on."""
    if ACTIVE is None:
        return host
    return ACTIVE.resolver.resolve(host)[0]

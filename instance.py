"""Links from other apps, and one PRISM per user.

When PRISM is the default browser, Windows starts `PRISM.exe "<url>"` for
every link clicked in another app (and `PRISM.exe "<file>"` for .html files).
If PRISM is already running, the new process hands its links to the running
one over a local socket (a named pipe on Windows) and exits, so the link
opens as a tab in the open window instead of starting a second browser on
the same profile.

Linux works the same way through prism.desktop (`Exec=prism %U`). macOS
doesn't put links on the command line: it starts (or wakes) the one PRISM.app
and sends each link as an Apple event, which Qt turns into a QFileOpenEvent
on the application (see AppleEvents below).
"""

import getpass
import hashlib
import os
import sys

from PyQt6.QtCore import QEvent, QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# Only these open from the command line / another process: no javascript:,
# data: or internal schemes.
SCHEMES = {"http", "https", "file"}


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return "Synterra.PRISM." + hashlib.sha256(user.encode()).hexdigest()[:16]


SERVER_NAME = _server_name()


def urls_from_argv(args: list[str]) -> list[str]:
    """The web addresses and local files in PRISM's command line, as full URLs.

    Anything else (flags, Qt options and their values) is ignored. Files are
    made absolute here, since the running PRISM may have another working folder.
    """
    urls = []
    for arg in args:
        if not arg or arg.startswith("-"):
            continue
        if os.path.isfile(arg):
            url = QUrl.fromLocalFile(os.path.abspath(arg))
        else:
            url = QUrl(arg, QUrl.ParsingMode.TolerantMode)
            if url.scheme().lower() not in SCHEMES or not url.isValid():
                continue
        urls.append(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
    return urls


def hand_off(urls: list[str]) -> bool:
    """Send `urls` to a PRISM that is already running. False: none is running."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(1500):
        return False
    if sys.platform == "win32":
        # This process may come to the front (the user just clicked a link);
        # let the running PRISM do that instead.
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
        except Exception:  # noqa: BLE001
            pass
    sock.write(("\n".join(urls) + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1500)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(1500)
    return True


class Listener(QObject):
    """Receives links from PRISM processes started after this one."""

    opened = pyqtSignal(list)       # URLs (possibly empty: "PRISM was started again")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # this user only
        self.server.newConnection.connect(self._accept)
        if not self.server.listen(SERVER_NAME):
            # A crashed PRISM can leave its socket file behind (not on Windows).
            QLocalServer.removeServer(SERVER_NAME)
            if not self.server.listen(SERVER_NAME):
                print(f"[prism] can't receive links from other apps: {self.server.errorString()}")

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()
            sock.readyRead.connect(lambda s=sock, b=buf: b.extend(bytes(s.readAll())))
            sock.disconnected.connect(lambda s=sock, b=buf: self._done(s, b))

    def _done(self, sock: QLocalSocket, buf: bytearray):
        buf.extend(bytes(sock.readAll()))
        sock.deleteLater()
        text = buf[:1_000_000].decode("utf-8", "replace")
        urls = []
        for line in text.splitlines():
            url = QUrl(line.strip(), QUrl.ParsingMode.StrictMode)
            if url.isValid() and url.scheme().lower() in SCHEMES:
                urls.append(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
        self.opened.emit(urls)


class AppleEvents(QObject):
    """macOS: links and files opened with PRISM from other apps (default
    browser, "Open With", dropping on the Dock icon). Install on the
    QApplication; links that arrive before the window exists are kept until
    `opened` is connected and `flush()` is called."""

    opened = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending: list[str] = []
        self.ready = False

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.FileOpen:
            url = event.url()
            if not url.isValid() and event.file():
                url = QUrl.fromLocalFile(event.file())
            if url.isValid() and url.scheme().lower() in SCHEMES:
                self.pending.append(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
                if self.ready:
                    self.flush()
            return True
        return super().eventFilter(obj, event)

    def flush(self):
        self.ready = True
        urls, self.pending = self.pending, []
        if urls:
            self.opened.emit(urls)

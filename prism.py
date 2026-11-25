"""PRISM: the privacy-first research browser, built and maintained by Synterra.

What it does:
  * SearXNG as the search engine (open-source metasearch, no tracking), moving
    to the next instance whenever one is busy; your own instance goes first
  * off-the-record sessions: browsing data never touches the disk
  * ad / tracker / malware blocking, tracking-parameter stripping, DNT + GPC,
    third-party cookie blocking, WebRTC IP-leak protection, optional
    encrypted DNS (DNS-over-HTTPS)
  * isolated containers (work, personal, banking, development), disposable
    temporary sessions and a locked-down sandbox for untrusted sites
  * developer tools: docked DevTools, split workspace, responsive preview,
    design inspector, API tester, terminal, source explorer and more in the
    PRISM panel (Ctrl+B)

This file only starts things up. Chromium reads its command-line flags once,
when Qt WebEngine starts, so they are set here before anything imports Qt
WebEngine; the browser itself is window.py and the modules it uses.

Run:  python prism.py            (or the PRISM executable of a built app)
      ... --update-blocklists     download the latest ad/tracker/malware lists, then exit
      ... --version               print the version, then exit
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QIcon, QSurfaceFormat

# Data paths are derived from these names, so they come first.
QCoreApplication.setOrganizationName("Synterra")
QCoreApplication.setApplicationName("PRISM")


def _command_line() -> int | None:
    """One-shot commands that exit before the browser starts (None: start the browser)."""
    if "--version" in sys.argv[1:]:
        from version import VERSION
        print(f"PRISM {VERSION}")
        return 0
    if "--update-blocklists" in sys.argv[1:]:
        import contextlib
        import io

        import update_blocklists
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = update_blocklists.main()
        report = out.getvalue() + f"\nSaved to {update_blocklists.DEST}. PRISM uses them from its next start."
        if sys.stdout is not None and sys.stdout.isatty():
            print(report)
        else:                       # started from a menu / shortcut (no console): show the result
            from PyQt6.QtWidgets import QApplication, QMessageBox
            _app = QApplication(sys.argv)
            (QMessageBox.warning if code else QMessageBox.information)(None, "PRISM blocklists", report)
        return code
    return None


import instance  # noqa: E402

LAUNCH_URLS: list[str] = []
if __name__ == "__main__":
    _cmd = _command_line()
    if _cmd is not None:
        sys.exit(_cmd)
    # Links from other apps (PRISM as default browser). PRISM already open:
    # it opens them as tabs and comes to the front; this process is done.
    LAUNCH_URLS = instance.urls_from_argv(sys.argv[1:])
    if instance.hand_off(LAUNCH_URLS):
        sys.exit(0)

import dohproxy  # noqa: E402
from storage import DNS_PROVIDERS, Settings, data_dir  # noqa: E402


def chromium_flags(proxy_port: int | None) -> str:
    flags = [
        "--no-pings",                                   # ignore <a ping> beacons
        "--disable-domain-reliability",                 # no Google reliability uploads
        "--disable-background-networking",
        "--force-webrtc-ip-handling-policy=default_public_interface_only",
        "--blink-settings=preferredColorScheme=0",      # ask sites for dark mode
    ]
    if proxy_port:
        # Encrypted DNS: hostnames go to the local DoH proxy, never to system DNS.
        # (Chromium sends localhost / 127.0.0.1 direct, as it should.)
        flags.append(f"--proxy-server=http://127.0.0.1:{proxy_port}")
    return " ".join(flags)


SETTINGS = Settings()
DOH_PROXY = None
if SETTINGS["dns"].get("mode") in ("secure", "strict"):
    _provider = DNS_PROVIDERS.get(SETTINGS["dns"].get("provider"), DNS_PROVIDERS["cloudflare"])
    DOH_PROXY = dohproxy.activate(
        dohproxy.DohProxy(_provider[1], strict=SETTINGS["dns"]["mode"] == "strict").start())
if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"):
    # Respect the user's own flags, but never drop encrypted DNS silently.
    if DOH_PROXY:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] += f" --proxy-server=http://127.0.0.1:{DOH_PROXY.port}"
else:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_flags(DOH_PROXY.port if DOH_PROXY else None)

# Flags are final: Qt WebEngine may load now.
from PyQt6 import sip  # noqa: E402
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import intro  # noqa: E402
from adblock import Blocklist, PrivacyEngine  # noqa: E402
from edition import DISABLED, EDITION  # noqa: E402
EDITION_NAME = "full" if EDITION == "employee" else EDITION   # what people see; "employee" is the settings value
from urls import ICON  # noqa: E402
from version import VERSION  # noqa: E402
from window import PrismWindow  # noqa: E402


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Synterra.Prism")
        except Exception:  # noqa: BLE001
            pass

    # Smooth scrolling: the toolbar, the page and the panel are separate web
    # views composited into one window. With vsync on, each of them presenting
    # a frame waits for its own screen refresh, so they take turns and pages
    # drop to ~30 fps (measured: 31-37 fps, 58-89% janky frames). Without it
    # they hit 56-60 fps. The Windows compositor still syncs the window to
    # the display, so nothing tears. PRISM_VSYNC=1 restores the old behaviour.
    if os.environ.get("PRISM_VSYNC") != "1":
        fmt = QSurfaceFormat.defaultFormat()
        fmt.setSwapInterval(0)
        QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setDesktopFileName("prism")     # Linux: matches prism.desktop, so docks show PRISM's icon

    blocklist = Blocklist()
    holder: dict[str, PrismWindow] = {}
    engine = PrivacyEngine(blocklist, SETTINGS,
                           on_block=lambda *a: holder["w"].on_blocked(*a) if "w" in holder else None,
                           stats_path=data_dir() / "stats.json")

    chrome_profile = QWebEngineProfile(app)  # off-the-record, local UI only
    chrome_profile.settings().setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

    win = PrismWindow(app, chrome_profile, engine, blocklist, SETTINGS, DOH_PROXY)
    holder["w"] = win
    if LAUNCH_URLS:                     # started by a link: open it instead of the new-tab page
        win.open_external(LAUNCH_URLS, replace_current=True)
    listener = instance.Listener(app)
    listener.opened.connect(win.open_external)
    win.show()
    # Terminal boot animation that fades into the browser. Not when PRISM was
    # started to open a link or a file: then the page is what's wanted, now.
    if intro.enabled(SETTINGS) and not LAUNCH_URLS:
        from sounds import Sfx
        sfx = Sfx(data_dir() / "sounds", enabled=bool(SETTINGS.data.get("introSound", True)), parent=win)
        intro.BootIntro(win, intro.boot_lines(win, blocklist, SETTINGS, DOH_PROXY, VERSION, EDITION_NAME),
                        version=VERSION, settings=SETTINGS, sfx=sfx).start()
    eng = win.updates.engine
    print(f"[prism] PRISM {VERSION}, {EDITION_NAME} edition"
          + (f" (without {', '.join(sorted(DISABLED))})" if DISABLED else "")
          + f"; Qt WebEngine {eng['qt']}, Chromium {eng['chromium']}"
          + (f", security patches to {eng['patch']}" if eng["patch"] else ""))
    print(f"[prism] {len(blocklist):,} blocked domains, {len(blocklist.malware):,} malicious domains"
          + (f", encrypted DNS via {SETTINGS['dns']['provider']} ({SETTINGS['dns']['mode']})" if DOH_PROXY else ""))
    code = app.exec()
    engine.stats.save()
    for c in win.containers.values():
        if c.login_dir is not None and c.profile is not None:
            c.profile.clearAllVisitedLinks()

    # Pages must die before their profiles, or Qt complains on exit.
    holder.clear()
    if win.dev is not None:
        sip.delete(win.dev)
    sip.delete(win)
    return code


if __name__ == "__main__":
    sys.exit(main())

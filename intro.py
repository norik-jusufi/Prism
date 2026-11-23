"""PRISM boot intro: a terminal that boots PRISM, then fades into the browser.

Shown over the whole window for about four seconds at start, while the
toolbar and the first tab load underneath (so their first paint is never
seen). A terminal powers on like a CRT, a command is typed in key by key, the
PRISM banner prints, the real boot log follows (version, engine, blocklists,
DNS, privacy, containers), a second command launches the interface, a text
progress bar fills, and the terminal fades away. Key clicks and digital blips
play along (sounds.py).

Drawn with QPainter on a plain widget, not a web view: it is on screen the
moment the window is, and costs nothing once it's gone. Its clock advances at
most one frame's worth per frame, so when Chromium's start-up briefly stalls
the UI thread the motion pauses for an instant instead of jumping.

Skip: click or press any key. Mute: M (remembered). Off: "intro": false in
settings.json, or the PRISM_NO_INTRO=1 environment variable. Sound only:
"introSound": false.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

from PyQt6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QApplication, QWidget

BG = QColor("#040a07")
BG_1 = QColor("#07110c")
LINE = QColor("#163826")
LINE_2 = QColor("#1f5537")
GREEN = QColor("#36f59b")
GREEN_HI = QColor("#74ff7a")
GREEN_DIM = QColor("#1fa866")
TEXT = QColor("#e8f5ec")
TEXT_2 = QColor("#a9c9b5")
MUTED = QColor("#5f8270")
WARN = QColor("#ffc65c")

PROMPT_USER = "synterra@prism"
PROMPT_PATH = ":~$ "
BANNER = [
    "██████╗ ██████╗ ██╗███████╗███╗   ███╗",
    "██╔══██╗██╔══██╗██║██╔════╝████╗ ████║",
    "██████╔╝██████╔╝██║███████╗██╔████╔██║",
    "██╔═══╝ ██╔══██╗██║╚════██║██║╚██╔╝██║",
    "██║     ██║  ██║██║███████║██║ ╚═╝ ██║",
    "╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚═╝     ╚═╝",
]
GLYPHS = "▓▒░<>/\\|[]{}=+*#%&$@01"

# Timeline (ms).
T_POWER = 260          # CRT power-on: a line of light opens into the screen
KEY_MIN, KEY_MAX = 14, 38   # one typed key
ENTER_PAUSE = 110      # after the return key, before the output
BANNER_ROW = 34        # one banner row
LOG_ROW = 95           # one boot-log row
DECODE = 120           # scrambled glyphs settle into text
STATUS_AFTER = 60      # "[ ok ]" lands this long after its row
BAR_TIME = 480         # progress bar fill
HOLD = 260             # "ready", then fade
FADE = 450             # fade into the browser
SKIP_FADE = 220        # faster fade when skipped
MAX_STEP = 20          # most intro time one frame may advance (ms)


def enabled(settings) -> bool:
    return os.environ.get("PRISM_NO_INTRO") != "1" and bool(settings.data.get("intro", True))


def boot_lines(window, blocklist, settings, doh, version: str, edition: str) -> list[tuple[str, str, str]]:
    """(label, detail, status) rows; status is "ok", "--" (off) or "!!" (problem)."""
    eng = window.updates.engine
    chromium = eng.get("chromium", "").split(".")[0]
    dns = settings["dns"]
    return [
        ("core", f"PRISM {version} · {edition} edition", "ok"),
        ("engine", f"chromium {chromium} · qt webengine {eng.get('qt', '?')}", "ok"),
        ("shields", f"{len(blocklist):,} trackers · {len(blocklist.malware):,} threats",
         "ok" if len(blocklist) else "!!"),
        ("dns", f"encrypted · {dns.get('provider')} ({dns.get('mode')})" if doh else "system resolver",
         "ok" if doh else "--"),
        ("privacy", "off-the-record · dnt + gpc · webrtc shield", "ok"),
        ("containers", "work · personal · banking · dev", "ok"),
    ]


def mono(px: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def ease_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def with_alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, c.alphaF() * a)))
    return c


# ------------------------------------------------------------- the script
@dataclass
class Row:
    """One line on the terminal and when it appears."""
    kind: str                      # "cmd" | "banner" | "text" | "log" | "bar" | "blank"
    start: int                     # ms
    text: str = ""
    label: str = ""
    status: str = ""
    keys: list[int] = field(default_factory=list)   # "cmd": ms each character lands
    end: int = 0                   # "cmd": return pressed; "bar": full


def build_script(lines: list[tuple[str, str, str]], version: str) -> tuple[list[Row], list[tuple[int, str]], int]:
    """Rows, the sound cues [(ms, name)] and the time the fade starts."""
    rnd = random.Random(1123)      # same rhythm every start
    rows: list[Row] = []
    cues: list[tuple[int, str]] = []
    t = T_POWER + 120

    def command(text: str) -> None:
        nonlocal t
        row = Row("cmd", t, text)
        k = t + 140                                   # the cursor blinks once first
        for ch in text:
            k += rnd.randint(KEY_MIN, KEY_MAX) + (45 if ch == " " and rnd.random() < 0.35 else 0)
            row.keys.append(k)
            cues.append((k, "key"))
        row.end = k + 70
        cues.append((row.end, "enter"))
        rows.append(row)
        t = row.end + ENTER_PAUSE

    command("./prism --boot --secure")
    for i, art in enumerate(BANNER):
        rows.append(Row("banner", t, art))
        cues.append((t, "data" if i == 0 else "tick"))
        t += BANNER_ROW
    t += 40
    rows.append(Row("text", t, f"   v{version} · privacy-first research browser · built and maintained by synterra"))
    cues.append((t, "blip2"))
    t += 120
    rows.append(Row("blank", t))
    for label, detail, status in lines:
        rows.append(Row("log", t, detail, label, status))
        cues.append((t, "blip"))
        cues.append((t + DECODE + STATUS_AFTER, {"ok": "ok", "--": "tick"}.get(status, "warn")))
        t += LOG_ROW
    t += 90
    rows.append(Row("blank", t))
    command("launch --interface")
    bar = Row("bar", t, end=t + BAR_TIME)
    rows.append(bar)
    for i in range(1, 10):
        cues.append((t + BAR_TIME * i // 10, "tick"))
    t = bar.end
    cues.append((t, "ready"))
    rows.append(Row("text", t + 30, "ready. opening prism", status="ready"))
    cues.sort()
    return rows, cues, t + HOLD


# ----------------------------------------------------------------- widget
class BootIntro(QWidget):
    def __init__(self, window: QWidget, lines: list[tuple[str, str, str]], version: str = "",
                 settings=None, sfx=None):
        super().__init__(window)
        self.window_ = window
        self.settings = settings
        self.sfx = sfx                            # sounds.Sfx, or None for silence
        self.rows, self.cues, self.t_fade = build_script(lines, version)
        self._cue = 0
        self.clock = QElapsedTimer()
        self.fade_from: int | None = None          # ms when the fade-out started
        self.fade_len = FADE
        self.done = False
        self.t = 0.0                               # intro time (ms), see _frame
        self.muted_note = 0.0                      # when M was pressed (for the hint)
        self._backdrop: QPixmap | None = None
        self._scroll = 0.0
        self._glitch = random.Random(5)

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.timer = QTimer(self, interval=8, timerType=Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._frame)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.setGeometry(self.window_.rect())
        self.window_.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        self.raise_()
        self.show()
        self.clock.start()
        self.timer.start()

    def skip(self) -> None:
        if self.fade_from is None:
            self.fade_from, self.fade_len = self.t, SKIP_FADE
            if self.sfx:
                self.sfx.stop()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def toggle_mute(self) -> None:
        if not self.sfx:
            return
        self.sfx.enabled = not self.sfx.enabled
        if not self.sfx.enabled:
            self.sfx.stop()
        self.muted_note = self.t
        if self.settings is not None:
            self.settings.data["introSound"] = self.sfx.enabled
            self.settings.save()

    def _finish(self) -> None:
        if self.done:
            return
        self.done = True
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.window_.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def _frame(self) -> None:
        # Intro time advances with the clock, but never more than MAX_STEP per
        # frame: when Chromium's start-up stalls the UI thread for a moment,
        # the animation pauses for that moment instead of jumping ahead.
        self.t += min(self.clock.restart(), MAX_STEP)
        t = self.t
        self._play_cues(t)
        if self.fade_from is None and t >= self.t_fade:
            self.fade_from = self.t_fade
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self.fade_from is not None and t >= self.fade_from + self.fade_len:
            self._finish()
            return
        self.update()

    def _play_cues(self, t: float) -> None:
        while self._cue < len(self.cues) and self.cues[self._cue][0] <= t:
            at, name = self.cues[self._cue]
            self._cue += 1
            # Skipped, or more than a frame late (a stall): stay quiet rather
            # than fire a burst of stale sounds at once.
            if self.sfx and self.fade_from is None and t - at < 60:
                self.sfx.key() if name == "key" else self.sfx.play(name)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        kind = ev.type()
        if obj is self.window_ and kind == QEvent.Type.Resize:
            self.setGeometry(self.window_.rect())
            self._backdrop = None
        elif kind in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress) and not self.done:
            if kind == QEvent.Type.MouseButtonPress and not self._is_mine(obj):
                return False
            if kind == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_M and self.fade_from is None:
                self.toggle_mute()
                return True
            self.skip()
            return True                      # the key or click only skips the intro
        return False

    def _is_mine(self, obj: QObject) -> bool:
        return obj is self or (isinstance(obj, QWidget) and self.window_.isAncestorOf(obj))

    # ------------------------------------------------------------ painting
    def _make_backdrop(self) -> QPixmap:
        """Background, faint grid, vignette and scanlines: drawn once per size."""
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(round(w * dpr), round(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(BG)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = 32
        p.setPen(QPen(with_alpha(LINE, 0.35), 1))
        x = (w / 2) % step
        while x < w:
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = (h / 2) % step
        while y < h:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        glow = QRadialGradient(QPointF(w / 2, h * 0.45), max(w, h) * 0.6)
        glow.setColorAt(0, with_alpha(GREEN, 0.06))
        glow.setColorAt(1, with_alpha(GREEN, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vig.setColorAt(0.5, QColor(0, 0, 0, 0))
        vig.setColorAt(1, QColor(0, 0, 0, 170))
        p.fillRect(QRectF(0, 0, w, h), vig)
        p.end()
        return pm

    def _screen_rect(self, w: float, h: float) -> QRectF:
        sw = min(980.0, w - 48.0)
        sh = min(620.0, h - 48.0)
        return QRectF((w - sw) / 2, (h - sh) / 2, sw, sh)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        t = self.t
        w, h = self.width(), self.height()
        fade = ease_in_out((t - self.fade_from) / self.fade_len) if self.fade_from is not None else 0.0
        alpha = 1.0 - fade

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self._backdrop is None or self._backdrop.deviceIndependentSize().toSize() != self.size():
            self._backdrop = self._make_backdrop()
        p.setOpacity(alpha)
        p.drawPixmap(0, 0, self._backdrop)

        screen = self._screen_rect(w, h)
        # Fading out, the terminal sinks back a little.
        if fade:
            k = 1 - 0.03 * fade
            c = screen.center()
            screen = QRectF(c.x() - screen.width() * k / 2, c.y() - screen.height() * k / 2 + 10 * fade,
                            screen.width() * k, screen.height() * k)

        # CRT power-on: a bright line opens vertically into the screen.
        power = ease_out(t / T_POWER)
        if power < 1:
            open_h = max(2.0, screen.height() * power ** 1.6)
            band = QRectF(screen.left() + screen.width() * 0.5 * (1 - min(1.0, power * 3)), screen.center().y() - open_h / 2,
                          screen.width() * min(1.0, power * 3), open_h)
            p.setOpacity(alpha)
            p.fillRect(band, with_alpha(BG_1, 0.95))
            p.fillRect(QRectF(band.left(), screen.center().y() - 1, band.width(), 2), with_alpha(GREEN_HI, 1 - power))
            p.end()
            return

        self._draw_frame(p, screen, t, alpha)
        p.end()

    def _draw_frame(self, p: QPainter, screen: QRectF, t: float, alpha: float) -> None:
        s = max(0.7, min(1.0, screen.width() / 980, screen.height() / 620))
        head_h = 30 * s
        pad = 22 * s

        # window: glow, body, border, title bar
        p.setOpacity(alpha)
        halo = QRadialGradient(screen.center(), max(screen.width(), screen.height()) * 0.7)
        halo.setColorAt(0, with_alpha(GREEN, 0.05))
        halo.setColorAt(1, with_alpha(GREEN, 0))
        p.fillRect(screen.adjusted(-60, -60, 60, 60), halo)
        p.fillRect(screen, with_alpha(BG_1, 0.97))
        p.setPen(QPen(LINE_2, 1))
        p.drawRect(screen)
        bar = QRectF(screen.left(), screen.top(), screen.width(), head_h)
        p.fillRect(bar, QColor("#0a1811"))
        p.setPen(QPen(LINE, 1))
        p.drawLine(bar.bottomLeft(), bar.bottomRight())
        for i, c in enumerate((GREEN, GREEN_DIM, LINE_2)):
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(bar.left() + 16 * s + i * 16 * s, bar.center().y()), 4.2 * s, 4.2 * s)
        p.setFont(mono(12 * s))
        p.setPen(MUTED)
        p.drawText(bar, Qt.AlignmentFlag.AlignCenter, "prism — synterra secure shell — 80×24")
        live = self.fade_from is None and t < self.t_fade
        p.setPen(GREEN if live else GREEN_DIM)
        p.drawText(bar.adjusted(0, 0, -14 * s, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "● live" if live else "● ready")

        # terminal text, scrolled so the newest row stays in view
        body = QRectF(screen.left() + pad, bar.bottom() + pad * 0.7, screen.width() - 2 * pad,
                      screen.height() - head_h - pad * 1.5 - 18 * s)
        f = mono(15 * s)
        fb = mono(15 * s, bold=True)
        fm = QFontMetricsF(f)
        line_h = fm.height() * 1.32
        banner_f = mono(min(22 * s, body.width() / (len(BANNER[0]) + 4) / 0.6), bold=True)
        banner_h = QFontMetricsF(banner_f).height() * 1.0
        shown = [r for r in self.rows if t >= r.start]
        total = sum(banner_h if r.kind == "banner" else line_h for r in shown) + line_h
        target = max(0.0, total - body.height())
        self._scroll += (target - self._scroll) * 0.25
        p.save()
        p.setClipRect(body.adjusted(-4, -2, 4, 2))
        y = body.top() - self._scroll
        for row in shown:
            rh = banner_h if row.kind == "banner" else line_h
            if y + rh >= body.top() - rh:
                self._draw_row(p, row, t, QRectF(body.left(), y, body.width(), rh), f, fb, banner_f, s, alpha)
            y += rh
        p.restore()

        # scanlines + a slow refresh band over the glass
        p.setOpacity(alpha)
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        yy = screen.top() + head_h + 0.5
        while yy < screen.bottom():
            p.drawLine(QPointF(screen.left() + 1, yy), QPointF(screen.right() - 1, yy))
            yy += 3
        if self.fade_from is None:
            band_y = screen.top() + (t * 0.32) % (screen.height() + 140) - 70
            g = QLinearGradient(0, band_y - 70, 0, band_y)
            g.setColorAt(0, with_alpha(GREEN, 0))
            g.setColorAt(1, with_alpha(GREEN, 0.035))
            p.save()
            p.setClipRect(screen)
            p.fillRect(QRectF(screen.left(), band_y - 70, screen.width(), 70), g)
            p.restore()

        # footer hint
        p.setFont(mono(11 * s))
        p.setOpacity(alpha * 0.85)
        p.setPen(MUTED)
        hint = "press any key to skip"
        if self.sfx and self.sfx.available:
            hint += " · m: " + ("sound off" if self.sfx.enabled else "sound on")
        if self.muted_note and t - self.muted_note < 1200:
            p.setPen(GREEN)
            hint = "sound on" if self.sfx and self.sfx.enabled else "sound off (press m to turn it back on)"
        p.drawText(QRectF(screen.left(), screen.bottom() - 22 * s, screen.width() - 14 * s, 18 * s),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, hint)

    def _prompt(self, p: QPainter, x: float, r: QRectF, fb: QFont, f: QFont) -> float:
        fm = QFontMetricsF(fb)
        p.setFont(fb)
        p.setPen(GREEN)
        p.drawText(QPointF(x, r.top() + (r.height() + fm.ascent() - fm.descent()) / 2), PROMPT_USER)
        x += fm.horizontalAdvance(PROMPT_USER)
        p.setFont(f)
        p.setPen(TEXT_2)
        p.drawText(QPointF(x, r.top() + (r.height() + fm.ascent() - fm.descent()) / 2), PROMPT_PATH)
        return x + QFontMetricsF(f).horizontalAdvance(PROMPT_PATH)

    def _cursor(self, p: QPainter, x: float, r: QRectF, fm: QFontMetricsF, solid: bool) -> None:
        if solid or (int(self.t) // 420) % 2 == 0:
            p.fillRect(QRectF(x + 1, r.top() + r.height() * 0.18, fm.horizontalAdvance("M") * 0.95, r.height() * 0.64),
                       with_alpha(GREEN, 0.9))

    def _decode(self, text: str, k: float, seed: int) -> str:
        """Scrambled glyphs that settle into `text` from left to right as k goes 0 -> 1."""
        if k >= 1:
            return text
        rnd = random.Random(seed * 131 + int(self.t // 40))
        n = int(len(text) * k)
        return text[:n] + "".join(" " if c == " " else rnd.choice(GLYPHS) for c in text[n:])

    def _draw_row(self, p: QPainter, row: Row, t: float, r: QRectF, f: QFont, fb: QFont, bf: QFont,
                  s: float, alpha: float) -> None:
        fm = QFontMetricsF(f)
        base = r.top() + (r.height() + fm.ascent() - fm.descent()) / 2
        p.setOpacity(alpha)
        if row.kind == "cmd":
            x = self._prompt(p, r.left(), r, fb, f)
            n = sum(1 for k in row.keys if k <= t)
            typed = row.text[:n]
            p.setFont(f)
            p.setPen(TEXT)
            p.drawText(QPointF(x, base), typed)
            if t < row.end:
                self._cursor(p, x + fm.horizontalAdvance(typed), r, fm, solid=0 < n < len(row.text))
        elif row.kind == "banner":
            k = ease_out((t - row.start) / 160)
            p.setFont(bf)
            bm = QFontMetricsF(bf)
            text = self._decode(row.text, min(1.0, (t - row.start) / 90), row.start)
            bx = r.left() + 2 * s
            by = r.top() + (r.height() + bm.ascent() - bm.descent()) / 2
            if k < 1:                                    # RGB split as each row lands
                off = 3 * s * (1 - k)
                p.setOpacity(alpha * 0.5 * (1 - k))
                p.setPen(QColor("#ff3b6b"))
                p.drawText(QPointF(bx - off, by), text)
                p.setPen(QColor("#3bd9ff"))
                p.drawText(QPointF(bx + off, by), text)
            p.setOpacity(alpha * 0.18)
            p.setPen(GREEN)
            for dx, dy in ((-1.5, 0), (1.5, 0), (0, -1.5), (0, 1.5)):   # cheap glow
                p.drawText(QPointF(bx + dx * s, by + dy * s), text)
            p.setOpacity(alpha)
            grad = QLinearGradient(bx, by - bm.ascent(), bx, by)
            grad.setColorAt(0, GREEN_HI)
            grad.setColorAt(1, GREEN)
            p.setPen(QPen(grad, 1))
            p.drawText(QPointF(bx, by), text)
        elif row.kind == "text":
            k = min(1.0, (t - row.start) / DECODE)
            p.setFont(fb if row.status == "ready" else f)
            p.setPen(GREEN if row.status == "ready" else MUTED)
            text = self._decode(row.text, k, row.start)
            if row.status == "ready":
                text = "✓ " + text
            p.drawText(QPointF(r.left(), base), text)
            if row.status == "ready" and self.fade_from is None:
                self._cursor(p, r.left() + QFontMetricsF(fb).horizontalAdvance(text) + 6 * s, r, fm, solid=False)
        elif row.kind == "log":
            k = min(1.0, (t - row.start) / DECODE)
            st = (t - row.start - DECODE - STATUS_AFTER) / 140
            tag = {"ok": "[  OK  ]", "--": "[  --  ]"}.get(row.status, "[ WARN ]")
            color = {"ok": GREEN, "--": MUTED}.get(row.status, WARN)
            p.setFont(fb)
            tw = QFontMetricsF(fb).horizontalAdvance(tag + " ")
            if st > 0:
                ks = ease_out(st)
                if st < 1 and row.status == "ok":            # flash as it lands
                    p.setOpacity(alpha * (1 - ks))
                    p.setPen(GREEN_HI)
                    for d in (-1.2, 1.2):
                        p.drawText(QPointF(r.left() + d * s, base), tag)
                p.setOpacity(alpha * ks)
                p.setPen(color)
                p.drawText(QPointF(r.left(), base), tag)
            else:
                p.setPen(MUTED)
                spin = "|/-\\"[int(t // 70) % 4]
                p.drawText(QPointF(r.left(), base), f"[  {spin}   ]")
            p.setOpacity(alpha)
            p.setFont(f)
            label_w = fm.horizontalAdvance("containers  ")
            p.setPen(GREEN_DIM)
            p.drawText(QPointF(r.left() + tw, base), self._decode(row.label, k, row.start + 1))
            p.setPen(TEXT_2)
            p.drawText(QPointF(r.left() + tw + label_w, base), self._decode(row.text, k, row.start + 2))
        elif row.kind == "bar":
            fill = ease_in_out((t - row.start) / max(1, row.end - row.start))
            cells = 36
            done = int(cells * fill)
            p.setFont(f)
            x = r.left()
            p.setPen(TEXT_2)
            p.drawText(QPointF(x, base), "launching ")
            x += fm.horizontalAdvance("launching ")
            p.setPen(LINE_2)
            p.drawText(QPointF(x, base), "[")
            x += fm.horizontalAdvance("[")
            p.setPen(GREEN)
            p.drawText(QPointF(x, base), "█" * done)
            p.setPen(LINE_2)
            p.drawText(QPointF(x + fm.horizontalAdvance("█" * done), base), "░" * (cells - done))
            x += fm.horizontalAdvance("█" * cells)
            p.drawText(QPointF(x, base), "]")
            p.setPen(GREEN if fill >= 1 else TEXT)
            p.drawText(QPointF(x + fm.horizontalAdvance("] "), base), f"{int(fill * 100):3d}%")

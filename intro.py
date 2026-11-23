"""PRISM boot intro: a terminal that "loads" PRISM in, then fades into the browser.

Shown over the whole window for about two seconds at start, while the toolbar
and the first tab load underneath (so their first paint is never seen). It
types out a real boot log (version, engine, blocklists, DNS, privacy,
containers), fills a progress bar, and fades away.

Drawn with QPainter on a plain widget, not a web view: it is on screen the
moment the window is, and costs nothing once it's gone. Its clock advances at
most one frame's worth per frame, so when Chromium's start-up briefly stalls
the UI thread the motion pauses for an instant instead of jumping.

Skip: click or press any key. Off: "intro": false in settings.json, or the
PRISM_NO_INTRO=1 environment variable.
"""

from __future__ import annotations

import math
import os

from PyQt6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QApplication, QWidget

from paths import RESOURCES

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

# Timeline (ms).
T_LOGO = 0            # logo + wordmark fade in
T_LINES = 380         # first boot line starts typing
LINE_TYPE = 150       # typing one line
LINE_GAP = 45         # pause before the next one
T_STATUS = 70         # "[ ok ]" lands this long after its line is typed
BAR_TIME = 380        # progress bar fill
HOLD = 200            # full bar, "ready"
FADE = 450            # fade into the browser
SKIP_FADE = 220       # faster fade when skipped
MAX_STEP = 20         # most intro time one frame may advance (ms)


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


class BootIntro(QWidget):
    def __init__(self, window: QWidget, lines: list[tuple[str, str, str]]):
        super().__init__(window)
        self.window_ = window
        self.lines = lines
        self.clock = QElapsedTimer()
        self.fade_from: int | None = None          # ms when the fade-out started
        self.fade_len = FADE
        self.done = False
        self.t = 0.0                               # intro time (ms), see _frame
        self.logo = QImage(str(RESOURCES / "assets" / "logo.png"))
        self._backdrop: QPixmap | None = None
        n = len(lines)
        self.t_bar = T_LINES + n * (LINE_TYPE + LINE_GAP) + T_STATUS
        self.t_fade = self.t_bar + BAR_TIME + HOLD

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
        self.setCursor(Qt.CursorShape.ArrowCursor)

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
        if self.fade_from is None and t >= self.t_fade:
            self.fade_from = self.t_fade
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self.fade_from is not None and t >= self.fade_from + self.fade_len:
            self._finish()
            return
        self.update()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        kind = ev.type()
        if obj is self.window_ and kind == QEvent.Type.Resize:
            self.setGeometry(self.window_.rect())
            self._backdrop = None
        elif kind in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress) and not self.done:
            if kind == QEvent.Type.MouseButtonPress and not self._is_mine(obj):
                return False
            self.skip()
            return True                      # the key or click only skips the intro
        return False

    def _is_mine(self, obj: QObject) -> bool:
        return obj is self or (isinstance(obj, QWidget) and self.window_.isAncestorOf(obj))

    # ------------------------------------------------------------ painting
    def _make_backdrop(self) -> QPixmap:
        """Background, grid, vignette and scanlines: drawn once per size."""
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(round(w * dpr), round(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(BG)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = 32
        p.setPen(QPen(with_alpha(LINE, 0.55), 1))
        x = (w / 2) % step
        while x < w:
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = (h / 2) % step
        while y < h:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        glow = QRadialGradient(QPointF(w / 2, h * 0.42), max(w, h) * 0.55)
        glow.setColorAt(0, with_alpha(GREEN, 0.07))
        glow.setColorAt(1, with_alpha(GREEN, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vig.setColorAt(0.55, QColor(0, 0, 0, 0))
        vig.setColorAt(1, QColor(0, 0, 0, 150))
        p.fillRect(QRectF(0, 0, w, h), vig)
        p.setPen(QPen(QColor(0, 0, 0, 34), 1))
        y = 0.5
        while y < h:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += 3
        p.end()
        return pm

    def paintEvent(self, _ev) -> None:  # noqa: N802
        t = int(self.t)
        w, h = self.width(), self.height()
        fade = 0.0
        if self.fade_from is not None:
            fade = ease_in_out((t - self.fade_from) / self.fade_len)
        alpha = 1.0 - fade

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._backdrop is None or self._backdrop.deviceIndependentSize().toSize() != self.size():
            self._backdrop = self._make_backdrop()
        p.setOpacity(alpha)
        p.drawPixmap(0, 0, self._backdrop)

        # Content drifts up a little as it fades out.
        lift = -18 * fade
        p.translate(0, lift)
        scale = min(1.0, w / 900, h / 640) if w and h else 1.0
        scale = max(0.62, scale)
        col_w = min(680.0, w - 64.0)
        x0 = (w - col_w) / 2
        y = max(24.0, h * 0.5 - 250 * scale)

        y = self._draw_brand(p, t, x0, y, col_w, scale, alpha)
        y = self._draw_terminal(p, t, x0, y + 26 * scale, col_w, scale, alpha)
        self._draw_bar(p, t, x0, y + 18 * scale, col_w, scale, alpha)

        # Sweeping scan beam across the whole screen while booting.
        if self.fade_from is None:
            beam_y = (t * 0.55) % (h + 160) - 80
            g = QLinearGradient(0, beam_y - 70, 0, beam_y)
            g.setColorAt(0, with_alpha(GREEN, 0))
            g.setColorAt(1, with_alpha(GREEN, 0.045))
            p.setOpacity(alpha)
            p.fillRect(QRectF(0, beam_y - 70 - lift, w, 70), g)
        p.end()

    def _draw_brand(self, p: QPainter, t: int, x0: float, y: float, col_w: float, s: float, alpha: float) -> float:
        k = ease_out((t - T_LOGO) / 520)
        logo_px = 112 * s
        cx = x0 + col_w / 2
        # logo: fades in and settles from slightly larger
        if not self.logo.isNull():
            size = logo_px * (1.08 - 0.08 * k)
            pulse = 0.85 + 0.15 * math.sin(t / 380)
            p.setOpacity(alpha * k)
            halo = QRadialGradient(QPointF(cx, y + logo_px / 2), logo_px * 0.9)
            halo.setColorAt(0, with_alpha(GREEN, 0.16 * pulse))
            halo.setColorAt(1, with_alpha(GREEN, 0))
            p.fillRect(QRectF(cx - logo_px, y - logo_px * 0.4, logo_px * 2, logo_px * 1.8), halo)
            p.drawImage(QRectF(cx - size / 2, y + (logo_px - size) / 2, size, size), self.logo)
        y += logo_px + 6 * s

        # wordmark with a short RGB-split glitch as it lands
        font = mono(46 * s, bold=True)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
        p.setFont(font)
        fm = QFontMetricsF(font)
        word = "PRISM"
        shown = word[:max(0, min(len(word), int((t - 120) / 55)))]
        tw = fm.horizontalAdvance(word)
        bx, by = cx - tw / 2, y + fm.ascent()
        glitch = max(0.0, 1 - (t - 120 - len(word) * 55) / 360) if shown == word else 1.0
        if 0 < k:
            if glitch > 0 and shown:
                off = 3.5 * s * glitch * (1 if (t // 40) % 2 else -1)
                p.setOpacity(alpha * 0.55 * glitch)
                p.setPen(QColor("#ff3b6b"))
                p.drawText(QPointF(bx - off, by), shown)
                p.setPen(QColor("#3bd9ff"))
                p.drawText(QPointF(bx + off, by), shown)
            for spread, a in ((3.0, 0.10), (1.5, 0.16)):           # cheap glow
                p.setOpacity(alpha * a)
                p.setPen(GREEN)
                for dx, dy in ((-spread, 0), (spread, 0), (0, -spread), (0, spread)):
                    p.drawText(QPointF(bx + dx * s, by + dy * s), shown)
            p.setOpacity(alpha)
            grad = QLinearGradient(bx, by - fm.ascent(), bx, by)
            grad.setColorAt(0, GREEN_HI)
            grad.setColorAt(1, GREEN)
            p.setPen(QPen(grad, 1))
            p.drawText(QPointF(bx, by), shown)
            if len(shown) < len(word) or (t // 450) % 2 == 0 and self.fade_from is None:
                cw = fm.horizontalAdvance(shown)
                p.fillRect(QRectF(bx + cw + 4 * s, by - fm.ascent() * 0.82, 12 * s, fm.ascent() * 0.86),
                           with_alpha(GREEN, 0.9))
        y += fm.height() + 2 * s

        sub = mono(13 * s)
        p.setFont(sub)
        p.setOpacity(alpha * ease_out((t - 300) / 400))
        p.setPen(MUTED)
        text = "// built and maintained by synterra"
        p.drawText(QRectF(x0, y, col_w, 20 * s), Qt.AlignmentFlag.AlignHCenter, text)
        return y + 20 * s

    def _draw_terminal(self, p: QPainter, t: int, x0: float, y: float, col_w: float, s: float, alpha: float) -> float:
        line_h = 25 * s
        pad = 18 * s
        head_h = 30 * s
        box_h = head_h + pad + len(self.lines) * line_h + pad * 0.6
        appear = ease_out((t - 200) / 380)
        p.setOpacity(alpha * appear)
        box = QRectF(x0, y + 8 * s * (1 - appear), col_w, box_h)

        # frame: clipped corners like the dashboard tiles
        cut = 12 * s
        path = QPainterPath()
        path.moveTo(box.left(), box.top())
        path.lineTo(box.right() - cut, box.top())
        path.lineTo(box.right(), box.top() + cut)
        path.lineTo(box.right(), box.bottom())
        path.lineTo(box.left() + cut, box.bottom())
        path.lineTo(box.left(), box.bottom() - cut)
        path.closeSubpath()
        p.fillPath(path, with_alpha(BG_1, 0.92))
        p.setPen(QPen(LINE_2, 1))
        p.drawPath(path)
        p.setPen(QPen(with_alpha(LINE, 1), 1))
        p.drawLine(QPointF(box.left(), box.top() + head_h), QPointF(box.right(), box.top() + head_h))

        f_head = mono(12 * s)
        p.setFont(f_head)
        p.setPen(MUTED)
        p.drawText(QRectF(box.left() + pad, box.top(), box.width() - 2 * pad, head_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "prism@synterra:~$ ./boot --secure")
        live = self.fade_from is None and t < self.t_fade
        p.setPen(GREEN if live else GREEN_DIM)
        p.drawText(QRectF(box.left() + pad, box.top(), box.width() - 2 * pad, head_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "● live" if live else "● ready")

        f = mono(14 * s)
        fb = mono(14 * s, bold=True)
        fm = QFontMetricsF(f)
        label_w = fm.horizontalAdvance("containers") + 22 * s
        ly = box.top() + head_h + pad * 0.7
        for i, (label, detail, status) in enumerate(self.lines):
            start = T_LINES + i * (LINE_TYPE + LINE_GAP)
            if t < start:
                break
            prog = min(1.0, (t - start) / LINE_TYPE)
            row = QRectF(box.left() + pad, ly, box.width() - 2 * pad, line_h)
            p.setOpacity(alpha * appear)
            p.setFont(fb)
            p.setPen(GREEN)
            p.drawText(row, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, ">")
            full = label.ljust(11) + detail
            n = int(len(full) * prog)
            lab = full[:min(n, len(label))]
            det = full[len(label.ljust(11)):n] if n > len(label.ljust(11)) else ""
            tx = row.left() + fm.horizontalAdvance("> ")
            p.setFont(f)
            p.setPen(GREEN_DIM)
            p.drawText(QRectF(tx, ly, label_w, line_h), Qt.AlignmentFlag.AlignVCenter, lab)
            p.setPen(TEXT_2)
            p.drawText(QRectF(tx + label_w, ly, row.width() - label_w - 80 * s, line_h),
                       Qt.AlignmentFlag.AlignVCenter, det)
            if prog < 1:                                     # typing cursor
                cx = tx + (fm.horizontalAdvance(lab) if n <= len(label)
                           else label_w + fm.horizontalAdvance(det))
                p.fillRect(QRectF(cx + 1, ly + line_h * 0.22, 8 * s, line_h * 0.56), with_alpha(GREEN, 0.9))
            st = (t - start - LINE_TYPE - T_STATUS) / 160
            if st > 0:
                k = ease_out(st)
                tag = {"ok": "[  ok  ]", "--": "[  --  ]"}.get(status, "[ warn ]")
                color = {"ok": GREEN, "--": MUTED}.get(status, WARN)
                p.setFont(fb)
                p.setOpacity(alpha * appear * k)
                tr = QRectF(row.left(), ly, row.width() + (1 - k) * 14 * s, line_h)
                if st < 1 and status == "ok":                     # flash as it lands
                    p.setPen(with_alpha(GREEN_HI, 1 - k))
                    for d in (-1.2, 1.2):
                        p.drawText(tr.translated(d * s, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tag)
                p.setPen(color)
                p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tag)
            ly += line_h
        return box.bottom()

    def _draw_bar(self, p: QPainter, t: int, x0: float, y: float, col_w: float, s: float, alpha: float) -> None:
        # Creeps forward while lines boot, then fills.
        booted = min(1.0, max(0.0, (t - T_LINES) / max(1, self.t_bar - T_LINES)))
        fill = 0.62 * ease_out(booted) + 0.38 * ease_in_out((t - self.t_bar) / BAR_TIME)
        fill = max(0.0, min(1.0, fill))
        appear = ease_out((t - 250) / 400)
        p.setOpacity(alpha * appear)
        f = mono(12 * s)
        p.setFont(f)
        ready = t >= self.t_bar + BAR_TIME
        label = "ready. opening prism" if ready else (
            "loading modules" if t < self.t_bar else "launching interface")
        dots = "" if ready else "." * (1 + (t // 220) % 3)
        p.setPen(GREEN if ready else MUTED)
        p.drawText(QRectF(x0, y, col_w, 18 * s), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   label + dots)
        p.setPen(GREEN if ready else TEXT_2)
        p.drawText(QRectF(x0, y, col_w, 18 * s), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{int(fill * 100):3d}%")
        by = y + 26 * s
        bh = max(2.0, 3 * s)
        p.fillRect(QRectF(x0, by, col_w, bh), with_alpha(LINE, 1))
        fw = col_w * fill
        if fw > 0:
            g = QLinearGradient(x0, 0, x0 + fw, 0)
            g.setColorAt(0, GREEN_DIM)
            g.setColorAt(1, GREEN_HI)
            p.fillRect(QRectF(x0, by, fw, bh), g)
            glow = QRadialGradient(QPointF(x0 + fw, by + bh / 2), 26 * s)
            glow.setColorAt(0, with_alpha(GREEN_HI, 0.55))
            glow.setColorAt(1, with_alpha(GREEN_HI, 0))
            p.fillRect(QRectF(x0 + fw - 26 * s, by - 24 * s, 52 * s, 48 * s + bh), glow)
        # segment ticks
        p.setPen(QPen(with_alpha(BG, 0.9), max(1.0, s)))
        for i in range(1, 40):
            tx = x0 + col_w * i / 40
            p.drawLine(QPointF(tx, by), QPointF(tx, by + bh))

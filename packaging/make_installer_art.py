"""Draw the Windows installer's artwork in PRISM's "digital green" look.

Writes PNGs to build/installer/ (several sizes each; Inno Setup picks the one
that fits the screen's DPI best):
  wizard-<w>.png   side panel on the welcome / finished pages (164:314)
  small-<w>.png    top-right corner image on the other pages
  back-<w>.png     background of every wizard page (497:360), kept faint so
                   text stays readable

Made with Qt, so no extra package is needed. build_windows.bat runs it.
Colours are the ones in ui/theme.css.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":     # the offscreen platform doesn't find system fonts on its own
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,  # noqa: E402
                         QPen, QRadialGradient, QLinearGradient)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "installer"

BG = QColor("#040a07")
BG_1 = QColor("#07110c")
LINE = QColor("#163826")
GREEN = QColor("#36f59b")
TEXT_2 = QColor("#a9c9b5")
MUTED = QColor("#5f8270")

# Sizes from the Inno Setup docs (100% ... 250% DPI).
WIZARD = [(202, 386), (269, 515), (336, 643), (403, 772), (430, 824), (534, 1022)]
SMALL = [58, 72, 87, 101, 116, 145]
BACK = [(596, 432), (796, 576), (994, 720), (1272, 922), (1630, 1148)]


def rgba(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(a)
    return c


def grid(p: QPainter, w: int, h: int, step: float, alpha: float) -> None:
    p.setPen(QPen(rgba(LINE, alpha), max(1.0, step / 40)))
    x = 0.0
    while x <= w:
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        x += step
    y = 0.0
    while y <= h:
        p.drawLine(QPointF(0, y), QPointF(w, y))
        y += step


def glow(p: QPainter, cx: float, cy: float, r: float, alpha: float) -> None:
    g = QRadialGradient(QPointF(cx, cy), r)
    g.setColorAt(0, rgba(GREEN, alpha))
    g.setColorAt(1, rgba(GREEN, 0))
    p.fillRect(QRectF(cx - r, cy - r, 2 * r, 2 * r), g)


def mono(px: float, weight=QFont.Weight.Bold) -> QFont:
    f = QFont("Cascadia Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies(["Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"])
    f.setPixelSize(max(1, round(px)))
    f.setWeight(weight)
    return f


def wizard(w: int, h: int, logo: QImage) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    s = w / 202                                    # 1.0 at 100% DPI
    grid(p, w, h, 20 * s, 0.55)
    glow(p, w * 0.5, h * 0.36, w * 0.75, 0.16)

    side = w * 0.92
    p.drawImage(QRectF((w - side) / 2, h * 0.36 - side / 2, side, side), logo)

    p.setPen(GREEN)
    p.setFont(mono(34 * s))
    p.drawText(QRectF(0, h * 0.62, w, 44 * s), Qt.AlignmentFlag.AlignHCenter, "PRISM")
    p.setPen(TEXT_2)
    p.setFont(mono(10.5 * s, QFont.Weight.Normal))
    p.drawText(QRectF(0, h * 0.62 + 46 * s, w, 18 * s), Qt.AlignmentFlag.AlignHCenter,
               "privacy-first browser")
    p.setPen(MUTED)
    p.setFont(mono(9 * s, QFont.Weight.Normal))
    p.drawText(QRectF(0, h - 30 * s, w, 16 * s), Qt.AlignmentFlag.AlignHCenter, "> synterra_")

    # thin green edge where the panel meets the page
    edge = QLinearGradient(0, 0, 0, h)
    edge.setColorAt(0, rgba(GREEN, 0))
    edge.setColorAt(0.5, rgba(GREEN, 0.7))
    edge.setColorAt(1, rgba(GREEN, 0))
    p.fillRect(QRectF(w - max(1, 1.5 * s), 0, max(1, 1.5 * s), h), edge)
    p.end()
    return img


def small(n: int, icon: QImage) -> QImage:
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, n, n), icon)
    p.end()
    return img


def back(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(BG_1)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = w / 596
    grid(p, w, h, 24 * s, 0.32)
    glow(p, w * 1.0, h * 1.0, w * 0.55, 0.07)
    glow(p, 0, 0, w * 0.35, 0.035)
    p.end()
    return img


def main() -> int:
    _app = QGuiApplication(sys.argv)
    logo = QImage(str(ROOT / "assets" / "logo.png"))
    icon = QImage(str(ROOT / "assets" / "icon.png"))
    if logo.isNull() or icon.isNull():
        print("can't read assets/logo.png or assets/icon.png", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    for w, h in WIZARD:
        wizard(w, h, logo).save(str(OUT / f"wizard-{w}.png"))
    for n in SMALL:
        small(n, icon).save(str(OUT / f"small-{n}.png"))
    for w, h in BACK:
        back(w, h).save(str(OUT / f"back-{w}.png"))
    print(f"wrote installer artwork to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

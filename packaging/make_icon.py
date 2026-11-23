"""Build assets/icon.ico (Windows exe + installer icon) from assets/icon.png.

A multi-size ICO with PNG-compressed entries (16 to 256 px), made with Qt so
no extra package is needed. The build scripts run this; run it by hand after
changing icon.png:  python packaging/make_icon.py
"""

import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(img: QImage, size: int) -> bytes:
    scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    scaled.save(buf, "PNG")
    return bytes(ba.data())


def main() -> int:
    src = ROOT / "assets" / "icon.png"
    img = QImage(str(src))
    if img.isNull():
        print(f"can't read {src}", file=sys.stderr)
        return 1
    images = [png_bytes(img, s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = len(header) + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size            # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out = ROOT / "assets" / "icon.ico"
    out.write_bytes(header + entries + b"".join(images))
    print(f"wrote {out} ({', '.join(map(str, SIZES))} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

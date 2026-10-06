"""Render the Clex app icon into src/clex/icons.

    uv run python scripts/make_icon.py

The logo is a Klecks, German for a blot of ink, which Clex sounds like: a glossy
indigo ink splat with droplets flying off, on the dark app tile. The splat is grown
from metaballs and traced into bezier curves by Clex's own path tracer.

Writes `clex.png` (1024 px) and `clex.ico` (Windows, 16-256 px). Drawn with Qt so it
needs no extra dependencies. Small sizes drop the details so they stay readable.
"""

import math
import os
import struct
import sys
from functools import cache
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from clex import paths

OUT = Path(__file__).resolve().parents[1] / "src" / "clex" / "icons"
UNITS = 1000  # artwork is drawn in a 1000 unit box

TILE_TOP = QColor("#1F2330")
TILE_BOTTOM = QColor("#0C0E16")
ACCENT = QColor("#6366F1")  # theme accent
INK_LIGHT = QColor("#A5B4FC")
INK = QColor("#6366F1")
INK_DARK = QColor("#3730A3")

CENTER = (490.0, 530.0)
type Ball = tuple[float, float, float]  # x, y, radius


def arm(angle: float, length: float, neck: float, tip: float) -> list[Ball]:
    """A splash arm: tapering out of the body, ending in a round bulb."""
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    cx, cy = CENTER
    balls = []
    steps = 9
    for i in range(steps):
        t = i / steps
        d = 150 + t * (length - 150)
        balls.append((cx + dx * d, cy + dy * d, 62 * (1 - t) + neck * t))
    balls.append((cx + dx * length, cy + dy * length, tip))
    return balls


cx, cy = CENTER
BODY = [(cx, cy, 170), (cx - 25, cy + 35, 135), (cx + 35, cy - 25, 125)]
ARMS = (
    arm(-42, 375, 18, 48)  # the long one to the top right
    + arm(138, 345, 18, 40)  # the long one to the bottom left
    + arm(10, 290, 20, 30)
    + arm(-112, 285, 20, 30)
    + arm(84, 300, 20, 34)
    + arm(194, 275, 20, 27)
    + arm(-160, 245, 18, 22)
    + arm(50, 255, 18, 24)
)
# droplets flying off, with the smallest icon size that still shows them
DROPLETS = [
    ((828, 192, 30), 32),
    ((165, 860, 24), 32),
    ((880, 470, 18), 64),
    ((230, 210, 16), 64),
    ((700, 860, 17), 64),
]

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def field(balls: list[Ball]) -> np.ndarray:
    """Metaballs: every ball adds (r/d)^6, the splat is where the sum reaches 1."""
    y, x = np.mgrid[0:UNITS, 0:UNITS].astype(np.float32)
    total = np.zeros((UNITS, UNITS), np.float32)
    for bx, by, r in balls:
        d2 = (x - bx) ** 2 + (y - by) ** 2 + 1e-3
        total += (r * r / d2) ** 3
    return total


@cache
def splat(droplets: int) -> QPainterPath:
    """The traced splat with the first `droplets` droplets, as a bezier path."""
    balls = BODY + ARMS + [ball for ball, _ in DROPLETS[:droplets]]
    plist = paths.trace_mask(field(balls) >= 1.0, alphamax=1.3, tolerance=0.1)

    path = QPainterPath()
    for knots in paths.subpaths(plist):
        path.moveTo(*knots[0][1])
        for (_, _, out), (into, anchor, _) in zip(
            knots, knots[1:] + knots[:1], strict=True
        ):
            path.cubicTo(QPointF(*out), QPointF(*into), QPointF(*anchor))
        path.closeSubpath()
    return path


def squircle(size: float, n: float = 5, steps: int = 720) -> QPainterPath:
    r = size / 2
    path = QPainterPath()
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = r + r * math.copysign(abs(c) ** (2 / n), c)
        y = r + r * math.copysign(abs(s) ** (2 / n), s)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def artwork(size: int) -> QImage:
    """The squircle tile with the ink splat, filling a `size` canvas."""
    scale = size / UNITS

    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)

    tile = squircle(UNITS)
    p.setClipPath(tile)
    background = QLinearGradient(0, 0, 0, UNITS)
    background.setColorAt(0, TILE_TOP)
    background.setColorAt(1, TILE_BOTTOM)
    p.fillPath(tile, QBrush(background))
    glow = QRadialGradient(QPointF(*CENTER), 560)
    glow.setColorAt(0, QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 90))
    glow.setColorAt(1, QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 0))
    p.fillPath(tile, QBrush(glow))

    ink = splat(sum(size >= smallest for _, smallest in DROPLETS))
    p.fillPath(ink.translated(0, 20), QColor(0, 0, 0, 95))  # drop shadow

    fill = QLinearGradient(QPointF(230, 220), QPointF(780, 840))
    fill.setColorAt(0, INK_LIGHT)
    fill.setColorAt(0.45, INK)
    fill.setColorAt(1, INK_DARK)
    p.fillPath(ink, QBrush(fill))

    if size >= 24:  # the wet shine on the ink
        shine = QPen(QColor(255, 255, 255, 175), 30 if size >= 48 else 42)
        shine.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(shine)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = 125
        p.drawArc(round(cx - r), round(cy - r), 2 * r, 2 * r, 100 * 16, 72 * 16)
        if size >= 48:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 205))
            p.drawEllipse(QPointF(758, 266), 13, 13)  # on the big bulb

    # hairline highlight along the tile edge
    p.setClipping(False)
    p.strokePath(
        squircle(UNITS - 4).translated(2, 2), QPen(QColor(255, 255, 255, 36), 4)
    )
    p.end()
    return image


def windows_icon(size: int) -> QImage:
    """Tile filling the canvas with a hair of margin, like Windows 11 icons."""
    margin = max(1, round(size * 0.03))
    canvas = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)
    p.drawImage(margin, margin, artwork(size - 2 * margin))
    p.end()
    return canvas


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def write_ico(path: Path, images: list[QImage]) -> None:
    """An .ico with PNG compressed frames, which Windows reads since Vista."""
    frames = [png_bytes(image) for image in images]
    offset = 6 + 16 * len(frames)
    entries = []
    for image, frame in zip(images, frames, strict=True):
        side = image.width() % 256  # 0 means 256
        entries.append(
            struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(frame), offset)
        )
        offset += len(frame)
    path.write_bytes(
        struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(frames)
    )


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv)  # noqa: F841 - keeps Qt's painting set up

    OUT.mkdir(parents=True, exist_ok=True)
    windows_icon(1024).save(str(OUT / "clex.png"))
    write_ico(OUT / "clex.ico", [windows_icon(s) for s in ICO_SIZES])
    print(f"icons written to {OUT}")


if __name__ == "__main__":
    main()

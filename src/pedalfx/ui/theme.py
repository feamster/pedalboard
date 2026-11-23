"""Colours, pedal finishes, board skins and shared painting helpers."""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

# name -> enclosure colour, lettering colour, knob style
FINISHES = {
    "graphite":  {"body": "#3d4349", "text": "#f0f2f4", "knob": "silver"},
    "gold":      {"body": "#d9a62e", "text": "#2b1d02", "knob": "black"},
    "tangerine": {"body": "#e4661c", "text": "#fff4e6", "knob": "black"},
    "violet":    {"body": "#5a3fa6", "text": "#f3ecff", "knob": "silver"},
    "sky":       {"body": "#3d9fd6", "text": "#04263b", "knob": "cream"},
    "mint":      {"body": "#7fceae", "text": "#0c3528", "knob": "black"},
    "cream":     {"body": "#e7ddc3", "text": "#3b2a18", "knob": "black"},
    "ocean":     {"body": "#175f7c", "text": "#e2f6ff", "knob": "silver"},
    "pearl":     {"body": "#e3e7eb", "text": "#1c2632", "knob": "black"},
    "crimson":   {"body": "#b0252d", "text": "#fff0ee", "knob": "cream"},
    "midnight":  {"body": "#191b1f", "text": "#e9edf2", "knob": "silver"},
    "seafoam":   {"body": "#9fd8cf", "text": "#143b38", "knob": "cream"},
}

BOARD_SKINS = ("walnut", "tolex", "aluminum", "stage")

MODULE_COLORS = ("#e2553a", "#e3a51a", "#2f97d3", "#8759cf")  # console modules

UI_BG = "#16181b"
UI_PANEL = "#1f2226"
UI_TEXT = "#d9dde2"
UI_DIM = "#8b929b"
UI_ACCENT = "#ffb224"


def finish_of(pedal) -> dict:
    return FINISHES.get(pedal.finish or pedal.FINISH, FINISHES["graphite"])


def font(px: int, bold: bool = False, family: str = "ui", spacing: float = 0.0) -> QFont:
    f = QFont()
    families = {
        "ui": ["Helvetica Neue", "Arial"],
        "logo": ["Futura", "Avenir Next", "Helvetica Neue", "Arial"],
        "mono": ["Menlo", "Monaco", "Courier New"],
    }[family]
    f.setFamilies(families)
    f.setPixelSize(px)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def fit_font(text: str, max_width: float, start_px: int, **kwargs) -> QFont:
    """Largest font (<= start_px) at which ``text`` fits in ``max_width``."""
    from PyQt6.QtGui import QFontMetricsF

    px = start_px
    while px > 8:
        f = font(px, **kwargs)
        if QFontMetricsF(f).horizontalAdvance(text) <= max_width:
            return f
        px -= 1
    return font(px, **kwargs)


def draw_led(p: QPainter, center: QPointF, radius: float, color: QColor, on: bool) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    if on:
        glow = QRadialGradient(center, radius * 3.4)
        c = QColor(color)
        c.setAlpha(150)
        glow.setColorAt(0.0, c)
        c.setAlpha(0)
        glow.setColorAt(1.0, c)
        p.setBrush(glow)
        p.drawEllipse(center, radius * 3.4, radius * 3.4)
    p.setBrush(QColor(20, 20, 22))
    p.drawEllipse(center, radius + 1.6, radius + 1.6)
    lens = QRadialGradient(center + QPointF(-radius * 0.3, -radius * 0.3), radius * 1.3)
    if on:
        lens.setColorAt(0.0, QColor(255, 255, 255))
        lens.setColorAt(0.35, QColor(color).lighter(130))
        lens.setColorAt(1.0, QColor(color))
    else:
        lens.setColorAt(0.0, QColor(color).darker(260))
        lens.setColorAt(1.0, QColor(color).darker(520))
    p.setBrush(lens)
    p.drawEllipse(center, radius, radius)
    p.restore()


def draw_screw(p: QPainter, center: QPointF, radius: float = 4.0, angle: float = 30.0) -> None:
    p.save()
    p.setPen(QPen(QColor(0, 0, 0, 110), 0.8))
    g = QRadialGradient(center + QPointF(-1, -1), radius * 1.4)
    g.setColorAt(0.0, QColor("#f2f2f2"))
    g.setColorAt(1.0, QColor("#7b7f84"))
    p.setBrush(g)
    p.drawEllipse(center, radius, radius)
    p.setPen(QPen(QColor(40, 40, 44, 200), 1.1))
    dx = math.cos(math.radians(angle)) * radius * 0.7
    dy = math.sin(math.radians(angle)) * radius * 0.7
    p.drawLine(center + QPointF(-dx, -dy), center + QPointF(dx, dy))
    p.restore()


def draw_enclosure(p: QPainter, rect: QRectF, body: QColor, lifted: bool = False,
                   radius: float = 14.0, screws: bool = True) -> None:
    """A painted metal stompbox enclosure with drop shadow, bevel and gloss."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    depth = 9 if lifted else 5
    for i in range(depth):
        p.setBrush(QColor(0, 0, 0, 20 if lifted else 26))
        grow = i * 0.9
        p.drawRoundedRect(rect.adjusted(-grow * 0.5, 2 + i * 1.4, grow * 0.5, 3 + i * 1.6),
                          radius + grow, radius + grow)
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, body.lighter(122))
    grad.setColorAt(0.45, body)
    grad.setColorAt(1.0, body.darker(132))
    p.setBrush(grad)
    p.setPen(QPen(body.darker(190), 1.2))
    p.drawRoundedRect(rect, radius, radius)
    # bevel highlight
    edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    edge.setColorAt(0.0, QColor(255, 255, 255, 120))
    edge.setColorAt(0.5, QColor(255, 255, 255, 18))
    edge.setColorAt(1.0, QColor(0, 0, 0, 50))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QBrush(edge), 1.6))
    p.drawRoundedRect(rect.adjusted(1.6, 1.6, -1.6, -1.6), radius - 1.5, radius - 1.5)
    # gloss
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.setClipPath(path)
    gloss = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.42))
    gloss.setColorAt(0.0, QColor(255, 255, 255, 46))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gloss)
    p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.42))
    p.setClipping(False)
    if screws:
        inset = 11.0
        for k, (sx, sy) in enumerate(((rect.left() + inset, rect.top() + inset),
                                      (rect.right() - inset, rect.top() + inset),
                                      (rect.left() + inset, rect.bottom() - inset),
                                      (rect.right() - inset, rect.bottom() - inset))):
            draw_screw(p, QPointF(sx, sy), 3.6, angle=25 + 50 * k)
    p.restore()


def metal_gradient(center: QPointF, start_angle: float = 0.0) -> QConicalGradient:
    g = QConicalGradient(center, start_angle)
    for stop, color in ((0.0, "#f6f6f6"), (0.12, "#9b9fa4"), (0.25, "#eeeeee"),
                        (0.4, "#7f8388"), (0.5, "#f2f2f2"), (0.63, "#93979c"),
                        (0.75, "#ececec"), (0.88, "#80848a"), (1.0, "#f6f6f6")):
        g.setColorAt(stop, QColor(color))
    return g


_tile_cache: dict = {}


def board_tile(skin: str, height: int, width: int = 960) -> QPixmap:
    """Procedurally painted, horizontally tileable board surface."""
    key = (skin, height)
    if key in _tile_cache:
        return _tile_cache[key]
    if len(_tile_cache) > 12:
        _tile_cache.clear()
    pm = QPixmap(width, max(1, height))
    rng = random.Random(11)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    if skin == "walnut":
        plank = 92
        for row, y in enumerate(range(0, height, plank)):
            base = QColor(["#5b3a22", "#52331d", "#603f26", "#4c2f1a"][row % 4])
            g = QLinearGradient(0, y, 0, y + plank)
            g.setColorAt(0.0, base.lighter(112))
            g.setColorAt(1.0, base.darker(112))
            p.fillRect(0, y, width, plank, g)
            for _ in range(46):  # straight grain lines tile seamlessly
                gy = y + rng.random() * plank
                shade = QColor(20, 8, 0, rng.randint(10, 46)) if rng.random() < 0.7 \
                    else QColor(255, 210, 160, rng.randint(6, 22))
                p.setPen(QPen(shade, rng.choice((0.6, 1.0, 1.6))))
                p.drawLine(QPointF(0, gy), QPointF(width, gy))
            p.fillRect(0, y, width, 2, QColor(0, 0, 0, 120))
            p.fillRect(0, y + 2, width, 1, QColor(255, 220, 180, 26))
    elif skin == "tolex":
        p.fillRect(0, 0, width, height, QColor("#17181a"))
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(int(width * height / 26)):
            x, y = rng.random() * width, rng.random() * height
            p.setBrush(QColor(255, 255, 255, rng.randint(5, 20)) if rng.random() < 0.5
                       else QColor(0, 0, 0, rng.randint(30, 90)))
            p.drawEllipse(QPointF(x, y), rng.uniform(0.6, 1.5), rng.uniform(0.6, 1.5))
    elif skin == "aluminum":
        p.fillRect(0, 0, width, height, QColor("#08090a"))
        rail, gap = 74, 20
        y = 12
        while y < height:
            g = QLinearGradient(0, y, 0, y + rail)
            g.setColorAt(0.0, QColor("#565b61"))
            g.setColorAt(0.08, QColor("#3a3e43"))
            g.setColorAt(0.9, QColor("#2a2d31"))
            g.setColorAt(1.0, QColor("#17191b"))
            p.fillRect(0, y, width, rail, g)
            for _ in range(60):  # brushed streaks
                gy = y + rng.random() * rail
                p.setPen(QPen(QColor(255, 255, 255, rng.randint(4, 16)), 0.7))
                p.drawLine(QPointF(0, gy), QPointF(width, gy))
            y += rail + gap
    else:  # stage: charcoal carpet
        p.fillRect(0, 0, width, height, QColor("#1d1f23"))
        for _ in range(int(width * height / 14)):
            x, y = rng.random() * width, rng.random() * height
            p.setPen(QPen(QColor(255, 255, 255, rng.randint(4, 15)) if rng.random() < 0.5
                          else QColor(0, 0, 0, rng.randint(20, 70)), 1))
            p.drawPoint(QPointF(x, y))
    p.end()
    _tile_cache[key] = pm
    return pm

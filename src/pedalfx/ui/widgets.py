"""Custom-painted controls: knobs, footswitches, slide switches, meters."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from .theme import draw_led, font, metal_gradient


class Knob(QWidget):
    """Rotary knob. Drag up/down (Shift = fine), scroll, double-click to reset."""

    changed = pyqtSignal(float)  # normalised 0..1

    def __init__(self, label: str, norm: float = 0.5, default: float = 0.5,
                 style: str = "black", text_color: str = "#ffffff",
                 diameter: int = 48, accent: str | None = None, formatter=None,
                 parent=None):
        super().__init__(parent)
        self.label = label
        self.norm = norm
        self.default = default
        self.style = style
        self.text_color = QColor(text_color)
        self.diameter = diameter
        self.accent = QColor(accent) if accent else None
        self.formatter = formatter  # norm -> display string
        self._drag = None
        self._hover = False
        self.focused = False     # the knob the up/down keys are adjusting
        self.setFixedSize(diameter + 30, diameter + 34)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return self.size()

    def set_norm(self, norm: float, emit: bool = False) -> None:
        norm = min(1.0, max(0.0, norm))
        if norm != self.norm:
            self.norm = norm
            self.update()
            if emit:
                self.changed.emit(norm)

    # -- interaction --------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = (e.globalPosition().y(), self.norm)
            self.update()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._drag:
            y0, n0 = self._drag
            span = 900.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 170.0
            self.set_norm(n0 + (y0 - e.globalPosition().y()) / span, emit=True)
        e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self.set_norm(self.default, emit=True)
        e.accept()

    def wheelEvent(self, e):
        delta = e.angleDelta().y() or e.angleDelta().x()
        if delta:
            self.set_norm(self.norm + (0.02 if delta > 0 else -0.02), emit=True)
        e.accept()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    # -- painting -----------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.diameter / 2.0
        c = QPointF(self.width() / 2.0, 9 + r)
        tick = QColor(self.text_color)
        for i in range(11):
            ang = math.radians(225 - i * 27)
            tick.setAlpha(170 if i in (0, 5, 10) else 90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tick)
            p.drawEllipse(c + QPointF(math.cos(ang), -math.sin(ang)) * (r + 5.5), 1.2, 1.2)
        p.setBrush(QColor(0, 0, 0, 85))
        p.drawEllipse(c + QPointF(0, 3.5), r + 0.5, r + 0.5)

        pointer = QColor("#f4f4f4")
        if self.style == "silver":
            p.setPen(QPen(QColor(40, 42, 46), 1))
            p.setBrush(metal_gradient(c, 20))
            p.drawEllipse(c, r, r)
            p.setPen(QPen(QColor(0, 0, 0, 70), 0.8))
            p.setBrush(metal_gradient(c, 110))
            p.drawEllipse(c, r * 0.74, r * 0.74)
            pointer = QColor("#1c1d20")
        elif self.style == "cream":
            g = QRadialGradient(c + QPointF(-r * 0.3, -r * 0.35), r * 1.5)
            g.setColorAt(0.0, QColor("#fffdf2"))
            g.setColorAt(0.6, QColor("#e9e0c4"))
            g.setColorAt(1.0, QColor("#b3a884"))
            p.setPen(QPen(QColor(70, 60, 40), 1))
            p.setBrush(g)
            p.drawEllipse(c, r, r)
            p.setPen(QPen(QColor(120, 105, 75, 140), 0.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r * 0.72, r * 0.72)
            pointer = QColor("#22201c")
        else:  # black bakelite
            g = QRadialGradient(c + QPointF(-r * 0.35, -r * 0.4), r * 1.6)
            g.setColorAt(0.0, QColor("#6a6a6a"))
            g.setColorAt(0.45, QColor("#222222"))
            g.setColorAt(1.0, QColor("#050505"))
            p.setPen(QPen(QColor(0, 0, 0), 1))
            p.setBrush(g)
            p.drawEllipse(c, r, r)
            cap = QLinearGradient(c + QPointF(0, -r * 0.7), c + QPointF(0, r * 0.7))
            cap.setColorAt(0.0, QColor("#4a4a4a"))
            cap.setColorAt(1.0, QColor("#141414"))
            p.setPen(QPen(QColor(255, 255, 255, 34), 0.8))
            p.setBrush(cap)
            p.drawEllipse(c, r * 0.72, r * 0.72)
        if self.accent:
            p.setPen(QPen(self.accent, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r * 0.72, r * 0.72)

        ang = math.radians(225 - 270 * self.norm)
        d = QPointF(math.cos(ang), -math.sin(ang))
        p.setPen(QPen(pointer, max(2.2, r * 0.11), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(c + d * (r * 0.28), c + d * (r * 0.9))

        active = self._drag is not None or self._hover or self.focused
        text = self.formatter(self.norm) if (active and self.formatter) else self.label.upper()
        if self.focused:   # a thin ring in the pedal's own lettering colour
            ring = QColor(self.text_color)
            ring.setAlpha(200)
            p.setPen(QPen(ring, 1.3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r + 3.0, r + 3.0)
        p.setPen(self.text_color)
        p.setFont(font(10, bold=True, spacing=0.0 if active else 0.6))
        p.drawText(QRectF(-10, 9 + self.diameter + 7, self.width() + 20, 15),
                   Qt.AlignmentFlag.AlignCenter, text)


class FootSwitch(QWidget):
    pressed = pyqtSignal()   # on the way down - use this when timing matters
    clicked = pyqtSignal()

    def __init__(self, parent=None, size: int = 58):
        super().__init__(parent)
        self._down = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
            self.pressed.emit()
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = self.width() / 2.0 - 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawEllipse(c + QPointF(0, 3), r, r)
        nut = QPolygonF([c + QPointF(math.cos(math.radians(a)), math.sin(math.radians(a))) * r
                         for a in range(0, 360, 60)])
        p.setPen(QPen(QColor(50, 52, 56), 1))
        p.setBrush(metal_gradient(c, 45))
        p.drawPolygon(nut)
        p.setBrush(metal_gradient(c, 150))
        p.drawEllipse(c, r * 0.74, r * 0.74)
        off = QPointF(0, 1.5) if self._down else QPointF(0, 0)
        dome = QRadialGradient(c + off + QPointF(-r * 0.2, -r * 0.25), r * 0.9)
        dome.setColorAt(0.0, QColor("#dcdcdc") if self._down else QColor("#ffffff"))
        dome.setColorAt(0.55, QColor("#a9adb2"))
        dome.setColorAt(1.0, QColor("#5d6166"))
        p.setPen(QPen(QColor(40, 42, 46), 1))
        p.setBrush(dome)
        p.drawEllipse(c + off, r * 0.56, r * 0.56)


class SlideSwitch(QWidget):
    """Multi-position slide switch with a label under each position."""

    changed = pyqtSignal(int)

    def __init__(self, choices, index: int = 0, text_color: str = "#ffffff",
                 width: int = 168, parent=None):
        super().__init__(parent)
        self.choices = list(choices)
        self.index = index
        self.text_color = QColor(text_color)
        self.setFixedSize(width, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _slot_x(self, i: int) -> float:
        cell = self.width() / len(self.choices)
        return cell * (i + 0.5)

    def set_index(self, index: int, emit: bool = False) -> None:
        index = max(0, min(len(self.choices) - 1, int(index)))
        if index != self.index:
            self.index = index
            self.update()
            if emit:
                self.changed.emit(index)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            cell = self.width() / len(self.choices)
            self.set_index(int(e.position().x() // cell), emit=True)
        e.accept()

    def wheelEvent(self, e):
        self.set_index(self.index + (1 if e.angleDelta().y() < 0 else -1), emit=True)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, x1 = self._slot_x(0), self._slot_x(len(self.choices) - 1)
        track = QRectF(x0 - 14, 3, x1 - x0 + 28, 16)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(8, 8, 10))
        p.drawRoundedRect(track, 8, 8)
        handle = QRectF(self._slot_x(self.index) - 11, 4.5, 22, 13)
        g = QLinearGradient(handle.topLeft(), handle.bottomLeft())
        g.setColorAt(0.0, QColor("#ffffff"))
        g.setColorAt(0.5, QColor("#b5b9be"))
        g.setColorAt(1.0, QColor("#6d7176"))
        p.setPen(QPen(QColor(30, 30, 34), 1))
        p.setBrush(g)
        p.drawRoundedRect(handle, 6, 6)
        cell = self.width() / len(self.choices)
        for i, name in enumerate(self.choices):
            color = QColor(self.text_color)
            color.setAlpha(255 if i == self.index else 140)
            p.setPen(color)
            p.setFont(font(10, bold=i == self.index, spacing=0.4))
            p.drawText(QRectF(cell * i, 22, cell, 14), Qt.AlignmentFlag.AlignCenter,
                       str(name).upper())


class SelectorList(QWidget):
    """Column of LED-lit effect names; clicking the lit one turns it off."""

    changed = pyqtSignal(int)  # 0 = off, 1..n = effect

    ROW = 17

    def __init__(self, names, index: int, color: str, text_color: str,
                 width: int = 106, parent=None):
        super().__init__(parent)
        self.names = list(names)
        self.index = index
        self.color = QColor(color)
        self.text_color = QColor(text_color)
        self.setFixedSize(width, self.ROW * len(self.names))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_index(self, index: int, emit: bool = False) -> None:
        if index != self.index:
            self.index = index
            self.update()
            if emit:
                self.changed.emit(index)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            row = int(e.position().y() // self.ROW) + 1
            if 1 <= row <= len(self.names):
                self.set_index(0 if row == self.index else row, emit=True)
        e.accept()

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() < 0 else -1
        self.set_index(max(0, min(len(self.names), self.index + step)), emit=True)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, name in enumerate(self.names):
            on = self.index == i + 1
            y = i * self.ROW
            draw_led(p, QPointF(9, y + self.ROW / 2.0), 3.4, self.color, on)
            color = QColor(self.text_color)
            color.setAlpha(255 if on else 150)
            p.setPen(color)
            p.setFont(font(11, bold=on))
            p.drawText(QRectF(20, y, self.width() - 20, self.ROW),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)


class LevelMeter(QWidget):
    """Segmented horizontal peak meter with a slow-falling peak."""

    SEGMENTS = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.setFixedSize(108, 10)

    def feed(self, peak: float) -> None:
        db = 20.0 * math.log10(max(peak, 1e-5))
        target = min(1.0, max(0.0, (db + 54.0) / 54.0))
        self.level = target if target > self.level else max(target, self.level - 0.035)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w = self.width() / self.SEGMENTS
        lit = int(round(self.level * self.SEGMENTS))
        for i in range(self.SEGMENTS):
            frac = i / (self.SEGMENTS - 1)
            color = QColor("#35d07f") if frac < 0.66 else QColor("#f0c23b") if frac < 0.88 \
                else QColor("#f04a3b")
            if i >= lit:
                color = color.darker(430)
            p.fillRect(QRectF(i * w, 0, w - 1.5, self.height()), color)


class PowerButton(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on = False
        self.setFixedSize(46, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Start / stop the audio engine")

    def set_on(self, on: bool) -> None:
        self.on = on
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(not self.on)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = 18.0
        glow = QColor("#39e58c") if self.on else QColor("#5b626b")
        if self.on:
            halo = QRadialGradient(c, 23)
            h = QColor(glow)
            h.setAlpha(120)
            halo.setColorAt(0.6, h)
            h.setAlpha(0)
            halo.setColorAt(1.0, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, 23, 23)
        g = QLinearGradient(c + QPointF(0, -r), c + QPointF(0, r))
        g.setColorAt(0.0, QColor("#3b4047"))
        g.setColorAt(1.0, QColor("#1b1e22"))
        p.setPen(QPen(glow, 1.6))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        p.setPen(QPen(glow, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(c.x() - 8, c.y() - 7, 16, 16), 125 * 16, 290 * 16)
        p.drawLine(c + QPointF(0, -10), c + QPointF(0, -2))


class CycleField(QWidget):
    """Labelled value window; click the right half for next, the left for previous."""

    changed = pyqtSignal(int)

    def __init__(self, label: str, choices, index: int = 0, text_color: str = "#ffffff",
                 width: int = 132, parent=None):
        super().__init__(parent)
        self.label = label
        self.choices = list(choices)
        self.index = index
        self.text_color = QColor(text_color)
        self.setFixedSize(width, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_index(self, index: int, emit: bool = False) -> None:
        index = int(index) % len(self.choices)
        if index != self.index:
            self.index = index
            self.update()
            if emit:
                self.changed.emit(index)

    def mousePressEvent(self, e):
        back = e.button() == Qt.MouseButton.RightButton or e.position().x() < self.width() / 2
        self.set_index(self.index + (-1 if back else 1), emit=True)
        e.accept()

    def contextMenuEvent(self, e):
        e.accept()   # right-click steps backwards; don't open the pedal menu

    def wheelEvent(self, e):
        self.set_index(self.index + (1 if e.angleDelta().y() < 0 else -1), emit=True)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dim = QColor(self.text_color)
        dim.setAlpha(190)
        p.setPen(dim)
        p.setFont(font(9, bold=True, spacing=1.0))
        p.drawText(QRectF(2, 0, self.width(), 12), Qt.AlignmentFlag.AlignVCenter, self.label.upper())
        box = QRectF(0.5, 14.5, self.width() - 1, 22)
        p.setPen(QPen(QColor(0, 0, 0, 170), 1))
        p.setBrush(QColor("#10161b"))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#4f9d86"))
        p.setFont(font(9, bold=True))
        p.drawText(QRectF(box.left(), box.top(), 16, box.height()), Qt.AlignmentFlag.AlignCenter, "◀")
        p.drawText(QRectF(box.right() - 16, box.top(), 16, box.height()),
                   Qt.AlignmentFlag.AlignCenter, "▶")
        p.setPen(QColor("#7fe3c1"))
        p.setFont(font(12, bold=True, family="mono"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(self.choices[self.index]))


class PadButton(QWidget):
    """Small rubber pad with a caption, a keyboard hint and an optional LED."""

    pressed = pyqtSignal()

    def __init__(self, label: str, hint: str = "", lit=None, parent=None):
        super().__init__(parent)
        self.label = label
        self.hint = hint
        self.lit = lit      # callable -> bool, or None for no LED
        self._down = False
        self.setFixedSize(50, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
            self.pressed.emit()
        e.accept()

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1 + (1 if self._down else 0), self.width() - 2, self.height() - 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(rect.translated(0, 2), 6, 6)
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0.0, QColor("#3a3d42") if not self._down else QColor("#2a2c30"))
        g.setColorAt(1.0, QColor("#1d1f22"))
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.setBrush(g)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QColor("#e8eaed"))
        p.setFont(font(9, bold=True, spacing=0.6))
        p.drawText(QRectF(rect.left(), rect.top() + 4, rect.width(), 13),
                   Qt.AlignmentFlag.AlignCenter, self.label.upper())
        p.setPen(QColor(255, 255, 255, 110))
        p.setFont(font(9, family="mono"))
        p.drawText(QRectF(rect.left(), rect.top() + 17, rect.width(), 13),
                   Qt.AlignmentFlag.AlignCenter, self.hint)
        if self.lit is not None:
            draw_led(p, QPointF(rect.left() + 7, rect.top() + 7), 2.6, QColor("#39e58c"),
                     bool(self.lit()))

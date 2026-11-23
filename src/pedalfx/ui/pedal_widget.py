"""The on-board pedal widgets: a generic stompbox and the Prism Console."""

from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ..dsp.console import CONSOLE_PRESETS, EFFECTS, MODULE_KEYS, MODULES
from .theme import MODULE_COLORS, draw_enclosure, draw_led, finish_of, fit_font, font
from .widgets import CycleField, FootSwitch, Knob, PadButton, SelectorList, SlideSwitch

PAD_X, PAD_TOP, PAD_BOTTOM = 12, 8, 22
BODY_H = 404
LED_COLOR = QColor("#ff3b30")


class PedalWidget(QWidget):
    """A stompbox built automatically from a pedal's parameter list."""

    edited = pyqtSignal()  # a knob, switch or the footswitch changed
    BODY_W = 206

    def __init__(self, pedal, board):
        super().__init__(board)
        self.pedal = pedal
        self.board = board
        self.lifted = False
        self.controls: dict = {}
        self._face: QPixmap | None = None
        self._face_key = None
        self.setFixedSize(self.BODY_W + 2 * PAD_X, BODY_H + PAD_TOP + PAD_BOTTOM)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.foot = FootSwitch(self)
        self.foot.clicked.connect(self.toggle)
        self._build()

    # -- geometry -----------------------------------------------------
    @property
    def body(self) -> QRectF:
        return QRectF(PAD_X, PAD_TOP, self.BODY_W, BODY_H)

    def jack_y(self) -> float:
        return PAD_TOP + 118.0

    def _place(self, widget, cx: float, top: float) -> None:
        widget.move(int(PAD_X + cx - widget.width() / 2), int(PAD_TOP + top))

    # -- controls -----------------------------------------------------
    def _make_knob(self, param, diameter=48, accent=None, label=None) -> Knob:
        fin = finish_of(self.pedal)
        knob = Knob(label or param.label, param.to_norm(self.pedal.get(param.key)),
                    param.to_norm(param.default), fin["knob"], fin["text"], diameter,
                    accent, lambda t, p=param: p.format(p.from_norm(t)), self)
        knob.changed.connect(lambda t, p=param: self._set(p.key, p.from_norm(t)))
        self.controls[param.key] = knob
        return knob

    def _set(self, key: str, value) -> None:
        self.pedal.set(key, value)
        self.edited.emit()

    def _build(self) -> None:
        fin = finish_of(self.pedal)
        knobs = [p for p in self.pedal.PARAMS if not p.is_choice]
        choices = [p for p in self.pedal.PARAMS if p.is_choice]
        left, right, mid = self.BODY_W * 0.26, self.BODY_W * 0.74, self.BODY_W * 0.5
        if len(knobs) == 4:
            spots = [(left, 30), (right, 30), (left, 116), (right, 116)]
        elif len(knobs) == 3:
            spots = [(left, 30), (right, 30), (mid, 108)]
        else:
            spots = [(left, 56), (right, 56)]
        for param, (cx, top) in zip(knobs, spots):
            self._place(self._make_knob(param), cx, top)
        for param in choices[:1]:
            switch = SlideSwitch(param.choices, int(self.pedal.get(param.key)),
                                 fin["text"], self.BODY_W - 34, self)
            switch.changed.connect(lambda i, p=param: self._set(p.key, i))
            self.controls[param.key] = switch
            self._place(switch, mid, 208)
        self._place(self.foot, mid, 326)

    def rebuild(self) -> None:
        """Recreate the controls (after a finish change)."""
        for widget in self.controls.values():
            widget.setParent(None)
            widget.deleteLater()
        self.controls = {}
        self._build()
        for widget in self.controls.values():
            widget.show()
        self.update()

    def refresh(self) -> None:
        """Pull every control's position back from the pedal's values."""
        for param in self.pedal.PARAMS:
            widget = self.controls.get(param.key)
            if isinstance(widget, Knob):
                widget.set_norm(param.to_norm(self.pedal.get(param.key)))
            elif widget is not None:
                widget.set_index(int(self.pedal.get(param.key)))
        self.update()

    def shutdown(self) -> None:
        """Stop any timers; called when the pedal leaves the board."""
        for name in ("_poll", "_tick"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()

    def toggle(self) -> None:
        self.pedal.enabled = not self.pedal.enabled
        self.update()
        self.edited.emit()

    # -- dragging is delegated to the board ---------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.body.contains(e.position()):
            self.board.begin_drag(self, e.globalPosition())
        e.accept()

    def mouseMoveEvent(self, e):
        self.board.drag_to(self, e.globalPosition())
        e.accept()

    def mouseReleaseEvent(self, e):
        self.board.end_drag(self)
        e.accept()

    def contextMenuEvent(self, e):
        self.board.pedal_menu(self, e.globalPos())

    def moveEvent(self, _):
        board = getattr(self, "board", None)
        if board is not None:
            board.update()  # cables follow the pedal

    # -- painting -----------------------------------------------------
    def _paint_key(self) -> tuple:
        """Everything the painted face depends on (knobs paint themselves)."""
        return (self.pedal.enabled, self.lifted, self.pedal.finish)

    def paintEvent(self, _):
        # The face is static between interactions, so it is rendered once and
        # blitted; that keeps repaints during drags off the audio thread's back.
        key = (self._paint_key(), self.devicePixelRatioF())
        if self._face is None or self._face_key != key:
            dpr = self.devicePixelRatioF()
            self._face = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            self._face.setDevicePixelRatio(dpr)
            self._face.fill(Qt.GlobalColor.transparent)
            painter = QPainter(self._face)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_face(painter)
            painter.end()
            self._face_key = key
        QPainter(self).drawPixmap(0, 0, self._face)

    def _paint_face(self, p: QPainter) -> None:
        fin = finish_of(self.pedal)
        body = self.body
        draw_enclosure(p, body, QColor(fin["body"]), self.lifted)
        text = QColor(fin["text"])
        draw_led(p, QPointF(body.center().x(), body.top() + 22), 5.0, LED_COLOR,
                 self.pedal.enabled)
        plate = QRectF(body.left() + 14, body.top() + 252, body.width() - 28, 62)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 44))
        p.drawRoundedRect(plate, 8, 8)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(plate.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        name = self.pedal.NAME.upper()
        p.setPen(text)
        p.setFont(fit_font(name, plate.width() - 16, 30, bold=True, family="logo", spacing=1.5))
        p.drawText(QRectF(plate.left(), plate.top() + 4, plate.width(), 36),
                   Qt.AlignmentFlag.AlignCenter, name)
        dim = QColor(text)
        dim.setAlpha(190)
        p.setPen(dim)
        tag = self.pedal.TAGLINE.upper()
        p.setFont(fit_font(tag, plate.width() - 12, 10, bold=True, spacing=1.0))
        p.drawText(QRectF(plate.left(), plate.top() + 40, plate.width(), 16),
                   Qt.AlignmentFlag.AlignCenter, tag)


class ConsoleWidget(PedalWidget):
    """Prism Console: four global knobs over four swappable effect modules."""

    BODY_W = 500
    COL_W = 118
    ZONE_TOP, ZONE_H = 128, 196

    def _col_x(self, slot: int) -> float:
        start = (self.BODY_W - 4 * self.COL_W) / 2.0
        return start + self.COL_W * (slot + 0.5)

    def _build(self) -> None:
        pedal = self.pedal
        fin = finish_of(pedal)
        for slot, key in enumerate(("tilt", "rate", "time", "mix")):
            self._place(self._make_knob(pedal.param(key), diameter=42), self._col_x(slot), 38)
        self.amounts, self.selectors = [], []
        for m, key in enumerate(MODULE_KEYS):
            knob = self._make_knob(pedal.param(f"{key}_amt"), diameter=46,
                                   accent=MODULE_COLORS[m])
            fx = pedal.param(f"{key}_fx")
            selector = SelectorList(EFFECTS[key], int(pedal.get(fx.key)), MODULE_COLORS[m],
                                    fin["text"], self.COL_W - 14, self)
            selector.changed.connect(lambda i, k=fx.key: self._set(k, i))
            self.controls[fx.key] = selector
            self.amounts.append(knob)
            self.selectors.append(selector)
        self._place(self._make_knob(pedal.param("level"), diameter=34), self.BODY_W - 62, 328)
        self._place(self.foot, self.BODY_W / 2.0, 336)
        self._layout_modules()

    def _layout_modules(self) -> None:
        for slot, m in enumerate(self.pedal.order):
            cx = self._col_x(slot)
            self._place(self.amounts[m], cx, self.ZONE_TOP + 20)
            self._place(self.selectors[m], cx + 2, self.ZONE_TOP + 104)
        self.update()

    def refresh(self) -> None:
        super().refresh()
        self._layout_modules()

    # -- hit areas ----------------------------------------------------
    def _zone(self, slot: int) -> QRectF:
        cx = PAD_X + self._col_x(slot)
        return QRectF(cx - self.COL_W / 2.0 + 3, PAD_TOP + self.ZONE_TOP,
                      self.COL_W - 6, self.ZONE_H)

    def _arrow_rects(self, slot: int):
        z = self._zone(slot)
        return (QRectF(z.left(), z.top(), 18, 18), QRectF(z.right() - 18, z.top(), 18, 18))

    def _preset_rects(self):
        body = self.body
        box = QRectF(body.right() - 226, body.top() + 10, 200, 22)
        return box, QRectF(box.left(), box.top(), 24, 22), QRectF(box.right() - 24, box.top(), 24, 22)

    def _step_preset(self, step: int) -> None:
        names = list(CONSOLE_PRESETS)
        if self.pedal.preset_name in names:
            target = (names.index(self.pedal.preset_name) + step) % len(names)
        else:  # from hand-tweaked "Custom" settings, start at either end of the list
            target = 0 if step > 0 else len(names) - 1
        self.pedal.apply_preset(names[target])
        self.refresh()
        self.edited.emit()

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MouseButton.LeftButton:
            _, prev_rect, next_rect = self._preset_rects()
            if prev_rect.contains(pos) or next_rect.contains(pos):
                self._step_preset(-1 if prev_rect.contains(pos) else 1)
                return e.accept()
            for slot in range(4):
                left, right = self._arrow_rects(slot)
                other = slot - 1 if left.contains(pos) else slot + 1 if right.contains(pos) else None
                if other is not None and 0 <= other <= 3:
                    self.pedal.swap_modules(slot, other)
                    self._layout_modules()
                    self.edited.emit()
                    return e.accept()
        super().mousePressEvent(e)

    def _set(self, key: str, value) -> None:
        super()._set(key, value)
        if self.pedal.preset_name != "Custom":
            self.pedal.preset_name = "Custom"
            self.update()

    # -- painting -----------------------------------------------------
    def _paint_key(self) -> tuple:
        pedal = self.pedal
        return (super()._paint_key(), tuple(pedal.order), pedal.preset_name,
                tuple(int(pedal.get(f"{k}_fx")) > 0 for k in MODULE_KEYS))

    def _paint_face(self, p: QPainter) -> None:
        pedal = self.pedal
        fin = finish_of(pedal)
        body = self.body
        text = QColor(fin["text"])
        draw_enclosure(p, body, QColor(fin["body"]), self.lifted)

        # prism stripe + logo
        stripe_x = body.left() + 26
        for i, color in enumerate(MODULE_COLORS):
            p.fillRect(QRectF(stripe_x + i * 7, body.top() + 12, 5, 18), QColor(color))
        p.setPen(text)
        p.setFont(font(19, bold=True, family="logo", spacing=2.0))
        p.drawText(QRectF(stripe_x + 36, body.top() + 8, 220, 26),
                   Qt.AlignmentFlag.AlignVCenter, "PRISM CONSOLE")

        # preset window
        box, prev_rect, next_rect = self._preset_rects()
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor("#10161b"))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#7fe3c1"))
        p.setFont(font(12, bold=True, family="mono"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, pedal.preset_name)
        p.setPen(QColor("#4f9d86"))
        p.drawText(prev_rect, Qt.AlignmentFlag.AlignCenter, "◀")
        p.drawText(next_rect, Qt.AlignmentFlag.AlignCenter, "▶")

        # module zones, in signal order left to right
        for slot, m in enumerate(pedal.order):
            zone = self._zone(slot)
            color = QColor(MODULE_COLORS[m])
            active = int(pedal.get(f"{MODULE_KEYS[m]}_fx")) > 0
            tint = QColor(color)
            tint.setAlpha(46 if active else 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(zone, 9, 9)
            header = QRectF(zone.left(), zone.top(), zone.width(), 18)
            band = QColor(color)
            band.setAlpha(235 if active else 120)
            p.setBrush(band)
            p.drawRoundedRect(header, 9, 9)
            p.drawRect(QRectF(header.left(), header.top() + 9, header.width(), 9))
            p.setPen(QColor("#ffffff"))
            p.setFont(font(10, bold=True, spacing=1.2))
            p.drawText(header, Qt.AlignmentFlag.AlignCenter, MODULES[m].upper())
            left, right = self._arrow_rects(slot)
            p.setFont(font(9, bold=True))
            arrow = QColor(255, 255, 255, 200)
            p.setPen(arrow)
            if slot > 0:
                p.drawText(left, Qt.AlignmentFlag.AlignCenter, "◀")
            if slot < 3:
                p.drawText(right, Qt.AlignmentFlag.AlignCenter, "▶")

        draw_led(p, QPointF(body.center().x() - 58, body.top() + 365), 5.0, LED_COLOR,
                 pedal.enabled)
        dim = QColor(text)
        dim.setAlpha(150)
        p.setPen(dim)
        p.setFont(font(9, bold=True, spacing=1.0))
        p.drawText(QRectF(body.left() + 22, body.top() + 352, 150, 26),
                   Qt.AlignmentFlag.AlignVCenter, "◀ ▶  REORDER MODULES")




# ---------------------------------------------------------------------------
class TunerDisplay(QWidget):
    """Note name plus a cents meter; reads the tuner pedal a few times a second."""

    def __init__(self, pedal, parent=None):
        super().__init__(parent)
        self.pedal = pedal
        self.reading = None
        self._misses = 0
        self._cents = 0.0
        self.setFixedSize(176, 126)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def poll(self) -> None:
        reading = self.pedal.read() if self.pedal.enabled else None
        if reading:
            same = self.reading and self.reading["note"] == reading["note"]
            self._cents = 0.6 * self._cents + 0.4 * reading["cents"] if same else reading["cents"]
            self.reading, self._misses = reading, 0
        else:
            self._misses += 1
            if self._misses > 6:   # hold the last note briefly so it doesn't flicker
                self.reading = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.setBrush(QColor("#0b1013"))
        p.drawRoundedRect(rect, 6, 6)
        cx, bar_y = rect.center().x(), 96.0
        reading = self.reading
        in_tune = reading is not None and abs(self._cents) < 3.0
        color = QColor("#39e58c") if in_tune else QColor("#ffb224")
        # cents scale: -50 .. +50
        for i in range(-5, 6):
            x = cx + i * 15
            tick = QColor("#39e58c") if i == 0 else QColor(255, 255, 255, 60)
            p.setPen(QPen(tick, 2 if i == 0 else 1))
            p.drawLine(QPointF(x, bar_y - (9 if i == 0 else 5)), QPointF(x, bar_y + (9 if i == 0 else 5)))
        if reading is None:
            p.setPen(QColor(255, 255, 255, 70))
            p.setFont(font(40, bold=True, family="logo"))
            p.drawText(QRectF(0, 6, self.width(), 62), Qt.AlignmentFlag.AlignCenter, "–")
            p.setFont(font(10, bold=True, spacing=1.0))
            p.drawText(QRectF(0, 108, self.width(), 14), Qt.AlignmentFlag.AlignCenter,
                       "PLAY A STRING" if self.pedal.enabled else "OFF")
            return
        p.setPen(color)
        p.setFont(font(52, bold=True, family="logo"))
        p.drawText(QRectF(0, 2, self.width(), 66), Qt.AlignmentFlag.AlignCenter, reading["note"])
        p.setFont(font(13, bold=True, family="mono"))
        p.drawText(QRectF(cx + 34, 40, 30, 20), Qt.AlignmentFlag.AlignLeft, str(reading["octave"]))
        p.setFont(font(16, bold=True))
        if self._cents < -3:
            p.drawText(QRectF(8, 22, 30, 30), Qt.AlignmentFlag.AlignCenter, "♭")
        elif self._cents > 3:
            p.drawText(QRectF(self.width() - 38, 22, 30, 30), Qt.AlignmentFlag.AlignCenter, "♯")
        x = cx + max(-50.0, min(50.0, self._cents)) * 1.5
        p.setPen(Qt.PenStyle.NoPen)
        glow = QColor(color)
        glow.setAlpha(70)
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(x - 7, bar_y - 13, 14, 26), 4, 4)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(x - 3, bar_y - 11, 6, 22), 2, 2)
        p.setPen(QColor(255, 255, 255, 150))
        p.setFont(font(10, bold=True, family="mono"))
        p.drawText(QRectF(0, 110, self.width(), 14), Qt.AlignmentFlag.AlignCenter,
                   f"{self._cents:+.0f} cents   {reading['freq']:.1f} Hz")


class TunerWidget(PedalWidget):
    def _build(self) -> None:
        pedal = self.pedal
        fin = finish_of(pedal)
        self.display = TunerDisplay(pedal, self)
        self.controls["_display"] = self.display
        self._place(self.display, self.BODY_W / 2.0, 34)
        self._place(self._make_knob(pedal.param("ref"), diameter=30), 46, 166)
        mode = pedal.param("mode")
        switch = SlideSwitch(mode.choices, int(pedal.get("mode")), fin["text"], 104, self)
        switch.changed.connect(lambda i: self._set("mode", i))
        self.controls["mode"] = switch
        self._place(switch, 142, 184)
        self._place(self.foot, self.BODY_W / 2.0, 326)
        if not hasattr(self, "_poll"):
            self._poll = QTimer(self)
            self._poll.timeout.connect(self._poll_display)
            self._poll.start(70)

    def _poll_display(self) -> None:
        self.display.poll()


STATE_LOOK = {   # looper state -> (label, colour)
    "empty": ("READY", "#7aa2b8"), "armed": ("ARMED", "#ffb224"), "count": ("COUNT", "#ffb224"),
    "rec": ("REC", "#ff4b3e"), "play": ("PLAY", "#39e58c"), "dub": ("DUB", "#ffb224"),
    "stop": ("STOP", "#7aa2b8"),
}
STATE_HINT = {
    "empty": "SPACE TO RECORD", "armed": "PLAY TO START", "count": "GET READY…",
    "rec": "RECORDING", "play": "SPACE TO OVERDUB", "dub": "OVERDUBBING",
    "stop": "SPACE TO PLAY",
}


class LooperDisplay(QWidget):
    """The looper's screen: state, track slots, measure/beat counter, tempo."""

    def __init__(self, pedal, parent=None):
        super().__init__(parent)
        self.pedal = pedal
        self.setFixedSize(464, 100)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.pedal.status()
        label, hex_color = STATE_LOOK[st["state"]]
        color = QColor(hex_color)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        tint = QColor(color)
        tint.setAlpha(38 if st["state"] in ("rec", "dub", "play") else 14)
        p.setPen(QPen(QColor(0, 0, 0, 220), 1))
        p.setBrush(QColor("#0b1013"))
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(rect, 6, 6)
        dim = QColor(255, 255, 255, 120)

        if not st["alive"]:
            p.setPen(dim)
            p.setFont(font(15, bold=True, family="mono"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "ENGINE OFF  ·  PRESS SPACE")
            return

        # left: state + track slots
        p.setPen(color)
        p.setFont(font(27, bold=True, family="mono"))
        p.drawText(QRectF(14, 6, 130, 36), Qt.AlignmentFlag.AlignVCenter, label)
        blink = int(time.monotonic() * 5) % 2 == 0
        for t in (0, 1):
            box = QRectF(14 + t * 54, 46, 46, 22)
            selected = st["track"] == t
            # solid = playing, faint = recorded but stopped, flashing = stopping at loop end
            sounding = st["has"][t] and st["playing"][t] and not (st["pending"][t] and blink)
            fill = QColor(color if selected else QColor("#39e58c"))
            if not sounding:
                fill.setAlpha(60 if st["has"][t] else 0)
            p.setPen(QPen(QColor("#ffffff") if selected else QColor(255, 255, 255, 60), 1.4))
            p.setBrush(fill)
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor("#0b1013") if sounding else (QColor("#ffffff") if selected else dim))
            p.setFont(font(11, bold=True, family="mono"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, f"TRK {t + 1}")

        # centre: measure counter and beat lamps
        p.setPen(dim)
        p.setFont(font(9, bold=True, spacing=1.2))
        p.drawText(QRectF(150, 8, 170, 12), Qt.AlignmentFlag.AlignCenter, "MEASURE")
        bars = st["bars"]
        if st["bar"] is not None:
            counter = f"{st['bar']}/{bars}" if bars else f"{st['bar']}"
        else:
            counter = f"–/{bars}" if bars else "FREE"
        p.setPen(QColor("#ffffff"))
        p.setFont(font(34, bold=True, family="mono"))
        p.drawText(QRectF(150, 18, 170, 40), Qt.AlignmentFlag.AlignCenter, counter)
        beats = st["beats"]
        gap = min(24.0, 150.0 / beats)
        x0 = 235 - gap * (beats - 1) / 2.0
        for b in range(beats):
            on = st["beat"] == b
            lamp = QColor(color) if on else QColor(255, 255, 255, 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(lamp)
            r = 6.0 if b == 0 else 4.5
            p.drawEllipse(QPointF(x0 + b * gap, 68), r, r)

        # right: tempo and rhythm
        p.setPen(QColor("#ffffff"))
        p.setFont(font(19, bold=True, family="mono"))
        p.drawText(QRectF(330, 6, 122, 26), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"♩={st['tempo']:.0f}")
        p.setPen(QColor("#7fe3c1") if st["drums"] else dim)
        p.setFont(font(11, bold=True, family="mono"))
        p.drawText(QRectF(300, 34, 152, 16), Qt.AlignmentFlag.AlignRight,
                   f"{st['style']} {st['part']}" if st["drums"] else "RHYTHM OFF")
        p.setPen(dim)
        p.setFont(font(10, bold=True, family="mono"))
        undo = ("  REDO✓" if st["redo"] else "  UNDO✓") if st["can_undo"] else ""
        length = f"{st['seconds']:.1f}s" if st["seconds"] else STATE_HINT[st["state"]]
        if any(st["pending"]):
            length, undo = "STOP AT LOOP END", ""
        p.drawText(QRectF(280, 54, 172, 16), Qt.AlignmentFlag.AlignRight, length + undo)

        # bottom: loop progress with a tick per measure
        bar = QRectF(14, 84, self.width() - 28, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(bar, 3, 3)
        if st["progress"] is not None:
            p.setBrush(color)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * min(1.0, st["progress"]),
                                     bar.height()), 3, 3)
        if bars and bars <= 16:
            p.setPen(QPen(QColor("#0b1013"), 1.5))
            for i in range(1, bars):
                x = bar.left() + bar.width() * i / bars
                p.drawLine(QPointF(x, bar.top()), QPointF(x, bar.bottom()))


class LooperWidget(PedalWidget):
    """Rerun: screen, settings, two footswitches and a row of pads."""

    BODY_W = 500
    FIELDS = (("measures", 88, 142), ("start", 226, 142), ("after", 88, 184),
              ("fill", 226, 184), ("style", 88, 226), ("kit", 226, 226))
    KNOBS = (("tempo", 344, 138), ("drum_level", 428, 138), ("level1", 344, 206),
             ("level2", 428, 206))
    PADS = (("track", "Track", "T"), ("drums", "Drums", "R"), ("undo", "Undo", "U"),
            ("fill", "Fill", "F"), ("next", "Part", "N"), ("clear", "Clear", "⌫"))

    def _build(self) -> None:
        pedal = self.pedal
        fin = finish_of(pedal)
        self.display = LooperDisplay(pedal, self)
        self.controls["_display"] = self.display
        self._place(self.display, self.BODY_W / 2.0, 34)
        for key, cx, top in self.FIELDS:
            param = pedal.param(key)
            field = CycleField(param.label, param.choices, int(pedal.get(key)), fin["text"], 132, self)
            field.changed.connect(lambda i, k=key: self._set(k, i))
            self.controls[key] = field
            self._place(field, cx, top)
        for key, cx, top in self.KNOBS:
            self._place(self._make_knob(pedal.param(key), diameter=34), cx, top)
        for i, (command, label, hint) in enumerate(self.PADS):
            lit = (lambda: int(pedal.get("drums")) == 1) if command == "drums" else None
            pad = PadButton(label, hint, lit, self)
            pad.pressed.connect(lambda c=command: self.send(c))
            self.controls[f"_pad_{command}"] = pad
            self._place(pad, 332 + (i % 3) * 58, 300 + (i // 3) * 44)
        if not hasattr(self, "stop_foot"):
            self.foot.clicked.disconnect()          # the big switch is REC/PLAY here, not bypass
            self.foot.pressed.connect(lambda: self.send("press"))
            self.stop_foot = FootSwitch(self)
            self.stop_foot.pressed.connect(lambda: self.send("stop"))
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._refresh_display)
            self._tick.start(33)
        stop = pedal.param("stop")     # sits above the stop switch as its caption
        field = CycleField("Stop · S", stop.choices, int(pedal.get("stop")), fin["text"], 112, self)
        field.changed.connect(lambda i: self._set("stop", i))
        self.controls["stop"] = field
        self._place(field, 216, 288)
        self._place(self.foot, 92, 333)
        self._place(self.stop_foot, 216, 333)

    def send(self, command: str) -> None:
        if self.pedal.command(command) and command == "drums":
            self.edited.emit()

    def nudge_tempo(self, delta: float) -> None:
        self._set("tempo", round(self.pedal.get("tempo")) + delta)
        self.refresh()

    def _refresh_display(self) -> None:
        if self.pedal.ui_dirty:     # the audio thread changed a value (tempo, rhythm on/off)
            self.pedal.ui_dirty = False
            self.refresh()
        self.display.update()
        self.controls["_pad_drums"].update()

    def _paint_face(self, p: QPainter) -> None:
        fin = finish_of(self.pedal)
        body = self.body
        text = QColor(fin["text"])
        draw_enclosure(p, body, QColor(fin["body"]), self.lifted)
        p.setPen(text)
        p.setFont(font(19, bold=True, family="logo", spacing=2.0))
        p.drawText(QRectF(body.left() + 26, body.top() + 6, 200, 26),
                   Qt.AlignmentFlag.AlignVCenter, "RERUN")
        dim = QColor(text)
        dim.setAlpha(190)
        p.setPen(dim)
        p.setFont(font(10, bold=True, spacing=1.4))
        p.drawText(QRectF(body.left() + 110, body.top() + 8, 364, 24),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "2-TRACK LOOPER + DRUM MACHINE")
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        y = body.top() + 286
        p.drawLine(QPointF(body.left() + 20, y), QPointF(body.right() - 20, y))
        p.setPen(text)
        p.setFont(font(10, bold=True, spacing=1.0))
        for cx, caption, key in ((92, "REC · PLAY · DUB", "SPACE"),):
            p.setPen(text)
            p.drawText(QRectF(body.left() + cx - 70, body.top() + 294, 140, 14),
                       Qt.AlignmentFlag.AlignCenter, caption)
            p.setPen(dim)
            p.drawText(QRectF(body.left() + cx - 70, body.top() + 308, 140, 14),
                       Qt.AlignmentFlag.AlignCenter, key)
            p.setFont(font(10, bold=True, spacing=1.0))


WIDGETS = {"console": ConsoleWidget, "tuner": TunerWidget, "looper": LooperWidget}


def make_pedal_widget(pedal, board) -> PedalWidget:
    return WIDGETS.get(pedal.TYPE, PedalWidget)(pedal, board)

"""The pedalboard surface (drag to reorder) and the pedal browser strip."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QMenu, QWidget

from ..dsp import PEDAL_CLASSES, create_pedal, pedal_from_dict
from .pedal_widget import BODY_H, PAD_BOTTOM, PAD_TOP, PAD_X, make_pedal_widget
from .theme import FINISHES, MODULE_COLORS, UI_DIM, board_tile, draw_enclosure, font

MIME = "application/x-pedalfx-type"
GAP = 26          # visible space between pedal bodies
MARGIN = 96       # room at each end for the in/out cables
MAX_PEDALS = 12


class BoardView(QWidget):
    chain_changed = pyqtSignal()   # pedals added / removed / reordered
    selection_changed = pyqtSignal()
    edited = pyqtSignal()          # anything at all changed

    def __init__(self, sample_rate_getter, parent=None):
        super().__init__(parent)
        self._sr = sample_rate_getter
        self.skin = "walnut"
        self.widgets: list = []
        self._anims: dict = {}
        self._drag = None          # (widget, grab offset, started?)
        self._insert_at = None     # browser drop indicator index
        self.selected = None       # the pedal the keyboard / footswitches act on
        self.setAcceptDrops(True)
        self.setMinimumHeight(BODY_H + PAD_TOP + PAD_BOTTOM + 44)
        self.chain_changed.connect(self.edited)

    # -- model --------------------------------------------------------
    def pedals(self) -> list:
        return [w.pedal for w in self.widgets]

    def set_pedals(self, pedals) -> None:
        self.shutdown()
        for w in self.widgets:
            w.setParent(None)
            w.deleteLater()
        self.widgets = []
        self.selected = None
        for pedal in pedals:
            self._attach(pedal, len(self.widgets))
        self.relayout(animate=False)
        self.chain_changed.emit()
        # start on the looper if there is one, so Space keeps meaning "loop"
        self.select(next((w for w in self.widgets if w.pedal.TYPE == "looper"),
                         self.widgets[0] if self.widgets else None))

    # -- selection ------------------------------------------------------
    def select(self, widget) -> None:
        if widget is self.selected:
            return
        if self.selected is not None and self.selected in self.widgets:
            self.selected.set_selected(False)
        self.selected = widget
        if widget is not None:
            widget.set_selected(True)
        self.update()
        self.selection_changed.emit()

    def select_step(self, step: int) -> None:
        """Move the selection left / right along the chain, wrapping at the ends."""
        if not self.widgets:
            return
        if self.selected in self.widgets:
            index = (self.widgets.index(self.selected) + step) % len(self.widgets)
        else:
            index = 0
        self.select(self.widgets[index])

    def shutdown(self) -> None:
        for w in self.widgets:
            w.shutdown()

    def set_skin(self, skin: str) -> None:
        self.skin = skin
        self.update()
        self.edited.emit()

    def _attach(self, pedal, index: int):
        widget = make_pedal_widget(pedal, self)
        widget.edited.connect(self.edited)
        self.widgets.insert(index, widget)
        widget.show()
        return widget

    def add_pedal(self, type_name: str, index: int | None = None, data: dict | None = None):
        if len(self.widgets) >= MAX_PEDALS:
            return None
        index = len(self.widgets) if index is None else max(0, min(index, len(self.widgets)))
        pedal = pedal_from_dict(data, self._sr()) if data else create_pedal(type_name, self._sr())
        widget = self._attach(pedal, index)
        if self.selected is None:
            self.select(widget)
        slots = self._slots()
        widget.move(slots[index].x(), slots[index].y() - 46)  # drops in from above
        self.relayout()
        self.chain_changed.emit()
        return widget

    def remove(self, widget) -> None:
        if widget in self.widgets:
            index = self.widgets.index(widget)
            self.widgets.remove(widget)
            if widget is self.selected:   # hand the selection to a neighbour
                self.selected = None
                self.select(self.widgets[min(index, len(self.widgets) - 1)] if self.widgets else None)
            self._anims.pop(widget, None)
            widget.shutdown()
            widget.setParent(None)
            widget.deleteLater()
            self.relayout()
            self.chain_changed.emit()

    # -- layout -------------------------------------------------------
    def _content_width(self) -> int:
        return sum(w.width() - 2 * PAD_X for w in self.widgets) + GAP * max(0, len(self.widgets) - 1)

    def _slots(self) -> list:
        """Top-left target position for each pedal widget, in chain order."""
        x = max(MARGIN, (self.width() - self._content_width()) // 2) - PAD_X
        y = (self.height() - (BODY_H + PAD_TOP + PAD_BOTTOM)) // 2 + 4
        slots = []
        for w in self.widgets:
            slots.append(QPoint(x, y))
            x += w.width() - 2 * PAD_X + GAP
        return slots

    def relayout(self, animate: bool = True, skip=None) -> None:
        self.setMinimumWidth(self._content_width() + 2 * MARGIN)
        for w, target in zip(self.widgets, self._slots()):
            if w is skip:
                continue
            running = self._anims.pop(w, None)
            if running:
                running.stop()
            if not animate or not self.isVisible():
                w.move(target)
                continue
            if w.pos() == target:
                continue
            anim = QPropertyAnimation(w, b"pos", self)
            anim.setDuration(170)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setEndValue(target)
            anim.finished.connect(lambda w=w, a=anim: self._anims.get(w) is a and self._anims.pop(w))
            self._anims[w] = anim
            anim.start()
        self.update()

    def resizeEvent(self, _):
        self.relayout(animate=False, skip=self._drag[0] if self._drag else None)

    def _index_for_x(self, center_x: float, ignore=None) -> int:
        """Chain index a pedal centred at ``center_x`` belongs at."""
        index = 0
        for w, slot in zip(self.widgets, self._slots()):
            if w is ignore:
                continue
            if center_x > slot.x() + w.width() / 2.0:
                index += 1
        return index

    # -- drag to reorder (driven by PedalWidget mouse events) --------
    def begin_drag(self, widget, global_pos: QPointF) -> None:
        self._drag = [widget, widget.mapFromGlobal(global_pos.toPoint()), False]
        self.select(widget)

    def drag_to(self, widget, global_pos: QPointF) -> None:
        if not self._drag or self._drag[0] is not widget:
            return
        _, offset, started = self._drag
        pos = self.mapFromGlobal(global_pos.toPoint()) - offset
        if not started:
            if (pos - widget.pos()).manhattanLength() < 7:
                return
            self._drag[2] = True
            old = self._anims.pop(widget, None)
            if old:
                old.stop()
            widget.lifted = True
            widget.raise_()
            widget.setCursor(Qt.CursorShape.ClosedHandCursor)
        widget.move(pos)
        off_board = (pos.y() + widget.height() * 0.5 < -30
                     or pos.y() + widget.height() * 0.5 > self.height() + 30)
        self._set_ghost(widget, off_board)
        new_index = self._index_for_x(pos.x() + widget.width() / 2.0, ignore=widget)
        if new_index != self.widgets.index(widget):
            self.widgets.remove(widget)
            self.widgets.insert(new_index, widget)
            self.relayout(skip=widget)
            self.chain_changed.emit()
        self.update()

    def end_drag(self, widget) -> None:
        if not self._drag or self._drag[0] is not widget:
            return
        started = self._drag[2]
        self._drag = None
        if not started:
            return
        widget.lifted = False
        widget.setCursor(Qt.CursorShape.OpenHandCursor)
        if widget.graphicsEffect() is not None:  # released off the board: remove it
            self.remove(widget)
            return
        widget.update()
        self.relayout()

    def _set_ghost(self, widget, ghost: bool) -> None:
        if ghost and widget.graphicsEffect() is None:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.35)
            widget.setGraphicsEffect(effect)
        elif not ghost and widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)

    # -- context menu -------------------------------------------------
    def pedal_menu(self, widget, global_pos) -> None:
        pedal = widget.pedal
        menu = QMenu(self)
        bypass = menu.addAction("Turn Off" if pedal.enabled else "Turn On")
        duplicate = menu.addAction("Duplicate")
        reset = menu.addAction("Reset Knobs")
        finish_menu = menu.addMenu("Finish")
        finish_actions = {}
        for name in FINISHES:
            action = finish_menu.addAction(name.title())
            action.setCheckable(True)
            action.setChecked(name == (pedal.finish or pedal.FINISH))
            finish_actions[action] = name
        menu.addSeparator()
        remove = menu.addAction("Remove from Board")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is bypass:
            widget.toggle()
        elif chosen is duplicate:
            self.add_pedal(pedal.TYPE, self.widgets.index(widget) + 1, pedal.to_dict())
        elif chosen is reset:
            for param in pedal.PARAMS:
                pedal.set(param.key, param.default)
            widget.refresh()
            self.edited.emit()
        elif chosen is remove:
            self.remove(widget)
        elif chosen in finish_actions:
            pedal.finish = finish_actions[chosen]
            widget.rebuild()
            self.edited.emit()

    # -- drops from the browser --------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME) and len(self.widgets) < MAX_PEDALS:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        self._insert_at = self._index_for_x(e.position().x())
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, _):
        self._insert_at = None
        self.update()

    def dropEvent(self, e):
        type_name = bytes(e.mimeData().data(MIME)).decode()
        index = self._index_for_x(e.position().x())
        self._insert_at = None
        self.add_pedal(type_name, index)
        e.acceptProposedAction()

    # -- painting -----------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.drawTiledPixmap(self.rect(), board_tile(self.skin, self.height()))
        # stage lighting: brighter centre band, darker floor edges
        light = QLinearGradient(0, 0, 0, self.height())
        light.setColorAt(0.0, QColor(0, 0, 0, 130))
        light.setColorAt(0.2, QColor(0, 0, 0, 10))
        light.setColorAt(0.8, QColor(0, 0, 0, 30))
        light.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.fillRect(self.rect(), light)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        sel = self.selected
        if sel is not None and sel in self.widgets:
            # quiet marker: a hairline outline and a small lamp on the floor below the pedal
            ring = QRectF(sel.x() + PAD_X, sel.y() + PAD_TOP, sel.width() - 2 * PAD_X, BODY_H)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 120), 1.2))
            p.drawRoundedRect(ring.adjusted(-4, -4, 4, 4), 17, 17)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawRoundedRect(QRectF(ring.center().x() - 14, ring.bottom() + 12, 28, 3), 1.5, 1.5)

        if not self.widgets:
            p.setPen(QColor(255, 255, 255, 150))
            p.setFont(font(20, bold=True, family="logo", spacing=2.0))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "DRAG A PEDAL HERE FROM THE SHELF BELOW")
        else:
            self._paint_cables(p)

        if self._insert_at is not None:
            slots = self._slots()
            if not slots:
                x = self.width() / 2.0
            elif self._insert_at < len(slots):
                x = slots[self._insert_at].x() + PAD_X - GAP / 2.0
            else:
                x = slots[-1].x() + self.widgets[-1].width() - PAD_X + GAP / 2.0
            y = (self.height() - BODY_H) / 2.0
            glow = QColor("#ffb224")
            for width, alpha in ((14, 40), (8, 80), (3, 255)):
                glow.setAlpha(alpha)
                p.setPen(QPen(glow, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(x, y + 10), QPointF(x, y + BODY_H - 10))

    def _paint_cables(self, p: QPainter) -> None:
        def jack(x: float, y: float) -> None:
            g = QLinearGradient(x - 5, y - 9, x - 5, y + 9)
            g.setColorAt(0.0, QColor("#e8e8e8"))
            g.setColorAt(0.5, QColor("#8d9196"))
            g.setColorAt(1.0, QColor("#4b4f54"))
            p.setPen(QPen(QColor(20, 20, 22), 1))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x - 6, y - 9, 12, 18), 2.5, 2.5)

        def cable(a: QPointF, b: QPointF, sag: float) -> None:
            path = QPainterPath(a)
            path.cubicTo(a + QPointF((b.x() - a.x()) * 0.25, sag),
                         b - QPointF((b.x() - a.x()) * 0.25, -sag), b)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 90), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path.translated(0, 4))
            p.setPen(QPen(QColor("#0c0c0d"), 6.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(255, 255, 255, 46), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path.translated(0, -1.6))

        ends = []
        for w in self.widgets:
            y = w.y() + w.jack_y()
            ends.append((QPointF(w.x() + PAD_X - 3, y), QPointF(w.x() + w.width() - PAD_X + 3, y)))
        first_in, last_out = ends[0][0], ends[-1][1]
        cable(QPointF(-10, first_in.y() + 60), first_in, 46)
        cable(last_out, QPointF(self.width() + 10, last_out.y() + 60), 46)
        for (_, out), (inp, _) in zip(ends, ends[1:]):
            cable(out, inp, 30)
        for inp, out in ends:
            jack(inp.x(), inp.y())
            jack(out.x(), out.y())
        p.setPen(QColor(255, 255, 255, 120))
        p.setFont(font(10, bold=True, spacing=1.6))
        p.drawText(QRectF(10, first_in.y() + 78, 90, 16), Qt.AlignmentFlag.AlignLeft, "GUITAR IN")
        p.drawText(QRectF(self.width() - 100, last_out.y() + 78, 90, 16),
                   Qt.AlignmentFlag.AlignRight, "AMP OUT")


# ---------------------------------------------------------------------------
def paint_mini_pedal(p: QPainter, rect: QRectF, cls) -> None:
    """Thumbnail of a pedal for the browser shelf and drag pixmaps."""
    fin = FINISHES[cls.FINISH]
    draw_enclosure(p, rect, QColor(fin["body"]), radius=6, screws=False)
    p.setPen(Qt.PenStyle.NoPen)
    knob = QColor("#1a1a1a") if fin["knob"] == "black" else QColor("#f1efe6")
    if cls.TYPE in ("looper", "tuner"):
        screen = QRectF(rect.left() + 7, rect.top() + 8, rect.width() - 14,
                        24 if cls.TYPE == "looper" else 30)
        p.setBrush(QColor("#0b1013"))
        p.drawRoundedRect(screen, 3, 3)
        p.setBrush(QColor("#39e58c"))
        if cls.TYPE == "looper":
            p.drawRoundedRect(QRectF(screen.left() + 5, screen.bottom() - 7, screen.width() * 0.55, 3), 1, 1)
            p.setBrush(QColor("#c9ccd0"))
            p.setPen(QPen(QColor(40, 40, 44), 1))
            p.drawEllipse(QPointF(rect.left() + rect.width() * 0.3, rect.bottom() - 13), 6, 6)
            p.drawEllipse(QPointF(rect.left() + rect.width() * 0.7, rect.bottom() - 13), 6, 6)
            return
        p.drawRoundedRect(QRectF(screen.center().x() - 1.5, screen.top() + 6, 3, screen.height() - 12), 1, 1)
    elif cls.TYPE == "console":
        for i, color in enumerate(MODULE_COLORS):
            x = rect.left() + rect.width() * (i + 0.5) / 4.0
            p.setBrush(knob)
            p.drawEllipse(QPointF(x, rect.top() + 13), 4.2, 4.2)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x - 9, rect.top() + 24, 18, 26), 3, 3)
    else:
        count = sum(1 for prm in cls.PARAMS if not prm.is_choice)
        spots = [(0.3, 14), (0.7, 14), (0.3, 32), (0.7, 32)] if count == 4 else \
            [(0.3, 14), (0.7, 14), (0.5, 30)] if count == 3 else [(0.3, 20), (0.7, 20)]
        p.setBrush(knob)
        for fx, dy in spots:
            p.drawEllipse(QPointF(rect.left() + rect.width() * fx, rect.top() + dy), 5.4, 5.4)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(QRectF(rect.left() + 6, rect.top() + 44, rect.width() - 12, 9), 2, 2)
    p.setBrush(QColor("#c9ccd0"))
    p.setPen(QPen(QColor(40, 40, 44), 1))
    p.drawEllipse(QPointF(rect.center().x(), rect.bottom() - 13), 6, 6)


class PedalTile(QWidget):
    def __init__(self, cls, board: BoardView, parent=None):
        super().__init__(parent)
        self.cls = cls
        self.board = board
        self._press = None
        self._hover = False
        self.pedal_w = 112 if cls.TYPE in ("console", "looper") else 58
        self.setFixedSize(self.pedal_w + 34, 116)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"{cls.NAME} - {cls.TAGLINE}\nDrag onto the board, or double-click to add")

    def _pedal_rect(self) -> QRectF:
        return QRectF((self.width() - self.pedal_w) / 2.0, 6, self.pedal_w, 80)

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        pm = QPixmap(int(self.pedal_w * 2 + 16), 176)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2.0, 2.0)
        paint_mini_pedal(painter, QRectF(4, 2, self.pedal_w, 80), self.cls)
        painter.end()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, self.cls.TYPE.encode())
        drag.setMimeData(mime)
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseDoubleClickEvent(self, _):
        self.board.add_pedal(self.cls.TYPE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 1, -2, -1), 8, 8)
        paint_mini_pedal(p, self._pedal_rect(), self.cls)
        p.setPen(QColor("#e6e9ed") if self._hover else QColor(UI_DIM))
        p.setFont(font(11, bold=True, spacing=0.5))
        p.drawText(QRectF(0, 94, self.width(), 16), Qt.AlignmentFlag.AlignCenter,
                   self.cls.NAME.upper())


class PedalBrowser(QWidget):
    """The shelf of available pedals along the bottom of the window."""

    def __init__(self, board: BoardView, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 4, 18, 4)
        row.setSpacing(2)
        row.addStretch(1)
        for cls in PEDAL_CLASSES:
            row.addWidget(PedalTile(cls, board, self))
        row.addStretch(1)

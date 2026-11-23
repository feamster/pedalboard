"""Main window: transport bar, the board and the pedal shelf."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..engine import BLOCK_SIZES, SAMPLE_RATES, AudioConfig, AudioEngine, list_devices
from ..presets import PresetStore, board_to_dict, pedals_from_board, with_tuner_first
from .board_view import BoardView, PedalBrowser
from .pedal_widget import LooperWidget
from .theme import BOARD_SKINS, UI_ACCENT, UI_BG, UI_DIM, UI_PANEL, UI_TEXT
from .widgets import Knob, LevelMeter, PowerButton

SOURCE_LABELS = (("demo", "Demo Riff"), ("live", "Live Input"), ("file", "Audio File…"))

STYLE = f"""
QMainWindow, QDialog {{ background: {UI_BG}; }}
QWidget#bar, QWidget#shelf {{ background: {UI_PANEL}; }}
QLabel {{ color: {UI_TEXT}; font-size: 12px; }}
QLabel#logo {{ color: #ffffff; font-family: Futura, 'Avenir Next'; font-size: 19px;
               font-weight: bold; letter-spacing: 3px; }}
QLabel#dim, QLabel#status {{ color: {UI_DIM}; font-size: 11px; }}
QLabel#caption {{ color: {UI_DIM}; font-size: 10px; font-weight: bold; letter-spacing: 1px; }}
QLabel#edited {{ color: {UI_ACCENT}; font-size: 11px; font-weight: bold; }}
QComboBox, QPushButton, QSpinBox {{
    color: {UI_TEXT}; background: #2a2e33; border: 1px solid #3a3f46;
    border-radius: 6px; padding: 5px 10px; font-size: 12px; min-height: 18px; }}
QComboBox:hover, QPushButton:hover {{ border-color: #5a626c; background: #30353b; }}
QPushButton:pressed {{ background: #24282c; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ color: {UI_TEXT}; background: #24272b;
    selection-background-color: #3d444c; border: 1px solid #3a3f46; }}
QMenu {{ color: {UI_TEXT}; background: #24272b; border: 1px solid #3a3f46; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: #3d444c; }}
QScrollArea {{ border: none; background: #0c0d0e; }}
QScrollBar:horizontal {{ background: #101113; height: 11px; }}
QScrollBar::handle:horizontal {{ background: #3a3f46; border-radius: 5px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ color: {UI_TEXT}; background: #24272b; border: 1px solid #3a3f46; }}
"""


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("caption")
    return label


class SettingsDialog(QDialog):
    def __init__(self, config: AudioConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio Settings")
        self.setMinimumWidth(420)
        ins, outs = list_devices()
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(12)

        def device_combo(devices, current):
            combo = QComboBox()
            default = next((d["name"] for d in devices if d["default"]), "none")
            combo.addItem(f"System Default ({default})", None)
            for dev in devices:
                combo.addItem(f"{dev['name']}  ({dev['channels']} ch)", dev["name"])
            combo.setCurrentIndex(max(0, combo.findData(current)))
            return combo

        self.input = device_combo(ins, config.input_device)
        self.output = device_combo(outs, config.output_device)
        self.channel = QSpinBox()
        self.channel.setRange(1, 64)
        self.channel.setValue(config.input_channel)
        self.rate = QComboBox()
        self.rate.addItem("Match device (lowest latency)", 0)
        for sr in SAMPLE_RATES:
            self.rate.addItem(f"{sr / 1000:g} kHz", sr)
        self.rate.setCurrentIndex(self.rate.findData(config.sample_rate))
        self.block = QComboBox()
        for size in BLOCK_SIZES:
            self.block.addItem(f"{size} samples", size)
        self.block.setCurrentIndex(self.block.findData(config.block_size))
        form.addRow("Input device", self.input)
        form.addRow("Guitar is on input", self.channel)
        form.addRow("Output device", self.output)
        form.addRow("Sample rate", self.rate)
        form.addRow("Buffer size", self.block)
        note = QLabel("Smaller buffers mean less latency but more CPU. "
                      "Use headphones with Live Input to avoid feedback.")
        note.setObjectName("dim")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_config(self) -> AudioConfig:
        return AudioConfig(self.input.currentData(), self.output.currentData(),
                           self.channel.value(), self.rate.currentData(),
                           self.block.currentData())


def default_config() -> AudioConfig:
    """First-run guess: a Scarlett interface with the guitar on input 2.

    Output stays on the system default so the first press of the power button
    is audible wherever the computer's sound already goes.
    """
    ins, _ = list_devices()
    cfg = AudioConfig()
    scarlett = next((d for d in ins if d["name"].startswith("Scarlett")), None)
    if scarlett:
        cfg.input_device = scarlett["name"]
        cfg.input_channel = 2 if scarlett["channels"] >= 2 else 1
    return cfg


class MainWindow(QMainWindow):
    def __init__(self, store: PresetStore | None = None):
        super().__init__()
        self.store = store or PresetStore()
        self.engine = AudioEngine()
        self.preset_name = "Welcome Board"
        self._loading = False
        self.setWindowTitle("Pedalboard")
        self.setStyleSheet(STYLE)
        self.resize(1440, 720)

        self.board = BoardView(lambda: self.engine.sr)
        self.board.chain_changed.connect(lambda: self.engine.set_chain(self.board.pedals()))
        self.board.edited.connect(self._mark_edited)

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_bar())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.board)
        column.addWidget(self.scroll, 1)
        column.addWidget(self._build_shelf())
        self.setCentralWidget(central)

        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save)
        self._space_down = False
        self._hold = QTimer(self)          # Space held down -> looper undo/redo
        self._hold.setSingleShot(True)
        self._hold.setInterval(900)
        self._hold.timeout.connect(self._space_held)
        QApplication.instance().installEventFilter(self)

        self._restore_session()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # -- construction -------------------------------------------------
    def _build_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("bar")
        bar.setFixedHeight(84)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 6, 18, 6)
        row.setSpacing(12)

        logo = QLabel("PEDALBOARD")
        logo.setObjectName("logo")
        row.addWidget(logo)
        row.addSpacing(10)

        self.power = PowerButton()
        self.power.toggled.connect(self._power)
        row.addWidget(self.power)
        self.power_label = QLabel("OFF")
        self.power_label.setObjectName("caption")
        self.power_label.setFixedWidth(34)
        row.addWidget(self.power_label)

        source_box = QVBoxLayout()
        source_box.setSpacing(3)
        source_box.addWidget(_caption("INPUT SOURCE"))
        self.source = QComboBox()
        for key, label in SOURCE_LABELS:
            self.source.addItem(label, key)
        self.source.activated.connect(self._source_chosen)
        self.source.setFixedWidth(170)
        source_box.addWidget(self.source)
        row.addLayout(source_box)
        row.addStretch(1)

        preset_box = QVBoxLayout()
        preset_box.setSpacing(3)
        head = QHBoxLayout()
        head.addWidget(_caption("BOARD PRESET"))
        self.edited_label = QLabel("")
        self.edited_label.setObjectName("edited")
        head.addWidget(self.edited_label)
        head.addStretch(1)
        preset_box.addLayout(head)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.presets = QComboBox()
        self.presets.setFixedWidth(210)
        self.presets.activated.connect(lambda _: self._load_preset(self.presets.currentData()))
        line.addWidget(self.presets)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        line.addWidget(save)
        more = QPushButton("⋯")
        more.setFixedWidth(38)
        menu = QMenu(more)
        menu.addAction("Save As…", self._save_as)
        menu.addAction("Revert to Saved", lambda: self._load_preset(self.preset_name))
        menu.addAction("Clear Board", lambda: self.board.set_pedals([]))
        menu.addSeparator()
        menu.addAction("Delete Preset", self._delete_preset)
        more.setMenu(menu)
        line.addWidget(more)
        preset_box.addLayout(line)
        row.addLayout(preset_box)

        skin_box = QVBoxLayout()
        skin_box.setSpacing(3)
        skin_box.addWidget(_caption("BOARD SKIN"))
        self.skins = QComboBox()
        for skin in BOARD_SKINS:
            self.skins.addItem(skin.title(), skin)
        self.skins.activated.connect(lambda _: self.board.set_skin(self.skins.currentData()))
        skin_box.addWidget(self.skins)
        row.addLayout(skin_box)
        row.addStretch(1)

        def gain_knob(label, lo, hi, setter):
            knob = Knob(label, default=(0 - lo) / (hi - lo), norm=(0 - lo) / (hi - lo),
                        style="silver", text_color=UI_TEXT, diameter=36,
                        formatter=lambda t: f"{lo + (hi - lo) * t:+.1f} dB")
            knob.changed.connect(lambda t: setter(lo + (hi - lo) * t))
            return knob

        self.in_knob = gain_knob("Input", -24.0, 24.0, lambda v: setattr(self.engine, "input_gain_db", v))
        self.out_knob = gain_knob("Master", -36.0, 12.0, lambda v: setattr(self.engine, "master_db", v))
        self.in_meter, self.out_meter = LevelMeter(), LevelMeter()
        meters = QVBoxLayout()
        meters.setSpacing(4)
        for text, meter in (("IN", self.in_meter), ("OUT", self.out_meter)):
            line = QHBoxLayout()
            label = _caption(text)
            label.setFixedWidth(26)
            line.addWidget(label)
            line.addWidget(meter)
            meters.addLayout(line)
        self.status = QLabel("Engine off")
        self.status.setObjectName("status")
        self.status.setFixedWidth(200)
        meters.addWidget(self.status)
        row.addWidget(self.in_knob)
        row.addLayout(meters)
        row.addWidget(self.out_knob)

        settings = QPushButton("Audio…")
        settings.clicked.connect(self._open_settings)
        row.addWidget(settings)
        return bar

    def _build_shelf(self) -> QWidget:
        shelf = QWidget()
        shelf.setObjectName("shelf")
        column = QVBoxLayout(shelf)
        column.setContentsMargins(0, 6, 0, 2)
        column.setSpacing(0)
        hint = _caption("PEDAL SHELF  ·  DRAG ONTO THE BOARD OR DOUBLE-CLICK  ·  DRAG A PEDAL OFF THE BOARD "
                        "(OR RIGHT-CLICK) TO REMOVE")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(hint)
        column.addWidget(PedalBrowser(self.board))
        line = QFrame()
        line.setFixedHeight(0)
        column.addWidget(line)
        return shelf

    # -- keyboard -----------------------------------------------------
    LOOPER_KEYS = {Qt.Key.Key_S: "stop", Qt.Key.Key_U: "undo", Qt.Key.Key_T: "track",
                   Qt.Key.Key_R: "drums", Qt.Key.Key_F: "fill", Qt.Key.Key_N: "next",
                   Qt.Key.Key_Backspace: "clear", Qt.Key.Key_Delete: "clear",
                   Qt.Key.Key_Escape: "stopall"}

    def looper(self) -> LooperWidget | None:
        """The looper the keyboard controls: the first one on the board."""
        return next((w for w in self.board.widgets if isinstance(w, LooperWidget)), None)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self._keys_are_ours(event):
            if self.handle_key(event.key(), kind == QEvent.Type.KeyPress, event.isAutoRepeat()):
                return True
        return super().eventFilter(obj, event)

    def _keys_are_ours(self, event) -> bool:
        if not self.isActiveWindow() or QApplication.activePopupWidget() is not None:
            return False
        if isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox)):
            return False
        blocked = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
                   | Qt.KeyboardModifier.AltModifier)
        return not (event.modifiers() & blocked)

    def handle_key(self, key, down: bool, repeat: bool = False) -> bool:
        """Space is the looper's main switch (or engine power); letters are its other controls."""
        looper = self.looper()
        if key == Qt.Key.Key_Space:
            if repeat:
                return True
            self._space_down = down
            if not down:
                self._hold.stop()
            elif not self.engine.running:
                self._power(True)
            elif looper is None:
                self._power(False)
            else:
                looper.send("press")
                self._hold.start()
            return True
        if looper is None or not down:
            return False
        if key in self.LOOPER_KEYS:
            if not repeat:
                looper.send(self.LOOPER_KEYS[key])
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            looper.nudge_tempo(1 if key == Qt.Key.Key_Up else -1)
            return True
        return False

    def _space_held(self) -> None:
        looper = self.looper()
        if self._space_down and looper is not None:
            looper.send("hold")

    # -- presets ------------------------------------------------------
    def _refresh_presets(self) -> None:
        self.presets.clear()
        for name in self.store.user_names():
            self.presets.addItem(name, name)
        if self.presets.count():
            self.presets.insertSeparator(self.presets.count())
        user = set(self.store.user_names())
        for name in self.store.factory_names():
            if name not in user:
                self.presets.addItem(f"{name}  (factory)", name)
        index = self.presets.findData(self.preset_name)
        self.presets.setCurrentIndex(index)

    def _apply_board(self, data: dict) -> None:
        self._loading = True
        skin = data.get("skin", "walnut")
        self.board.skin = skin if skin in BOARD_SKINS else "walnut"
        self.skins.setCurrentIndex(self.skins.findData(self.board.skin))
        self.board.set_pedals(pedals_from_board(data, self.engine.sr))
        self._loading = False

    def _load_preset(self, name: str | None) -> None:
        if not name:
            return
        try:
            data = self.store.load(name)
        except KeyError:
            return
        self.preset_name = name
        self._apply_board(data)
        self._refresh_presets()
        self.edited_label.setText("")

    def _mark_edited(self) -> None:
        if not self._loading:
            self.edited_label.setText("● edited")

    def _current_board(self, name: str) -> dict:
        return board_to_dict(name, self.board.pedals(), self.board.skin)

    def _save(self) -> None:
        if not self.store.is_user(self.preset_name):
            return self._save_as()  # factory boards are never overwritten
        self.store.save(self._current_board(self.preset_name))
        self.edited_label.setText("")

    def _save_as(self) -> None:
        suggestion = self.preset_name if self.store.is_user(self.preset_name) \
            else f"My {self.preset_name}"
        name, ok = QInputDialog.getText(self, "Save Board", "Preset name:", text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        self.store.save(self._current_board(name))
        self.preset_name = name
        self._refresh_presets()
        self.edited_label.setText("")

    def _delete_preset(self) -> None:
        name = self.preset_name
        if not self.store.is_user(name):
            QMessageBox.information(self, "Delete Preset", "Factory presets can't be deleted.")
            return
        if QMessageBox.question(self, "Delete Preset", f"Delete “{name}”?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        self._load_preset(self.store.factory_names()[0])

    # -- audio --------------------------------------------------------
    def _power(self, on: bool) -> None:
        if on:
            try:
                self.engine.start()
            except Exception as exc:
                self.engine.stop()
                QMessageBox.warning(self, "Audio", f"Couldn't start audio:\n\n{exc}\n\n"
                                    "Check the devices under Audio… and try again.")
        else:
            self.engine.stop()
        running = self.engine.running
        self.power.set_on(running)
        self.power_label.setText("ON" if running else "OFF")

    def _restart_if_running(self) -> None:
        if self.engine.running:
            self._power(True)

    def _source_chosen(self, _index: int) -> None:
        key = self.source.currentData()
        if key == "file":
            start = str(Path(self.engine.file_path).parent) if self.engine.file_path else str(Path.home())
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose an audio file to play through the board", start,
                "Audio (*.wav *.aif *.aiff *.flac *.mp3 *.ogg *.m4a);;All files (*)")
            if not path:
                self.source.setCurrentIndex(self.source.findData(self.engine.source))
                return
            self.engine.file_path = path
        self.engine.source = key
        self._update_source_tip()
        self._restart_if_running()

    def _update_source_tip(self) -> None:
        tip = {"demo": "A built-in looping clean guitar riff - no guitar required.",
               "live": "Your audio interface input (set the device under Audio…).",
               "file": f"Looping {Path(self.engine.file_path).name}" if self.engine.file_path else ""}
        self.source.setToolTip(tip[self.engine.source])

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.engine.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.engine.config = dialog.result_config()
            self._restart_if_running()

    def _tick(self) -> None:
        engine = self.engine
        in_peak, out_peak = engine.in_peak, engine.out_peak
        engine.in_peak = engine.out_peak = 0.0
        self.in_meter.feed(in_peak)
        self.out_meter.feed(out_peak)
        if engine.last_error:
            self.status.setText(f"DSP error: {engine.last_error}"[:60])
        elif engine.running:
            cfg = engine.config
            self.status.setText(f"{engine.sr / 1000:g} kHz · {cfg.block_size} · "
                                f"{engine.latency_ms:.0f} ms · CPU {engine.cpu_load * 100:.0f}%")
        else:
            self.status.setText("Engine off · press Space to start")

    # -- session ------------------------------------------------------
    def _restore_session(self) -> None:
        session = self.store.load_session()
        self.engine.config = AudioConfig.from_dict(session["audio"]) if "audio" in session \
            else default_config()
        if self.engine.config.sample_rate:
            self.engine.set_sample_rate(self.engine.config.sample_rate)
        source = session.get("source", "demo")
        path = session.get("file_path")
        if source == "file" and not (path and Path(path).exists()):
            source = "demo"
        self.engine.source, self.engine.file_path = source, path
        self.source.setCurrentIndex(self.source.findData(source))
        self._update_source_tip()
        for knob, key, lo, hi, attr in ((self.in_knob, "input_gain_db", -24.0, 24.0, "input_gain_db"),
                                        (self.out_knob, "master_db", -36.0, 12.0, "master_db")):
            value = min(hi, max(lo, float(session.get(key, 0.0))))
            setattr(self.engine, attr, value)
            knob.set_norm((value - lo) / (hi - lo))
        board = session.get("board")
        self.preset_name = session.get("preset", self.preset_name)
        if board and session.get("version", "2.0.0") < "2.1.0":
            board = with_tuner_first(board)   # 2.1 put a tuner at the front of every board
        if board:
            self._apply_board(board)
            self._refresh_presets()
            self.edited_label.setText("● edited" if session.get("edited") else "")
        else:
            self._load_preset(self.store.factory_names()[0])

    def save_session(self) -> None:
        self.store.save_session({
            "version": __version__,
            "audio": self.engine.config.to_dict(),
            "source": self.engine.source,
            "file_path": self.engine.file_path,
            "input_gain_db": self.engine.input_gain_db,
            "master_db": self.engine.master_db,
            "preset": self.preset_name,
            "edited": bool(self.edited_label.text()),
            "board": self._current_board(self.preset_name),
        })

    def closeEvent(self, event):
        self._timer.stop()
        self._hold.stop()
        QApplication.instance().removeEventFilter(self)
        self.board.shutdown()
        self.engine.stop()
        try:
            self.save_session()
        except OSError:
            pass
        super().closeEvent(event)

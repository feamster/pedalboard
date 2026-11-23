"""UI behaviour, driven through the same entry points the mouse uses."""

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pedalfx.presets import PresetStore
from pedalfx.ui.main_window import MainWindow
from pedalfx.ui.pedal_widget import ConsoleWidget
from pedalfx.ui.widgets import Knob


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow(PresetStore(tmp_path))
    win.resize(1500, 720)
    win.show()
    app.processEvents()
    yield win
    win.close()


def types(win):
    return [p.TYPE for p in win.board.pedals()]


def drag(win, widget, dx, dy=0):
    """Press on the pedal's name plate and drag it by (dx, dy)."""
    start = QPointF(widget.mapToGlobal(QPoint(widget.width() // 2, 290)))
    win.board.begin_drag(widget, start)
    for step in range(1, 11):
        win.board.drag_to(widget, start + QPointF(dx * step / 10, dy * step / 10))
    win.board.end_drag(widget)
    QApplication.processEvents()


def test_starts_on_the_welcome_board(window):
    assert window.preset_name == "Welcome Board"
    assert types(window) == ["tuner", "compressor", "distortion", "chorus", "delay", "reverb"]
    assert window.engine.chain == tuple(window.board.pedals())
    assert not window.engine.running


def test_dragging_a_pedal_reorders_the_signal_chain(window):
    first = window.board.widgets[0]
    drag(window, first, 2 * first.width() + 40)
    assert types(window) == ["compressor", "distortion", "tuner", "chorus", "delay", "reverb"]
    assert [p.TYPE for p in window.engine.chain] == types(window)
    last = window.board.widgets[-1]
    drag(window, last, -3000)
    assert types(window)[0] == "reverb"
    assert window.edited_label.text()


def test_small_mouse_wobble_is_not_a_drag(window):
    before = types(window)
    drag(window, window.board.widgets[1], 3)
    assert types(window) == before


def test_dragging_off_the_board_removes_the_pedal(window):
    victim = window.board.widgets[3]
    drag(window, victim, 0, 600)
    assert types(window) == ["tuner", "compressor", "distortion", "delay", "reverb"]
    assert len(window.engine.chain) == 5


def test_add_duplicate_and_limit(window):
    window.board.add_pedal("console", 0)
    assert types(window)[0] == "console"
    assert isinstance(window.board.widgets[0], ConsoleWidget)
    source = window.board.widgets[2]
    source.pedal.set("sustain", 0.9)
    window.board.add_pedal(source.pedal.TYPE, 3, source.pedal.to_dict())
    assert window.board.pedals()[3].get("sustain") == 0.9
    assert window.board.pedals()[3] is not source.pedal
    for _ in range(20):
        window.board.add_pedal("tremolo")
    assert len(window.board.widgets) == 12


def test_knob_drag_sets_the_parameter(window, app):
    widget = window.board.widgets[4]  # delay
    knob = widget.controls["time"]
    assert isinstance(knob, Knob)
    center = QPoint(knob.width() // 2, 30)
    QTest.mousePress(knob, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(knob, center - QPoint(0, 400))
    QTest.mouseRelease(knob, Qt.MouseButton.LeftButton, pos=center - QPoint(0, 400))
    assert widget.pedal.get("time") == 1200.0
    QTest.mouseDClick(knob, Qt.MouseButton.LeftButton, pos=center)
    assert widget.pedal.get("time") == pytest.approx(380.0)
    assert types(window)[4] == "delay"  # turning a knob never drags the pedal


def test_footswitch_and_mode_switch(window):
    widget = window.board.widgets[2]  # distortion ships switched off
    assert widget.pedal.enabled is False
    QTest.mouseClick(widget.foot, Qt.MouseButton.LeftButton)
    assert widget.pedal.enabled is True
    switch = widget.controls["mode"]
    QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(switch.width() - 10, 10))
    assert widget.pedal.get("mode") == 2


def test_console_selectors_presets_and_module_swap(window, app):
    console = window.board.add_pedal("console", 0)
    pedal = console.pedal
    selector = console.controls["text_fx"]
    QTest.mouseClick(selector, Qt.MouseButton.LeftButton, pos=QPoint(30, 4 * selector.ROW + 5))
    assert pedal.get("text_fx") == 5 and pedal.preset_name == "Custom"
    QTest.mouseClick(selector, Qt.MouseButton.LeftButton, pos=QPoint(30, 4 * selector.ROW + 5))
    assert pedal.get("text_fx") == 0  # clicking the lit effect switches the module off

    _, _, next_rect = console._preset_rects()
    QTest.mouseClick(console, Qt.MouseButton.LeftButton, pos=next_rect.center().toPoint())
    assert pedal.preset_name == "Init"
    QTest.mouseClick(console, Qt.MouseButton.LeftButton, pos=next_rect.center().toPoint())
    assert pedal.preset_name == "Worn Tape" and pedal.get("text_fx") == 3
    assert selector.index == 3

    x_before = console.amounts[0].x()
    _, right_arrow = console._arrow_rects(0)
    QTest.mouseClick(console, Qt.MouseButton.LeftButton, pos=right_arrow.center().toPoint())
    assert pedal.order == [1, 0, 2, 3]
    assert console.amounts[0].x() > x_before
    assert window.board.widgets[0] is console  # arrows don't start a drag


def test_presets_save_load_and_session(window, tmp_path, app, monkeypatch):
    window._load_preset("Shoegaze Wash")
    assert types(window) == ["tuner", "distortion", "phaser", "chorus", "delay", "reverb"]
    assert window.board.skin == "stage" and not window.edited_label.text()

    window.board.widgets[1].pedal.set("drive", 0.11)
    window.board.set_skin("tolex")
    monkeypatch.setattr("pedalfx.ui.main_window.QInputDialog.getText",
                        lambda *a, **k: ("Mine", True))
    window._save()  # factory preset -> becomes Save As
    assert window.preset_name == "Mine" and window.store.is_user("Mine")
    assert "Welcome Board" in window.store.factory_names()

    window._load_preset("Welcome Board")
    window._load_preset("Mine")
    assert window.board.pedals()[1].get("drive") == 0.11 and window.board.skin == "tolex"

    window.engine.master_db = -9.0
    window.save_session()
    again = MainWindow(PresetStore(tmp_path))
    assert again.preset_name == "Mine"
    assert again.board.pedals()[1].get("drive") == 0.11
    assert again.engine.master_db == -9.0
    again.close()


def test_finish_change_rebuilds_controls(window, app):
    widget = window.board.widgets[1]
    widget.pedal.set("sustain", 0.8)
    widget.pedal.finish = "crimson"
    widget.rebuild()
    app.processEvents()
    assert widget.controls["sustain"].style == "cream"
    assert widget.controls["sustain"].norm == pytest.approx(0.8)


def test_dropping_a_shelf_pedal_inserts_it_where_released(window, app):
    from PyQt6.QtCore import QMimeData
    from PyQt6.QtGui import QDropEvent

    from pedalfx.ui.board_view import MIME

    board = window.board
    second = board.widgets[2]
    mime = QMimeData()
    mime.setData(MIME, b"phaser")
    # release just left of the distortion's centre -> lands just before it
    pos = QPointF(second.x() + second.width() / 2 - 20, board.height() / 2)
    board.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier))
    assert types(window) == ["tuner", "compressor", "phaser", "distortion", "chorus", "delay", "reverb"]
    board.dropEvent(QDropEvent(QPointF(board.width() - 5, 50), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert types(window)[-1] == "phaser"
    assert [p.TYPE for p in window.engine.chain] == types(window)


# -- tuner, looper and the keyboard -------------------------------------
class FakeStream:
    """Stands in for a running audio stream so no real device is opened."""
    latency = 0.01
    cpu_load = 0.0

    def stop(self):
        pass

    close = stop


def pump(window, blocks=4, level=0.0):
    import numpy as np
    for _ in range(blocks):
        window.engine.process_block(np.full((2, 256), level, dtype=np.float32))


def test_every_factory_board_starts_with_the_tuner(window):
    from pedalfx.ui.pedal_widget import TunerWidget

    for name in window.store.factory_names():
        window._load_preset(name)
        assert types(window)[0] == "tuner", name
        assert isinstance(window.board.widgets[0], TunerWidget)
    assert "Looper Rig" in window.store.factory_names()


def test_tuner_display_follows_the_engine(window, app):
    import numpy as np
    tuner = window.board.widgets[0]
    tuner.display.poll()
    assert tuner.display.reading is None             # engine has not produced audio
    t = np.arange(8192) / window.engine.sr
    wave = (0.2 * np.sin(2 * np.pi * 110.0 * t)).astype(np.float32)
    for s in range(0, 8192, 256):
        window.engine.process_block(np.stack([wave[s:s + 256]] * 2))
    tuner.display.poll()
    assert tuner.display.reading["note"] == "A" and tuner.display.reading["octave"] == 2
    tuner.grab()                                     # paints without error


def test_space_starts_the_engine_then_works_the_selected_pedal(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_power", lambda on: calls.append(on))
    tuner = window.board.widgets[0]
    assert window.looper() is None and window.board.selected is tuner
    assert window.handle_key(Qt.Key.Key_Space, True)
    assert calls == [True] and tuner.pedal.enabled        # engine was off: Space only starts it
    window.engine._stream = FakeStream()
    window.handle_key(Qt.Key.Key_Space, False)
    window.handle_key(Qt.Key.Key_Space, True)
    window.handle_key(Qt.Key.Key_Space, True, repeat=True)
    assert calls == [True] and not tuner.pedal.enabled    # now it is the pedal's footswitch
    assert not window.handle_key(Qt.Key.Key_S, True)      # looper letters do nothing without one
    window.engine._stream = None


def test_arrow_keys_walk_the_board_and_turn_knobs(window, app):
    board = window.board
    window.engine._stream = FakeStream()
    order = types(window)
    assert board.selected is board.widgets[0]
    window.handle_key(Qt.Key.Key_Left, True)                    # wraps to the far end
    assert board.selected is board.widgets[-1]
    window.handle_key(Qt.Key.Key_Right, True)
    window.handle_key(Qt.Key.Key_Right, True)
    window.handle_key(Qt.Key.Key_Right, True)
    dist = board.selected
    assert dist.pedal.TYPE == "distortion" and dist.selected and not board.widgets[0].selected
    assert dist.pedal.enabled is False
    window.handle_key(Qt.Key.Key_Space, True)                   # stomp it on
    window.handle_key(Qt.Key.Key_Space, False)
    assert dist.pedal.enabled is True

    drive, tone = dist.controls["drive"], dist.controls["tone"]
    assert drive.focused and not tone.focused
    before = dist.pedal.get("drive")
    for _ in range(5):
        window.handle_key(Qt.Key.Key_Up, True, repeat=True)     # holding the key keeps turning
    assert dist.pedal.get("drive") == pytest.approx(before + 0.10)
    window.handle_key(Qt.Key.Key_Tab, True)
    assert tone.focused and not drive.focused
    window.handle_key(Qt.Key.Key_Down, True)
    assert dist.pedal.get("tone") == pytest.approx(0.53)
    assert dist.pedal.get("drive") == pytest.approx(before + 0.10)
    window.handle_key(Qt.Key.Key_Backtab, True)
    assert drive.focused
    window.handle_key(Qt.Key.Key_Right, True)
    assert not drive.focused and types(window) == order         # selection never reorders
    board.grab()                                                # selection ring paints

    QTest.mousePress(dist, Qt.MouseButton.LeftButton, pos=QPoint(dist.width() // 2, 290))
    QTest.mouseRelease(dist, Qt.MouseButton.LeftButton, pos=QPoint(dist.width() // 2, 290))
    assert board.selected is dist                               # clicking a pedal selects it
    neighbour = board.widgets[board.widgets.index(dist) + 1]
    board.remove(dist)
    assert board.selected is neighbour and neighbour.selected
    window.engine._stream = None


def test_return_is_always_the_looper(window, app):
    window._load_preset("Looper Rig")
    looper = window.looper()
    assert window.board.selected is looper                      # boards with a looper start on it
    looper.pedal.set("start", 0)
    window.engine._stream = FakeStream()
    pump(window)
    window.handle_key(Qt.Key.Key_Left, True)                    # move to the reverb
    reverb = window.board.selected
    assert reverb.pedal.TYPE == "reverb"
    window.handle_key(Qt.Key.Key_Return, True)
    window.handle_key(Qt.Key.Key_Return, False)
    pump(window)
    assert looper.pedal.state == "rec" and reverb.pedal.enabled
    window.handle_key(Qt.Key.Key_Space, True)                   # Space still belongs to the reverb
    window.handle_key(Qt.Key.Key_Space, False)
    pump(window)
    assert not reverb.pedal.enabled and looper.pedal.state == "rec"
    window.handle_key(Qt.Key.Key_Escape, True)
    window.engine._stream = None


def test_keyboard_drives_the_looper(window, app):
    window._load_preset("Looper Rig")
    widget = window.looper()
    looper = widget.pedal
    for key, value in (("start", 0), ("measures", 1), ("after", 1), ("drums", 0)):
        looper.set(key, value)
    window.engine._stream = FakeStream()
    pump(window)

    def key(k, hold=False):
        looper.last_press = -10.0
        window.handle_key(k, True)
        if not hold:
            window.handle_key(k, False)
        pump(window)

    key(Qt.Key.Key_Space)
    assert looper.state == "rec"
    window.handle_key(Qt.Key.Key_Space, True, repeat=True)   # auto-repeat must not re-trigger
    pump(window, blocks=int(looper.measure // 256) + 2)
    assert looper.state == "play"
    key(Qt.Key.Key_Space)
    assert looper.state == "dub"
    key(Qt.Key.Key_Space)
    assert looper.state == "play" and looper.status()["can_undo"]
    key(Qt.Key.Key_U)
    assert looper.redo[0]
    key(Qt.Key.Key_T)
    assert looper.sel == 1
    key(Qt.Key.Key_R)
    assert looper.get("drums") == 1
    widget._refresh_display()
    key(Qt.Key.Key_S)
    assert looper.state == "play"                    # track 2 is selected and isn't playing
    key(Qt.Key.Key_Escape)
    assert looper.state == "stop"                    # Esc stops everything
    key(Qt.Key.Key_T)
    key(Qt.Key.Key_Backspace)
    assert looper.state == "empty"
    key(Qt.Key.Key_Up)
    assert looper.get("tempo") == 97 and widget.controls["tempo"].norm == pytest.approx(57 / 200)

    key(Qt.Key.Key_Space, hold=True)                 # holding Space asks for undo
    assert window._hold.isActive() and window._switch_down
    window._space_held()
    window.handle_key(Qt.Key.Key_Space, False)
    assert not window._hold.isActive()
    widget.grab()
    window.engine._stream = None


def test_looper_footswitches_and_fields(window, app):
    widget = window.board.add_pedal("looper")
    looper = widget.pedal
    looper.set("start", 0)
    pump(window)
    QTest.mousePress(widget.foot, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(widget.foot, Qt.MouseButton.LeftButton)
    pump(window)
    assert looper.state == "rec" and looper.enabled   # the big switch records, it never bypasses
    QTest.mousePress(widget.stop_foot, Qt.MouseButton.LeftButton)
    pump(window)
    assert looper.state == "empty"
    stop_mode = widget.controls["stop"]
    QTest.mouseClick(stop_mode, Qt.MouseButton.LeftButton, pos=QPoint(stop_mode.width() - 8, 25))
    assert looper.param("stop").format(looper.get("stop")) == "Loop End"
    field = widget.controls["style"]
    QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(field.width() - 8, 25))
    assert looper.get("style") == 1
    QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(8, 25))
    QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(8, 25))
    assert looper.style.name == "Metronome"          # wraps around backwards
    window.board.remove(widget)
    assert not widget._tick.isActive()


def test_old_sessions_gain_a_tuner_once(tmp_path, app):
    store = PresetStore(tmp_path)
    old_board = {"name": "Mine", "skin": "tolex", "pedals": [{"type": "reverb", "params": {}}]}
    store.save_session({"version": "2.0.0", "preset": "Mine", "board": old_board})
    upgraded = MainWindow(store)
    assert types(upgraded) == ["tuner", "reverb"]
    upgraded.board.remove(upgraded.board.widgets[0])  # the user takes it off again ...
    upgraded.save_session()
    upgraded.close()
    again = MainWindow(store)
    assert types(again) == ["reverb"]                 # ... and it stays off
    again.close()

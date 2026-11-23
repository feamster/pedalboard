import numpy as np
import pytest

from conftest import SR, render
from pedalfx.dsp import PEDAL_CLASSES, REGISTRY, create_pedal, pedal_from_dict
from pedalfx.dsp.console import CONSOLE_PRESETS, EFFECTS, MODULE_KEYS, PrismConsole
from pedalfx.dsp.core import DelayLine, Param, Reverser

REQUESTED = {"phaser", "delay", "reverb", "distortion", "chorus", "console"}


def solo_console(key, fx, amount=0.8, **params):
    """A console with only one module switched on."""
    pedal = create_pedal("console", SR)
    for k in MODULE_KEYS:
        pedal.set(f"{k}_fx", 0)
    pedal.set(f"{key}_fx", fx)
    pedal.set(f"{key}_amt", amount)
    for name, value in params.items():
        pedal.set(name, value)
    return pedal


def test_registry_has_every_requested_pedal():
    assert set(REGISTRY) >= REQUESTED
    assert len({cls.NAME for cls in PEDAL_CLASSES}) == len(PEDAL_CLASSES)


@pytest.mark.parametrize("cls", PEDAL_CLASSES, ids=lambda c: c.TYPE)
@pytest.mark.parametrize("block", [64, 256, 1000])
def test_pedal_output_is_sane(cls, block, riff):
    out = render(cls(SR), riff[:SR], block)
    assert out.shape == (2, SR)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert 0.005 < np.sqrt(np.mean(out ** 2)) < 0.5  # audible, not blown up


EFFECTS_ONLY = [c for c in PEDAL_CLASSES if c.TYPE not in ("tuner", "looper")]  # those pass audio through


@pytest.mark.parametrize("cls", EFFECTS_ONLY, ids=lambda c: c.TYPE)
def test_pedal_changes_the_signal(cls, riff):
    dry = np.stack([riff, riff])
    assert np.abs(render(cls(SR), riff) - dry).max() > 0.01


@pytest.mark.parametrize("cls", PEDAL_CLASSES, ids=lambda c: c.TYPE)
def test_every_knob_extreme_is_stable(cls, riff):
    for extreme in ("lo", "hi"):
        pedal = cls(SR)
        for param in cls.PARAMS:
            if not param.is_choice:
                pedal.set(param.key, getattr(param, extreme))
        out = render(pedal, riff[:SR])
        assert np.isfinite(out).all()
        assert np.abs(out).max() < 40.0  # a maxed boost is +34 dB; the engine clips after


@pytest.mark.parametrize("type_name", ["compressor", "boost", "distortion", "phaser",
                                       "chorus", "tremolo", "delay", "reverb"])
def test_block_size_does_not_change_the_sound(type_name, riff):
    a = render(create_pedal(type_name, SR), riff, 64)
    b = render(create_pedal(type_name, SR), riff, 1024)
    assert np.abs(a - b).max() < 1e-3


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_short_delay_with_big_blocks(mode, riff):
    """Delay shorter than the block exercises the chunked feedback loop."""
    def make():
        pedal = create_pedal("delay", SR)
        pedal.set("mode", mode)
        pedal.set("time", 30)
        pedal.set("feedback", 0.8)
        return pedal
    a, b = render(make(), riff, 64), render(make(), riff, 2048)
    assert np.abs(a - b).max() < 1e-3


def test_delay_repeats_arrive_on_time():
    pedal = create_pedal("delay", SR)
    pedal.set("time", 250)
    pedal.set("feedback", 0.5)
    pedal.set("mix", 0.5)
    pedal.set("tone", 1.0)
    click = np.zeros(SR, dtype=np.float32)
    click[100] = 1.0
    out = render(pedal, click)[0]
    first = 100 + int(0.25 * SR)
    assert abs(out[first]) > 0.3
    assert abs(out[first + int(0.25 * SR)]) > 0.1   # second repeat, quieter
    assert abs(out[first]) > abs(out[first + int(0.25 * SR)])
    assert np.abs(out[200:first - 50]).max() < 1e-4


def test_ping_pong_alternates_sides():
    pedal = create_pedal("delay", SR)
    for key, value in (("mode", 2), ("time", 200), ("feedback", 0.7), ("mix", 0.7), ("tone", 1.0)):
        pedal.set(key, value)
    click = np.zeros(SR, dtype=np.float32)
    click[10] = 1.0
    out = render(pedal, click)
    d = int(0.2 * SR)
    first, second = out[:, 10 + d], out[:, 10 + 2 * d]
    assert abs(first[0]) > 10 * abs(first[1])
    assert abs(second[1]) > 10 * abs(second[0])


def test_distortion_modes_differ_and_drive_adds_harmonics():
    t = np.arange(SR) / SR
    sine = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    outs = []
    for mode in range(3):
        pedal = create_pedal("distortion", SR)
        pedal.set("mode", mode)
        pedal.set("drive", 0.8)
        pedal.set("tone", 1.0)
        outs.append(render(pedal, sine)[0])
        spectrum = np.abs(np.fft.rfft(outs[-1][SR // 2:]))
        assert spectrum[330] > 0.02 * spectrum[110]  # 3rd harmonic (660 Hz) present
    assert np.abs(outs[0] - outs[1]).max() > 0.01
    assert np.abs(outs[1] - outs[2]).max() > 0.01


def test_chorus_is_stereo_and_tremolo_modulates_level(riff):
    out = render(create_pedal("chorus", SR), riff)
    assert np.abs(out[0] - out[1]).max() > 0.01
    pedal = create_pedal("tremolo", SR)
    pedal.set("depth", 1.0)
    pedal.set("rate", 4.0)
    steady = np.full(SR, 0.2, dtype=np.float32)
    env = render(pedal, steady)[0]
    assert env.min() < 0.01 and env.max() > 0.19


def test_reverb_has_a_tail():
    pedal = create_pedal("reverb", SR)
    pedal.set("size", 0.9)
    pedal.set("mix", 0.6)
    burst = np.zeros(SR * 2, dtype=np.float32)
    burst[:2000] = 0.3 * np.sin(np.arange(2000) * 0.2)
    out = render(pedal, burst)
    assert np.abs(out[:, SR:]).max() > 1e-3


# -- parameters ---------------------------------------------------------
def test_param_clamps_and_round_trips():
    p = Param("time", "Time", 30.0, 1200.0, 380.0, "ms", skew=2.0)
    assert p.clamp(5000) == 1200.0 and p.clamp(-1) == 30.0
    for value in (30.0, 100.0, 380.0, 1200.0):
        assert p.from_norm(p.to_norm(value)) == pytest.approx(value)
    choice = Param("mode", "Mode", default=0, choices=("A", "B", "C"))
    assert choice.clamp(7) == 2 and choice.format(1) == "B"


def test_set_rejects_unknown_parameter():
    with pytest.raises(KeyError):
        create_pedal("reverb", SR).set("nope", 1.0)


@pytest.mark.parametrize("cls", PEDAL_CLASSES, ids=lambda c: c.TYPE)
def test_pedal_serialization_round_trip(cls):
    pedal = cls(SR)
    for param in cls.PARAMS:
        pedal.set(param.key, param.from_norm(0.3))
    pedal.enabled = False
    pedal.finish = "crimson"
    clone = pedal_from_dict(pedal.to_dict(), SR)
    assert type(clone) is cls
    assert clone.values == pedal.values
    assert clone.enabled is False and clone.finish == "crimson"


def test_load_dict_ignores_junk():
    pedal = pedal_from_dict({"type": "delay", "params": {"time": "fast", "bogus": 1, "mix": 0.9}}, SR)
    assert pedal.get("mix") == 0.9
    assert pedal.get("time") == 380.0


# -- primitives ---------------------------------------------------------
def test_delay_line_fractional_read():
    line = DelayLine(1024)
    ramp = np.arange(200, dtype=np.float32)
    line.write(np.stack([ramp, ramp]))
    out = line.read(10.5, 200)
    assert out[0, 150] == pytest.approx(150 - 10.5)


def test_reverser_plays_previous_slice_backwards():
    rev = Reverser(SR)
    n = int(0.1 * SR)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    x = np.concatenate([ramp, np.zeros(n, dtype=np.float32)])
    out = rev.process(np.stack([x, x]), 0.1)[0]
    assert out[:n].max() == 0.0
    middle = out[n + n // 4: n + 3 * n // 4]
    assert np.all(np.diff(middle) < 0)  # the rising ramp comes back falling


# -- Prism Console ------------------------------------------------------
CONSOLE_CASES = [(key, fx) for key in MODULE_KEYS for fx in range(1, 6)]


@pytest.mark.parametrize("key,fx", CONSOLE_CASES,
                         ids=[EFFECTS[k][f - 1] for k, f in CONSOLE_CASES])
def test_console_effect(key, fx, riff):
    dry = np.stack([riff, riff])
    for amount in (0.3, 1.0):
        for block in (64, 512):
            out = render(solo_console(key, fx, amount), riff, block)
            assert np.isfinite(out).all()
            assert np.abs(out).max() < 4.0
            assert np.sqrt(np.mean(out ** 2)) > 0.004
    assert np.abs(out - dry).max() > 0.005


def test_console_has_four_modules_of_five_effects():
    assert len(MODULE_KEYS) == 4
    assert all(len(EFFECTS[k]) == 5 for k in MODULE_KEYS)
    assert len({name for k in MODULE_KEYS for name in EFFECTS[k]}) == 20


def test_console_all_modules_off_is_transparent(riff):
    pedal = solo_console("char", 0)
    out = render(pedal, riff)
    assert np.allclose(out[0], riff, atol=1e-6)


def test_console_mix_zero_is_dry(riff):
    pedal = create_pedal("console", SR)
    pedal.apply_preset("Worn Tape")
    pedal.set("mix", 0.0)
    assert np.allclose(render(pedal, riff)[0], riff, atol=1e-6)


def test_console_module_order_matters(riff):
    def make(order):
        pedal = solo_console("char", 3, 0.7)  # fuzz ...
        pedal.set("diff_fx", 1)               # ... and an echo
        pedal.set("diff_amt", 0.7)
        pedal.order = order
        return pedal
    fuzz_first = render(make([0, 1, 2, 3]), riff)
    echo_first = render(make([2, 1, 0, 3]), riff)
    assert np.abs(fuzz_first - echo_first).max() > 0.02


def test_console_swap_and_order_persist():
    pedal = create_pedal("console", SR)
    pedal.swap_modules(0, 3)
    assert pedal.order == [3, 1, 2, 0]
    clone = pedal_from_dict(pedal.to_dict(), SR)
    assert clone.order == [3, 1, 2, 0]
    bad = pedal_from_dict({"type": "console", "order": [0, 0, 1, 2]}, SR)
    assert bad.order == [0, 1, 2, 3]


@pytest.mark.parametrize("name", list(CONSOLE_PRESETS))
def test_console_presets(name, riff):
    pedal = create_pedal("console", SR)
    pedal.set("char_amt", 0.123)
    pedal.apply_preset(name)
    assert pedal.preset_name == name
    assert pedal.get("char_amt") == CONSOLE_PRESETS[name].get("char_amt", 0.5)
    out = render(pedal, riff)
    assert np.isfinite(out).all() and np.abs(out).max() < 4.0


def test_console_tilt_shifts_the_spectrum(riff):
    def brightness(tilt):
        pedal = solo_console("char", 0, tilt=tilt)
        spectrum = np.abs(np.fft.rfft(render(pedal, riff)[0]))
        freqs = np.fft.rfftfreq(len(riff), 1 / SR)
        return spectrum[freqs > 2000].sum() / spectrum[freqs < 300].sum()
    assert brightness(1.0) > 2 * brightness(-1.0)


def test_console_pitch_shifts_up_an_octave():
    t = np.arange(SR) / SR
    sine = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    pedal = solo_console("move", 5, 1.0, rate=12.0)  # top of RATE = +12 semitones
    spectrum = np.abs(np.fft.rfft(render(pedal, sine)[0][SR // 2:] * np.hanning(SR // 2)))
    freqs = np.fft.rfftfreq(SR // 2, 1 / SR)
    octave = spectrum[(freqs > 420) & (freqs < 460)].max()
    assert octave > 5 * spectrum[(freqs > 300) & (freqs < 380)].max()


def test_console_swell_fades_notes_in():
    pedal = solo_console("char", 5, 1.0)
    note = np.concatenate([np.zeros(SR // 4), 0.3 * np.ones(SR)]).astype(np.float32)
    out = render(pedal, note)[0]
    start = SR // 4
    assert abs(out[start + 200]) < 0.02          # attack is suppressed
    assert abs(out[-1]) > 0.1                    # then it blooms
    assert isinstance(pedal, PrismConsole)


def test_sample_rate_change_rebuilds(riff):
    pedal = create_pedal("console", SR)
    pedal.set_sample_rate(44100)
    assert pedal.sr == 44100
    assert np.isfinite(render(pedal, riff[:8000])).all()

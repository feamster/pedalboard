"""Synthesised drum kits and the rhythm styles for the looper's drum machine.

Nothing here is sampled: every hit is built from sine sweeps and filtered
noise when a kit is first requested, then cached per sample rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

F32 = np.float32
VELOCITY = {"X": 1.0, "x": 0.72, "o": 0.3}
INSTRUMENTS = "KSRHODCTL"  # kick snare rim hat open-hat ride crash tom floor-tom
KITS = ("Studio", "Sidestick", "Electro", "Lo-Fi")


# -- synthesis --------------------------------------------------------------
def _band(x, sr, lo, hi):
    spectrum = np.fft.rfft(x)
    f = np.maximum(np.fft.rfftfreq(len(x), 1.0 / sr), 1e-6)
    shape = 1.0 / np.sqrt(1.0 + (lo / f) ** 6) / np.sqrt(1.0 + (f / hi) ** 6)
    return np.fft.irfft(spectrum * shape, len(x))


def _env(n, sr, decay, attack=0.0008):
    t = np.arange(n) / sr
    return np.minimum(1.0, t / attack) * np.exp(-t * decay)


def _sweep(n, sr, f_start, f_end, rate):
    t = np.arange(n) / sr
    freq = f_end + (f_start - f_end) * np.exp(-t * rate)
    return np.sin(2 * np.pi * np.cumsum(freq) / sr)


def _tone(n, sr, freq):
    return np.sin(2 * np.pi * freq * np.arange(n) / sr)


def _finish(x, level):
    x = x / max(1e-9, np.abs(x).max()) * level
    tail = min(len(x), 256)
    x[-tail:] *= np.linspace(1.0, 0.0, tail)
    return x.astype(F32)


def _studio(sr, rng):
    def n(seconds):
        return int(seconds * sr)

    def noise(count):
        return rng.standard_normal(count)

    k, s, r = n(0.45), n(0.28), n(0.09)
    hits = {
        "K": (_sweep(k, sr, 165, 48, 45) * _env(k, sr, 8)
              + 0.25 * _band(noise(k), sr, 1500, 6000) * _env(k, sr, 300), 0.9),
        "S": (0.75 * _band(noise(s), sr, 400, 9000) * _env(s, sr, 20)
              + 0.45 * _sweep(s, sr, 260, 180, 60) * _env(s, sr, 26), 0.7),
        # sidestick: a woody knock, almost no noise
        "R": (0.6 * _tone(r, sr, 1720) * _env(r, sr, 110) + 0.45 * _tone(r, sr, 560) * _env(r, sr, 70)
              + 0.5 * _band(noise(r), sr, 1500, 7000) * _env(r, sr, 450), 0.55),
        "H": (_band(noise(n(0.07)), sr, 7000, 16000) * _env(n(0.07), sr, 75), 0.28),
        "O": (_band(noise(n(0.45)), sr, 6000, 16000) * _env(n(0.45), sr, 8), 0.28),
        "D": (_band(noise(n(0.8)), sr, 4500, 14000) * _env(n(0.8), sr, 4.5)
              + 0.45 * (_tone(n(0.8), sr, 3150) + _tone(n(0.8), sr, 4720)) * _env(n(0.8), sr, 7), 0.26),
        "C": (_band(noise(n(1.6)), sr, 2500, 15000) * _env(n(1.6), sr, 2.8, 0.004), 0.4),
        "T": (_sweep(n(0.35), sr, 210, 140, 30) * _env(n(0.35), sr, 9), 0.6),
        "L": (_sweep(n(0.45), sr, 130, 85, 25) * _env(n(0.45), sr, 7.5), 0.65),
    }
    return {name: _finish(wave, level) for name, (wave, level) in hits.items()}


_cache: dict = {}


def make_kit(name: str, sr: int) -> dict:
    """Instrument letter -> mono float32 one-shot, for one of ``KITS``."""
    key = (name, int(sr))
    if key in _cache:
        return _cache[key]
    sr = int(sr)
    rng = np.random.default_rng(1234)
    kit = dict(_studio(sr, rng))
    if name == "Sidestick":
        kit["S"] = (kit["R"] * 1.2).astype(F32)   # every backbeat becomes a rim click
    elif name == "Electro":
        k, c, h = int(0.7 * sr), int(0.3 * sr), int(0.05 * sr)
        kit["K"] = _finish(_sweep(k, sr, 120, 42, 20) * _env(k, sr, 4.2), 0.95)
        clap = np.zeros(c)
        burst = _band(rng.standard_normal(c), sr, 900, 4500)
        for delay in (0.0, 0.011, 0.023):
            d = int(delay * sr)
            clap[d:] += burst[: c - d] * _env(c - d, sr, 180)
        clap += 0.6 * burst * _env(c, sr, 22)
        kit["S"] = _finish(clap, 0.7)
        kit["H"] = _finish(_band(rng.standard_normal(h), sr, 8000, 16000) * _env(h, sr, 120), 0.26)
    elif name == "Lo-Fi":
        for inst, wave in kit.items():
            dull = np.tanh(2.0 * _band(wave.astype(np.float64), sr, 30, 4200)) / np.tanh(2.0)
            kit[inst] = _finish(np.round(dull * 48) / 48, float(np.abs(wave).max()))
    _cache[key] = kit
    return kit


# -- rhythm styles ----------------------------------------------------------
@dataclass(frozen=True)
class Style:
    name: str
    beats: int      # beats counted per measure
    quarters: int   # measure length in quarter notes
    steps: int      # grid steps per measure
    parts: dict     # "A" / "B" / "fill" -> {instrument: row}

    def __post_init__(self):
        for part in ("A", "B", "fill"):
            for inst, row in self.parts[part].items():
                assert inst in INSTRUMENTS, (self.name, inst)
                assert len(row) == self.steps and set(row) <= set("Xxo."), (self.name, part, inst)


def _style(name, a, b, fill, beats=4, quarters=4, steps=16) -> Style:
    return Style(name, beats, quarters, steps, {"A": a, "B": b, "fill": fill})


EIGHTHS = "x.x.x.x.x.x.x.x."
SIXTEENTHS = "xoxoxoxoxoxoxoxo"

STYLES = (
    _style("Sidestick",
           {"K": "x.......x.x.....", "R": "....x.......x...", "H": EIGHTHS},
           {"K": "x.....x.x.x.....", "R": "....x.......x...", "D": EIGHTHS},
           {"K": "x.......x.......", "R": "....x..x..x.x.xx", "H": "x.x.x.x........."}),
    _style("Rock",
           {"K": "x.......x.x.....", "S": "....X.......X...", "H": EIGHTHS},
           {"K": "x.x.....x.x.....", "S": "....X.......X...", "D": EIGHTHS},
           {"K": "x.......x.......", "S": "....X.x.xx......", "T": "..........xx....",
            "L": "............xxxx", "H": "x.x.x.x........."}),
    _style("Driving 8ths",
           {"K": "x.x...x.x.x...x.", "S": "....X.......X...", "H": "X.x.X.x.X.x.X.x."},
           {"K": "x..x..x.x..x..x.", "S": "....X.......X...", "O": "x...x...x...x..."},
           {"K": "x...x...x...x...", "S": "X.x.X.x.X.xxXxxx"}),
    _style("Pop",
           {"K": "x.....x...x.....", "S": "....X.......X...", "H": EIGHTHS},
           {"K": "x..x..x...x..x..", "S": "....X.......X..o", "H": SIXTEENTHS},
           {"K": "x.....x.x.......", "S": "....X.....o.X.xx", "H": "x.x.x.x.x......."}),
    _style("Half-Time",
           {"K": "x.........x.....", "S": "........X.......", "H": EIGHTHS},
           {"K": "x.....x...x.....", "S": "........X.......", "D": EIGHTHS},
           {"K": "x.........x.....", "S": "........X...x.x.", "L": ".............x.x",
            "H": "x.x.x.x........."}),
    _style("Funk",
           {"K": "x..x......x..x..", "S": "....X..o.o..X..o", "H": SIXTEENTHS},
           {"K": "x.x...x..xx.....", "S": "....X..o....X.o.", "H": SIXTEENTHS, "O": "..............x."},
           {"K": "x..x....x.......", "S": "....X..o.oX.oXxx", "H": "xoxoxoxo........"}),
    _style("Bossa",
           {"K": "x.....x.x.....x.", "R": "x..x..x...x.x...", "H": EIGHTHS},
           {"K": "x.....x.x.....x.", "R": "x..x..x...x.x...", "D": EIGHTHS},
           {"K": "x.....x.x.....x.", "R": "x..x..x...x.xxxx", "H": EIGHTHS}),
    _style("One Drop",
           {"K": "........X.......", "R": "........x.......", "H": "o.X.o.X.o.X.o.X."},
           {"K": "x...x...x...x...", "R": "........x.......", "H": "o.X.o.X.o.X.o.X."},
           {"K": "........X.......", "S": "..........x.xx.x", "T": "........x.......",
            "H": "o.X.o.X........."}),
    _style("Train",
           {"K": "x.......x.......", "S": "xoxoXoxoxoxoXoxo"},
           {"K": "x.....x.x.....x.", "S": "xoxoXoxoxoxoXoxo"},
           {"K": "x.......x.......", "S": "XoxoXoxoXxXxXxxx"}),
    _style("Motown",
           {"K": "x.....x.x.x.....", "S": "X...X...X...X...", "H": EIGHTHS},
           {"K": "x.....x.x.x...x.", "S": "X...X...X...X...", "O": "..x...x...x...x."},
           {"K": "x.....x.x.......", "S": "X...X...X.x.XxXx", "H": "x.x.x.x........."}),
    _style("Shuffle",
           {"K": "x.....x.....", "S": "...X.....X..", "H": "x.xx.xx.xx.x"},
           {"K": "x....xx.....", "S": "...X.....X..", "D": "x.xx.xx.xx.x"},
           {"K": "x.....x.....", "S": "...X..x.xxxx", "H": "x.xx.x......"}, steps=12),
    _style("Waltz",
           {"K": "x...........", "R": "....x...x...", "H": "x.x.x.x.x.x."},
           {"K": "x.........x.", "S": "....x...x...", "D": "x.x.x.x.x.x."},
           {"K": "x...........", "S": "....x...xxxx", "H": "x.x.x......."},
           beats=3, quarters=3, steps=12),
    _style("6/8 Ballad",
           {"K": "x.........x.", "R": "......x.....", "H": "x.x.x.x.x.x."},
           {"K": "x...x.....x.", "S": "......X.....", "D": "x.x.x.x.x.x."},
           {"K": "x...........", "S": "......X.xxxx", "H": "x.x.x......."},
           beats=6, quarters=3, steps=12),
    _style("Metronome",
           {"R": "X...x...x...x..."}, {"R": "X...x...x...x..."}, {"R": "X...x...x...x..."}),
)
STYLE_NAMES = tuple(s.name for s in STYLES)


def count_in_style(style: Style) -> Style:
    """One measure of rim clicks on the beats of ``style`` (accented downbeat)."""
    per_beat = style.steps // style.beats
    row = "".join(("X" if i == 0 else "x") if i % per_beat == 0 else "." for i in range(style.steps))
    parts = {"A": {"R": row}, "B": {"R": row}, "fill": {"R": row}}
    return Style("Count", style.beats, style.quarters, style.steps, parts)

"""DSP building blocks shared by every pedal.

Everything here works on float32 blocks shaped ``(2, n)`` and is vectorised
with numpy so it is cheap enough to run inside the audio callback. Filters and
the classic effects come from Spotify's ``pedalboard`` (stateful, called with
``reset=False``); the things pedalboard does not have - modulated delay
lines, feedback echoes with a processed loop, reverse buffers - live here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

F32 = np.float32
TWO_PI = 2.0 * math.pi


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def run(plugin, x: np.ndarray, sr: float) -> np.ndarray:
    """Run a pedalboard plugin on one block, keeping its internal state."""
    x = np.ascontiguousarray(x, dtype=F32)
    return plugin.process(x, sr, buffer_size=x.shape[1], reset=False)


@dataclass(frozen=True)
class Param:
    """A user-facing control. Continuous unless ``choices`` is given."""

    key: str
    label: str
    lo: float = 0.0
    hi: float = 1.0
    default: float = 0.5
    unit: str = "%"
    skew: float = 1.0  # >1 gives the low end of the range more knob travel
    choices: tuple = ()

    @property
    def is_choice(self) -> bool:
        return bool(self.choices)

    def clamp(self, value: float) -> float:
        if self.is_choice:
            return int(min(len(self.choices) - 1, max(0, round(float(value)))))
        return float(min(self.hi, max(self.lo, float(value))))

    def to_norm(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        t = (self.clamp(value) - self.lo) / (self.hi - self.lo)
        return t ** (1.0 / self.skew)

    def from_norm(self, t: float) -> float:
        t = min(1.0, max(0.0, t))
        return self.clamp(self.lo + (self.hi - self.lo) * t ** self.skew)

    def format(self, value: float) -> str:
        if self.is_choice:
            return str(self.choices[int(value)])
        if self.unit == "%":
            return f"{100 * (value - self.lo) / (self.hi - self.lo):.0f}%"
        if self.unit == "ms":
            return f"{value:.0f} ms"
        if self.unit == "s":
            return f"{value * 1000:.0f} ms" if value < 1 else f"{value:.2f} s"
        if self.unit == "Hz":
            return f"{value:.2f} Hz"
        if self.unit == "dB":
            return f"{value:+.1f} dB"
        if self.unit == "bpm":
            return f"{value:.0f} bpm"
        if self.unit == "±":
            return f"{value:+.2f}"
        return f"{value:.2f}"


class Pedal:
    """Base class: a set of named parameter values plus a block processor."""

    TYPE = "pedal"
    NAME = "Pedal"
    TAGLINE = ""
    FINISH = "graphite"
    PARAMS: tuple = ()

    def __init__(self, sr: float = 48000.0):
        self.sr = float(sr)
        self.enabled = True
        self.finish: str | None = None  # None -> the pedal's default finish
        self.values = {p.key: p.default for p in self.PARAMS}
        self._build()

    # -- parameters ---------------------------------------------------
    @classmethod
    def param(cls, key: str) -> Param:
        for p in cls.PARAMS:
            if p.key == key:
                return p
        raise KeyError(f"{cls.NAME} has no parameter '{key}'")

    def set(self, key: str, value: float) -> None:
        self.values[key] = self.param(key).clamp(value)

    def get(self, key: str) -> float:
        return self.values[key]

    # -- lifecycle ----------------------------------------------------
    def _build(self) -> None:
        """(Re)create all DSP state for the current sample rate."""

    def reset(self) -> None:
        self._build()

    def set_sample_rate(self, sr: float) -> None:
        if float(sr) != self.sr:
            self.sr = float(sr)
            self._build()

    def process(self, x: np.ndarray) -> np.ndarray:
        return x

    # -- persistence --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "type": self.TYPE,
            "enabled": self.enabled,
            "finish": self.finish,
            "params": dict(self.values),
        }

    def load_dict(self, data: dict) -> None:
        self.enabled = bool(data.get("enabled", True))
        self.finish = data.get("finish")
        for key, value in (data.get("params") or {}).items():
            try:
                self.set(key, value)
            except (KeyError, TypeError, ValueError):
                pass  # unknown or malformed values in old files are ignored


class Ramp:
    """Linear per-block smoothing for gains, so knob moves don't zipper."""

    def __init__(self, value: float | None = None):
        self.value = value  # None: snap to the first target instead of ramping

    def block(self, target: float, n: int):
        target = float(target)
        if self.value is None or abs(target - self.value) < 1e-7:
            self.value = target
            return F32(target)
        out = np.linspace(self.value, target, n + 1, dtype=F32)[1:]
        self.value = target
        return out


class Phasor:
    """LFO phase accumulator; returns per-sample phase in cycles."""

    def __init__(self, sr: float, phase: float = 0.0):
        self.sr = sr
        self.phase = phase

    def block(self, rate_hz: float, n: int) -> np.ndarray:
        inc = rate_hz / self.sr
        out = self.phase + inc * np.arange(n)
        self.phase = (self.phase + inc * n) % 1.0
        return out

    def sine(self, rate_hz: float, n: int, offset: float = 0.0) -> np.ndarray:
        return np.sin(TWO_PI * (self.block(rate_hz, n) + offset))


class DelayLine:
    """Circular buffer with fractional (linear-interpolated) reads."""

    def __init__(self, max_samples: int, channels: int = 2):
        size = 1 << int(math.ceil(math.log2(max_samples + 8)))
        self.buf = np.zeros((channels, size), dtype=F32)
        self.mask = size - 1
        self.max_delay = size - 4
        self.w = 0
        self._ch = np.arange(channels)[:, None]

    def clear(self) -> None:
        self.buf[:] = 0.0

    def write(self, x: np.ndarray) -> None:
        n = x.shape[1]
        idx = (self.w + np.arange(n)) & self.mask
        self.buf[:, idx] = x
        self.w = (self.w + n) & self.mask

    def read(self, delay, n: int, ahead: bool = False) -> np.ndarray:
        """Read ``n`` samples ``delay`` samples in the past.

        ``delay`` is a scalar, an ``(n,)`` array or a ``(channels, n)`` array.
        With ``ahead=False`` the current block has already been written; with
        ``ahead=True`` it is about to be (feedback loops), so ``delay`` must
        stay greater than ``n``.
        """
        base = self.w + np.arange(n) - (0 if ahead else n)
        pos = base - np.asarray(delay, dtype=np.float64)
        i0 = np.floor(pos).astype(np.int64)
        frac = (pos - i0).astype(F32)
        if pos.ndim == 1:
            a = self.buf[:, i0 & self.mask]
            b = self.buf[:, (i0 + 1) & self.mask]
        else:
            a = self.buf[self._ch, i0 & self.mask]
            b = self.buf[self._ch, (i0 + 1) & self.mask]
        return a + (b - a) * frac


class Echo:
    """Feedback delay whose repeats can be filtered, saturated and wobbled.

    Returns only the wet signal. Delay-time changes glide like a tape machine
    changing speed instead of clicking.
    """

    def __init__(self, sr: float, max_seconds: float = 3.2):
        from pedalboard import LowpassFilter

        self.sr = sr
        self.line = DelayLine(int(sr * max_seconds))
        self.lp = LowpassFilter(cutoff_frequency_hz=5000)
        self.d: float | None = None

    def clear(self) -> None:
        self.line.clear()
        self.d = None

    def process(self, x, delay_s, feedback, damp_hz=None, wobble=None,
                pingpong=False, drive=False, send=1.0) -> np.ndarray:
        n = x.shape[1]
        target = min(self.line.max_delay - 64.0, max(96.0, delay_s * self.sr))
        if self.d is None:
            self.d = target
        step = min(0.5 * n, max(-0.5 * n, target - self.d))
        d = self.d + step * np.arange(1, n + 1) / n
        self.d += step
        if wobble is not None:
            d = d + wobble
        limit = max(16, int(d.min()) - 2)
        pieces = -(-n // limit)
        size = -(-n // pieces)
        if damp_hz:
            self.lp.cutoff_frequency_hz = float(damp_hz)
        out = np.empty((2, n), dtype=F32)
        for s in range(0, n, size):
            e = min(n, s + size)
            rd = self.line.read(d[s:e], e - s, ahead=True)
            out[:, s:e] = rd
            fb = run(self.lp, rd, self.sr) if damp_hz else rd
            if drive:
                fb = np.tanh(fb)
            if pingpong:
                fb = fb[::-1]
            self.line.write(x[:, s:e] * send + fb * feedback)
        return out


class Reverser:
    """Records slices and plays the previous slice backwards."""

    def __init__(self, sr: float, max_seconds: float = 1.6):
        self.sr = sr
        size = int(sr * max_seconds) + 8
        self.rec = np.zeros((2, size), dtype=F32)
        self.play = np.zeros((2, size), dtype=F32)
        self.length = int(sr * 0.4)
        self.pos = 0
        self.fade = int(sr * 0.012)

    def clear(self) -> None:
        self.rec[:] = 0.0
        self.play[:] = 0.0
        self.pos = 0

    def process(self, x: np.ndarray, seconds: float) -> np.ndarray:
        n = x.shape[1]
        want = int(min(self.rec.shape[1] - 1, max(self.fade * 4, seconds * self.sr)))
        out = np.empty((2, n), dtype=F32)
        i = 0
        while i < n:
            if self.pos == 0:
                self.length = want  # slice length only changes on a boundary
            m = min(n - i, self.length - self.pos)
            k = self.pos + np.arange(m)
            self.rec[:, k] = x[:, i:i + m]
            win = np.minimum(1.0, np.minimum(k, self.length - 1 - k) / self.fade)
            out[:, i:i + m] = self.play[:, self.length - 1 - k] * win.astype(F32)
            self.pos += m
            i += m
            if self.pos >= self.length:
                self.rec, self.play = self.play, self.rec
                self.pos = 0
        return out


class PitchTaps:
    """Two cross-faded moving delay taps: a cheap, latency-free pitch shifter."""

    def __init__(self, sr: float, window_s: float = 0.055):
        self.sr = sr
        self.window = window_s * sr
        self.line = DelayLine(int(self.window * 2) + 64)
        self.phase = 0.0

    def clear(self) -> None:
        self.line.clear()

    def process(self, x: np.ndarray, semitones: float) -> np.ndarray:
        n = x.shape[1]
        ratio = 2.0 ** (semitones / 12.0)
        inc = (1.0 - ratio) / self.window
        ph = (self.phase + inc * np.arange(n)) % 1.0
        self.phase = (self.phase + inc * n) % 1.0
        self.line.write(x)
        out = np.zeros((2, n), dtype=F32)
        for offset in (0.0, 0.5):
            p = (ph + offset) % 1.0
            gain = (np.sin(math.pi * p) ** 2).astype(F32)
            out += self.line.read(p * self.window + 2.0, n) * gain
        return out

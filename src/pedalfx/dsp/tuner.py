"""Chromatic tuner. The audio thread only copies samples into a ring; pitch
detection runs on the UI thread when the display asks for a reading."""

from __future__ import annotations

import math

import numpy as np

from .core import F32, Param, Pedal, Ramp

NOTE_NAMES = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")


def detect_pitch(x: np.ndarray, sr: float, fmin: float = 55.0, fmax: float = 1400.0):
    """Fundamental frequency of ``x`` in Hz, or None if there is no clear pitch.

    Normalised autocorrelation (the McLeod pitch method): pick the first strong
    peak rather than the tallest, so harmonics don't cause octave errors.
    """
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    n = len(x)
    if n < 256 or np.sqrt(np.mean(x * x)) < 0.003:
        return None
    spectrum = np.fft.rfft(x, 2 * n)
    acf = np.fft.irfft(spectrum.real ** 2 + spectrum.imag ** 2)[:n]
    squares = np.concatenate(([0.0], np.cumsum(x * x)))
    lags = np.arange(n)
    energy = squares[n - lags] + squares[n] - squares[lags]
    nsdf = 2.0 * acf / np.maximum(energy, 1e-12)

    lo = max(2, int(sr / fmax))
    hi = min(n // 2, int(sr / fmin))
    negative = np.nonzero(nsdf[:hi] < 0)[0]
    if not len(negative):
        return None
    start = max(lo, int(negative[0]))  # skip the lag-zero lobe
    seg = nsdf[start:hi]
    if len(seg) < 3:
        return None
    peaks = np.nonzero((seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:]))[0] + 1
    if not len(peaks):
        return None
    best = seg[peaks].max()
    if best < 0.6:
        return None
    k = int(peaks[np.nonzero(seg[peaks] >= 0.9 * best)[0][0]]) + start
    a, b, c = nsdf[k - 1], nsdf[k], nsdf[k + 1]
    denom = a - 2 * b + c
    shift = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
    return sr / (k + shift)


def note_for(freq: float, ref: float = 440.0) -> tuple:
    """(name, octave, cents off) of the nearest equal-tempered note."""
    midi = 69.0 + 12.0 * math.log2(freq / ref)
    nearest = int(round(midi))
    return NOTE_NAMES[nearest % 12], nearest // 12 - 1, 100.0 * (midi - nearest)


class Tuner(Pedal):
    TYPE = "tuner"
    NAME = "Pitchfork"
    TAGLINE = "chromatic tuner"
    FINISH = "midnight"
    PARAMS = (
        Param("ref", "A4", 430.0, 450.0, 440.0, "Hz"),
        Param("mode", "Output", default=0, choices=("Thru", "Mute")),
    )

    def _build(self):
        self.window = 4096 if self.sr < 70000 else 8192
        self.ring = np.zeros(self.window * 2, dtype=F32)
        self.w = 0
        self.blocks = 0          # bumped every processed block
        self._read_at = -1
        self.gain = Ramp()

    def process(self, x):
        n = x.shape[1]
        mono = 0.5 * (x[0] + x[1])
        size = len(self.ring)
        if n >= size:
            self.ring[:] = mono[-size:]
            self.w = 0
        else:
            idx = (self.w + np.arange(n)) % size
            self.ring[idx] = mono
            self.w = (self.w + n) % size
        self.blocks += 1
        if int(self.values["mode"]) == 1 or self.gain.value not in (None, 1.0):
            return x * self.gain.block(0.0 if int(self.values["mode"]) == 1 else 1.0, n)
        self.gain.value = 1.0
        return x

    def read(self):
        """Latest reading as a dict, or None (silence, noise, or audio stopped)."""
        if self.blocks == self._read_at:
            return None  # nothing new has arrived: the engine is off or we are bypassed
        self._read_at = self.blocks
        size = len(self.ring)
        w = self.w
        recent = self.ring[(w - self.window + np.arange(self.window)) % size]
        freq = detect_pitch(recent, self.sr)
        if freq is None:
            return None
        name, octave, cents = note_for(freq, self.values["ref"])
        return {"freq": freq, "note": name, "octave": octave, "cents": cents}

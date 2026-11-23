"""Signal sources that stand in for a guitar: a built-in synthesized riff and
audio files. Both are plain looping stereo-less (mono) float32 buffers."""

from __future__ import annotations

import numpy as np

F32 = np.float32

_NOTE = {"E2": 82.41, "G2": 98.00, "B2": 123.47, "C3": 130.81, "D3": 146.83,
         "E3": 164.81, "G3": 196.00, "A3": 220.00, "B3": 246.94, "C4": 261.63,
         "D4": 293.66, "E4": 329.63, "F#4": 369.99, "G4": 392.00}

_RIFF = (  # four bars of eighth notes: Em - Cmaj7 - G - D
    "E2 B2 E3 G3 B3 G3 E3 B3 "
    "C3 G3 C4 E4 B3 E4 C4 G3 "
    "G2 D3 G3 B3 D4 B3 G3 D4 "
    "D3 A3 D4 F#4 A3 D4 F#4 D4"
).split()


def _pluck(freq: float, seconds: float, sr: int, rng) -> np.ndarray:
    """Karplus-Strong plucked string, computed a period at a time."""
    period = max(2, int(round(sr / freq)))
    n = int(seconds * sr)
    cur = rng.uniform(-1.0, 1.0, period)
    cur = 0.5 * (cur + np.roll(cur, 1))  # soften the pick attack a little
    out = np.empty(n)
    for start in range(0, n, period):
        m = min(period, n - start)
        out[start:start + m] = cur[:m]
        cur = 0.4985 * (cur + np.roll(cur, 1))
    return out


def demo_riff(sr: int, bpm: float = 96.0) -> np.ndarray:
    """A looping clean-guitar arpeggio so the board can be auditioned without
    plugging anything in."""
    rng = np.random.default_rng(3)
    step = int(sr * 60.0 / bpm / 2.0)
    total = step * len(_RIFF)
    loop = np.zeros(total)
    for i, name in enumerate(_RIFF):
        note = _pluck(_NOTE[name], 1.7, sr, rng) * (1.0 if i % 8 == 0 else 0.75)
        idx = (i * step + np.arange(len(note))) % total  # tails wrap for a seamless loop
        np.add.at(loop, idx, note)
    loop *= 0.3 / np.max(np.abs(loop))
    return loop.astype(F32)


def load_audio_file(path: str, sr: int, max_seconds: float = 600.0) -> np.ndarray:
    """Load (up to ten minutes of) an audio file as mono at ``sr``."""
    from pedalboard.io import AudioFile

    with AudioFile(path) as f:
        frames = int(min(f.frames, max_seconds * f.samplerate))
        audio = f.read(frames)
        file_sr = f.samplerate
    mono = audio.mean(axis=0)
    if int(file_sr) != int(sr) and len(mono) > 1:
        positions = np.arange(int(len(mono) * sr / file_sr)) * (file_sr / sr)
        mono = np.interp(positions, np.arange(len(mono)), mono)
    if len(mono) == 0:
        raise ValueError("audio file is empty")
    return mono.astype(F32)

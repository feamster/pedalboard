"""Prism Console - a four-module multi-effect in the spirit of the Hologram
Chroma Console pedal and XLN's RC-20 Retro Color plugin.

Four modules run in series (the order is user-swappable). Each module offers
five effects, one active at a time, with a single AMOUNT knob:

    CHARACTER  Drive / Sweeten / Fuzz / Howl / Swell
    MOVEMENT   Doubler / Vibrato / Phaser / Tremolo / Pitch
    DIFFUSION  Cascade / Reels / Space / Collage / Reverse
    TEXTURE    Filter / Squash / Cassette / Broken / Interference

Four global knobs shape all of it: TILT (tilt EQ), RATE (modulation speed),
TIME (delay / reverb length) and MIX (overall wet/dry).

This is an original implementation written from the published feature
descriptions of those products - no code or impulse data from either.
"""

from __future__ import annotations

import numpy as np
import pedalboard as pb

from .core import (
    F32,
    DelayLine,
    Echo,
    Param,
    Pedal,
    Phasor,
    PitchTaps,
    Ramp,
    Reverser,
    db_to_lin,
    run,
)

MODULES = ("character", "movement", "diffusion", "texture")
MODULE_KEYS = ("char", "move", "diff", "text")
EFFECTS = {
    "char": ("Drive", "Sweeten", "Fuzz", "Howl", "Swell"),
    "move": ("Doubler", "Vibrato", "Phaser", "Tremolo", "Pitch"),
    "diff": ("Cascade", "Reels", "Space", "Collage", "Reverse"),
    "text": ("Filter", "Squash", "Cassette", "Broken", "Interference"),
}
PITCH_INTERVALS = (-12, -7, -5, 4, 7, 12)

# name -> partial parameter set; anything not listed keeps its default
CONSOLE_PRESETS = {
    "Init": {},
    "Worn Tape": {"char_fx": 2, "char_amt": 0.35, "move_fx": 2, "move_amt": 0.3,
                  "diff_fx": 2, "diff_amt": 0.35, "text_fx": 3, "text_amt": 0.6,
                  "rate": 0.8, "time": 0.36, "tilt": -0.15},
    "Glass Double": {"char_fx": 2, "char_amt": 0.5, "move_fx": 1, "move_amt": 0.7,
                     "diff_fx": 3, "diff_amt": 0.4, "text_fx": 0, "time": 0.6,
                     "tilt": 0.25},
    "Howling Reels": {"char_fx": 4, "char_amt": 0.45, "move_fx": 0, "diff_fx": 2,
                      "diff_amt": 0.5, "text_fx": 2, "text_amt": 0.5, "time": 0.42},
    "Backwards Bloom": {"char_fx": 5, "char_amt": 0.5, "move_fx": 3, "move_amt": 0.35,
                        "diff_fx": 5, "diff_amt": 0.75, "text_fx": 1, "text_amt": 0.3,
                        "time": 0.7, "rate": 0.35},
    "Dying Walkman": {"char_fx": 1, "char_amt": 0.3, "move_fx": 2, "move_amt": 0.45,
                      "diff_fx": 0, "text_fx": 4, "text_amt": 0.7, "rate": 0.5,
                      "tilt": -0.3},
    "Shortwave": {"char_fx": 3, "char_amt": 0.25, "move_fx": 4, "move_amt": 0.5,
                  "diff_fx": 1, "diff_amt": 0.35, "text_fx": 5, "text_amt": 0.55,
                  "rate": 6.0, "time": 0.22},
    "Octave Cloud": {"char_fx": 2, "char_amt": 0.4, "move_fx": 5, "move_amt": 0.5,
                     "diff_fx": 4, "diff_amt": 0.6, "text_fx": 1, "text_amt": 0.35,
                     "rate": 11.5, "time": 0.9, "tilt": 0.1},
    "Pump & Swirl": {"char_fx": 1, "char_amt": 0.6, "move_fx": 3, "move_amt": 0.7,
                     "diff_fx": 1, "diff_amt": 0.3, "text_fx": 2, "text_amt": 0.7,
                     "rate": 0.4, "time": 0.33},
}


def _fx_param(key: str, label: str, default: int) -> Param:
    return Param(f"{key}_fx", label, default=default, choices=("Off",) + EFFECTS[key])


class PrismConsole(Pedal):
    TYPE = "console"
    NAME = "Prism Console"
    TAGLINE = "four-module texture workstation"
    FINISH = "pearl"
    PARAMS = (
        Param("tilt", "Tilt", -1.0, 1.0, 0.0, "±"),
        Param("rate", "Rate", 0.05, 12.0, 1.0, "Hz", skew=2.5),
        Param("time", "Time", 0.04, 1.5, 0.35, "s", skew=2.0),
        Param("mix", "Mix", default=1.0),
        Param("char_amt", "Amount", default=0.5),
        Param("move_amt", "Amount", default=0.5),
        Param("diff_amt", "Amount", default=0.4),
        Param("text_amt", "Amount", default=0.5),
        _fx_param("char", "Character", 1),
        _fx_param("move", "Movement", 1),
        _fx_param("diff", "Diffusion", 3),
        _fx_param("text", "Texture", 3),
        Param("level", "Level", -12.0, 12.0, 0.0, "dB"),
    )

    def __init__(self, sr: float = 48000.0):
        self.order = [0, 1, 2, 3]  # indices into MODULE_KEYS, signal order
        self.preset_name = "Init"
        super().__init__(sr)

    # -- state --------------------------------------------------------
    def _build(self):
        sr = self.sr
        self._rng = np.random.default_rng(7)
        self._active = {k: -1 for k in MODULE_KEYS}
        # character
        self.sweet_comp = pb.Compressor(threshold_db=-20, ratio=2.5, attack_ms=8, release_ms=140)
        self.sweet_shelf = pb.HighShelfFilter(cutoff_frequency_hz=3500)
        self.fuzz_hp = pb.HighpassFilter(cutoff_frequency_hz=60)
        self.fuzz_lp = pb.LowpassFilter(cutoff_frequency_hz=5200)
        self.howl_bp = pb.LadderFilter(mode=pb.LadderFilter.Mode.BPF12, resonance=0.8)
        self.sw_gain, self.sw_slow, self.sw_quiet, self.sw_since = 1.0, 0.0, 0.0, 1.0
        # movement
        self.lfo = Phasor(sr)
        self.mod_line = DelayLine(int(sr * 0.08))
        self.phaser = pb.Phaser(centre_frequency_hz=900, mix=0.5)
        self.pitch = PitchTaps(sr)
        # diffusion
        self.echo = Echo(sr, max_seconds=3.3)
        self.reel_lfo = Phasor(sr)
        self.space = pb.Reverb(wet_level=1.0, dry_level=0.0, width=1.0)
        self.reverser = Reverser(sr)
        # texture
        self.filt = pb.LadderFilter(mode=pb.LadderFilter.Mode.LPF24, resonance=0.35)
        self.squash = pb.Compressor(attack_ms=0.5, release_ms=110)
        self.tape_line = DelayLine(int(sr * 0.06))
        self.wow, self.flutter = Phasor(sr), Phasor(sr, 0.3)
        self.tape_lp = pb.LowpassFilter(cutoff_frequency_hz=7000)
        self.drift, self.drop_gain = 0.0, np.ones(2)
        self.drop_left, self.drop_depth = np.zeros(2), np.zeros(2)
        self.sr_count, self.sr_last = 0, np.zeros(2, dtype=F32)
        # global
        self.tilt_lo = pb.LowShelfFilter(cutoff_frequency_hz=650)
        self.tilt_hi = pb.HighShelfFilter(cutoff_frequency_hz=650)
        self.mix = Ramp()
        self.level = Ramp()

    def _switched(self, key: str, fx: int) -> bool:
        """True (once) when a module's effect selection has just changed."""
        if self._active[key] != fx:
            self._active[key] = fx
            return True
        return False

    # -- persistence --------------------------------------------------
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["order"] = list(self.order)
        data["console_preset"] = self.preset_name
        return data

    def load_dict(self, data: dict) -> None:
        super().load_dict(data)
        order = data.get("order")
        if isinstance(order, list) and sorted(order) == [0, 1, 2, 3]:
            self.order = [int(i) for i in order]
        self.preset_name = data.get("console_preset", self.preset_name)

    def apply_preset(self, name: str) -> None:
        for p in self.PARAMS:
            if p.key != "level":
                self.values[p.key] = p.default
        for key, value in CONSOLE_PRESETS[name].items():
            self.set(key, value)
        self.preset_name = name

    def swap_modules(self, slot_a: int, slot_b: int) -> None:
        order = list(self.order)
        order[slot_a], order[slot_b] = order[slot_b], order[slot_a]
        self.order = order  # replaced atomically for the audio thread

    # -- processing ---------------------------------------------------
    def process(self, x):
        n = x.shape[1]
        stages = (self._character, self._movement, self._diffusion, self._texture)
        y = x
        for index in self.order:
            y = np.ascontiguousarray(stages[index](y), dtype=F32)
        tilt = self.values["tilt"]
        if abs(tilt) > 0.02:
            self.tilt_lo.gain_db = -7.0 * tilt
            self.tilt_hi.gain_db = 7.0 * tilt
            y = run(self.tilt_hi, run(self.tilt_lo, y, self.sr), self.sr)
        mix = self.mix.block(self.values["mix"], n)
        out = x * (1.0 - mix) + y * mix
        return out * self.level.block(db_to_lin(self.values["level"]), n)

    # CHARACTER ---------------------------------------------------------
    def _character(self, x):
        fx, a = int(self.values["char_fx"]), self.values["char_amt"]
        self._switched("char", fx)
        if fx == 0:
            return x
        if fx == 1:  # Drive: asymmetric soft clipping
            g = 1.0 + 4.0 * a + 30.0 * a * a
            return (np.tanh(g * x + 0.1 * a) - np.tanh(0.1 * a)) * (0.5 * g ** -0.35)
        if fx == 2:  # Sweeten: gentle compression, air and a little warmth
            self.sweet_comp.threshold_db = -14.0 - 16.0 * a
            self.sweet_shelf.gain_db = 7.0 * a
            y = run(self.sweet_shelf, run(self.sweet_comp, x, self.sr), self.sr)
            return np.tanh(y * (1.0 + 1.5 * a)) * 0.8
        if fx in (3, 4):  # Fuzz / Howl
            g = 10.0 + 140.0 * a * a + 30.0 * a
            y = run(self.fuzz_hp, x, self.sr)
            y = np.sign(y) * (1.0 - np.exp(-np.abs(g * y)))
            y = run(self.fuzz_lp, y, self.sr)
            if fx == 3:
                return y * 0.17
            # Howl: fuzz pushed through a screaming resonant band-pass
            self.howl_bp.cutoff_hz = 380.0 + 2400.0 * a
            self.howl_bp.resonance = 0.78 + 0.18 * a
            return (0.3 * y + 1.3 * run(self.howl_bp, y, self.sr)) * 0.12
        return self._swell(x, a)

    def _swell(self, x, a):
        """Auto volume swell: each new note fades in over 50 ms - 1.3 s."""
        n = x.shape[1]
        block_s = n / self.sr
        env = float(np.max(np.abs(x))) if n else 0.0
        self.sw_since += block_s
        self.sw_quiet = self.sw_quiet + block_s if env < 0.012 else 0.0
        fresh = self.sw_quiet > 0.04  # silence re-arms the swell
        attack = env > 0.03 and env > 2.4 * self.sw_slow and self.sw_since > 0.18
        if fresh or attack:
            self.sw_gain = 0.0
            if attack:
                self.sw_since = 0.0
        self.sw_slow += (env - self.sw_slow) * min(1.0, block_s / 0.12)
        inc = 1.0 / ((0.05 + 1.25 * a) * self.sr)
        g = np.minimum(1.0, self.sw_gain + inc * np.arange(1, n + 1))
        self.sw_gain = float(g[-1]) if n else self.sw_gain
        return x * (g * g).astype(F32)

    # MOVEMENT ----------------------------------------------------------
    def _movement(self, x):
        fx, a = int(self.values["move_fx"]), self.values["move_amt"]
        rate = self.values["rate"]
        if self._switched("move", fx):
            self.mod_line.clear()
            self.pitch.clear()
        if fx == 0:
            return x
        n = x.shape[1]
        sr = self.sr
        if fx == 1:  # Doubler: two slowly drifting slap voices, cross-panned
            ph = self.lfo.block(0.15 + 0.12 * rate, n)
            lfo = np.sin(2 * np.pi * (ph[None, :] + np.array([[0.0], [0.37]])))
            delay = np.array([[0.019], [0.028]]) * sr + 0.0016 * sr * lfo
            self.mod_line.write(x)
            wet = self.mod_line.read(delay, n)[::-1]
            return (x + wet * (1.1 * a)) / (1.0 + 0.45 * a)
        if fx == 2:  # Vibrato: pure pitch modulation
            depth = a * 0.0045 * sr / max(1.0, rate / 2.5)
            delay = 0.007 * sr + depth * self.lfo.sine(rate, n)
            self.mod_line.write(x)
            return self.mod_line.read(delay, n)
        if fx == 3:  # Phaser
            self.phaser.rate_hz = rate
            self.phaser.depth = 0.35 + 0.65 * a
            self.phaser.feedback = 0.15 + 0.6 * a
            return run(self.phaser, x, sr)
        if fx == 4:  # Tremolo
            s = self.lfo.sine(rate, n)
            return x * (1.0 - a * 0.5 * (1.0 + s)).astype(F32)
        # Pitch: RATE picks the interval, AMOUNT blends the shifted voice in
        t = self.param("rate").to_norm(rate)
        interval = PITCH_INTERVALS[min(len(PITCH_INTERVALS) - 1, int(t * len(PITCH_INTERVALS)))]
        wet = self.pitch.process(x, interval)
        return x * (1.0 - 0.6 * a) + wet * (1.3 * a)

    # DIFFUSION ---------------------------------------------------------
    def _diffusion(self, x):
        fx, a = int(self.values["diff_fx"]), self.values["diff_amt"]
        time_s = self.values["time"]
        if self._switched("diff", fx):
            self.echo.clear()
            self.reverser.clear()
            self.space.reset()
        if fx == 0:
            return x
        n = x.shape[1]
        wet_gain = min(1.0, 1.7 * a)
        if fx == 1:  # Cascade: clean multi-repeat echo
            wet = self.echo.process(x, time_s, 0.2 + 0.68 * a, damp_hz=7500)
            return x + wet * wet_gain
        if fx == 2:  # Reels: dark, saturated, wobbling tape echo
            wob = 0.0011 * self.sr * self.reel_lfo.sine(0.55, n)
            wet = self.echo.process(x, time_s, 0.25 + 0.65 * a, damp_hz=2300,
                                    wobble=wob, drive=True)
            return x + wet * wet_gain
        if fx == 3:  # Space: reverb, TIME sets the size
            t = self.param("time").to_norm(time_s)
            self.space.room_size = 0.25 + 0.73 * t
            self.space.damping = 0.35
            wet = run(self.space, x, self.sr)
            return x * (1.0 - 0.35 * a) + wet * (0.9 * a)
        if fx == 4:  # Collage: sound-on-sound layers that slowly decay
            wet = self.echo.process(x, time_s * 2.0, 0.88, damp_hz=5200,
                                    drive=True, send=0.25 + 0.6 * a)
            return x + wet * (0.35 + 0.6 * a)
        wet = self.reverser.process(x, time_s)  # Reverse
        return x * (1.0 - 0.6 * a) + wet * (1.5 * a)

    # TEXTURE -----------------------------------------------------------
    def _texture(self, x):
        fx, a = int(self.values["text_fx"]), self.values["text_amt"]
        if self._switched("text", fx):
            self.tape_line.clear()
            self.drop_gain[:] = 1.0
            self.drop_left[:] = 0.0
        if fx == 0:
            return x
        n = x.shape[1]
        sr = self.sr
        if fx == 1:  # Filter: resonant low-pass, darker as AMOUNT rises
            self.filt.cutoff_hz = 16000.0 * (220.0 / 16000.0) ** a
            self.filt.resonance = 0.25 + 0.4 * a
            return run(self.filt, x, sr)
        if fx == 2:  # Squash: slammed compressor
            self.squash.threshold_db = -12.0 - 34.0 * a
            self.squash.ratio = 4.0 + 16.0 * a
            y = run(self.squash, x, sr) * db_to_lin(26.0 * a)
            return np.tanh(y * 1.2) / 1.2
        if fx in (3, 4):  # Cassette / Broken share the tape transport
            broken = fx == 4
            self.drift += (self._rng.normal() - self.drift * 0.2) * 0.15
            wow = self.wow.sine(0.9 if broken else 0.55, n)
            flutter = self.flutter.sine(9.3 if broken else 6.7, n)
            depth = a * (2.6 if broken else 1.0)
            delay = (0.012 + depth * (0.0022 * wow + 0.00018 * flutter)
                     + 0.0006 * depth * np.tanh(self.drift)) * sr
            self.tape_line.write(x)
            y = self.tape_line.read(np.maximum(2.0, delay), n)
            y = np.tanh(y * (1.0 + 2.0 * a)) / (1.0 + 0.8 * a)
            self.tape_lp.cutoff_frequency_hz = 12000.0 * (2600.0 / 12000.0) ** a
            y = run(self.tape_lp, y, sr)
            y = y + self._rng.normal(0.0, 0.0012 * a, y.shape).astype(F32)  # hiss
            if broken:
                y = y * self._dropouts(n, a)
            return y
        # Interference: sample-rate crush, bit loss and radio crackle
        step = 1 + int(a * a * 38)
        g = self.sr_count + np.arange(n)
        idx = (g // step) * step - self.sr_count
        y = np.where(idx >= 0, x[:, np.maximum(idx, 0)], self.sr_last[:, None])
        self.sr_count = (self.sr_count + n) % step
        self.sr_last = y[:, -1].copy()
        q = 2.0 ** (12.0 - 8.5 * a)
        y = np.round(y * q) / q
        crackle = (self._rng.random(n) < 0.0009 * a) * self._rng.normal(0, 0.25 * a, n)
        return y + crackle.astype(F32)

    def _dropouts(self, n: int, a: float) -> np.ndarray:
        """Random per-channel level dips, like a chewed-up tape."""
        block_s = n / self.sr
        gains = np.empty((2, n), dtype=F32)
        for ch in range(2):
            if self.drop_left[ch] <= 0 and self._rng.random() < block_s * (0.4 + 2.2 * a):
                self.drop_left[ch] = self._rng.uniform(0.04, 0.32)
                self.drop_depth[ch] = self._rng.uniform(0.35, 1.0) * min(1.0, 0.3 + a)
            target = 1.0 - self.drop_depth[ch] if self.drop_left[ch] > 0 else 1.0
            self.drop_left[ch] -= block_s
            slew = min(1.0, block_s / 0.025)
            new = self.drop_gain[ch] + (target - self.drop_gain[ch]) * slew
            gains[ch] = np.linspace(self.drop_gain[ch], new, n + 1)[1:]
            self.drop_gain[ch] = new
        return gains

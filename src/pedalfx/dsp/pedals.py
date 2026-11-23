"""The stompboxes: compressor, boost, distortion, phaser, chorus, tremolo,
delay and reverb."""

from __future__ import annotations

import numpy as np
import pedalboard as pb

from .core import F32, DelayLine, Echo, Param, Pedal, Phasor, Ramp, db_to_lin, run


class Compressor(Pedal):
    TYPE = "compressor"
    NAME = "Squeeze"
    TAGLINE = "compressor"
    FINISH = "graphite"
    PARAMS = (
        Param("sustain", "Sustain", default=0.5),
        Param("attack", "Attack", 1.0, 60.0, 12.0, "ms", skew=2.0),
        Param("level", "Level", -12.0, 12.0, 0.0, "dB"),
    )

    def _build(self):
        self.comp = pb.Compressor(release_ms=160)
        self.gain = Ramp()

    def process(self, x):
        s = self.values["sustain"]
        self.comp.threshold_db = -8.0 - 32.0 * s
        self.comp.ratio = 2.0 + 8.0 * s
        self.comp.attack_ms = self.values["attack"]
        y = run(self.comp, x, self.sr)
        return y * self.gain.block(db_to_lin(9.0 * s + self.values["level"]), x.shape[1])


class Boost(Pedal):
    TYPE = "boost"
    NAME = "Lift"
    TAGLINE = "clean boost"
    FINISH = "gold"
    PARAMS = (
        Param("gain", "Gain", 0.0, 24.0, 6.0, "dB"),
        Param("bass", "Bass", -10.0, 10.0, 0.0, "dB"),
        Param("treble", "Treble", -10.0, 10.0, 0.0, "dB"),
    )

    def _build(self):
        self.low = pb.LowShelfFilter(cutoff_frequency_hz=180)
        self.high = pb.HighShelfFilter(cutoff_frequency_hz=3200)
        self.gain = Ramp()

    def process(self, x):
        self.low.gain_db = self.values["bass"]
        self.high.gain_db = self.values["treble"]
        y = run(self.high, run(self.low, x, self.sr), self.sr)
        return y * self.gain.block(db_to_lin(self.values["gain"]), x.shape[1])


class Distortion(Pedal):
    TYPE = "distortion"
    NAME = "Scorch"
    TAGLINE = "overdrive / distortion / fuzz"
    FINISH = "tangerine"
    PARAMS = (
        Param("drive", "Drive", default=0.5),
        Param("tone", "Tone", default=0.55),
        Param("level", "Level", default=0.5),
        Param("mode", "Mode", default=0, choices=("OD", "Dist", "Fuzz")),
    )

    def _build(self):
        self.hp = pb.HighpassFilter(cutoff_frequency_hz=140)
        self.lp = pb.LowpassFilter(cutoff_frequency_hz=4000)
        self.pre = Ramp()
        self.post = Ramp()

    def process(self, x):
        n = x.shape[1]
        drive, mode = self.values["drive"], int(self.values["mode"])
        self.hp.cutoff_frequency_hz = (140.0, 90.0, 45.0)[mode]
        x = run(self.hp, x, self.sr)
        if mode == 0:  # asymmetric soft clip: tube-ish overdrive
            g = self.pre.block(db_to_lin(4.0 + 30.0 * drive), n)
            y = np.tanh(g * x + 0.12) - np.tanh(0.12)
        elif mode == 1:  # harder two-stage clip
            g = self.pre.block(db_to_lin(14.0 + 34.0 * drive), n)
            y = np.tanh(g * x)
            y = np.tanh(2.2 * y) * 0.92
        else:  # squared-off, slightly gated fuzz
            g = self.pre.block(db_to_lin(24.0 + 36.0 * drive), n)
            y = np.sign(x) * (1.0 - np.exp(-np.abs(g * x))) * 0.8
        self.lp.cutoff_frequency_hz = 700.0 * (12000.0 / 700.0) ** self.values["tone"]
        y = run(self.lp, y, self.sr)
        trim = (1.0, 0.5, 0.5)[mode]
        return y * self.post.block(trim * self.values["level"] ** 2, n)


class Phaser(Pedal):
    TYPE = "phaser"
    NAME = "Orbit"
    TAGLINE = "phaser"
    FINISH = "violet"
    PARAMS = (
        Param("rate", "Rate", 0.05, 8.0, 0.5, "Hz", skew=2.5),
        Param("depth", "Depth", default=0.7),
        Param("feedback", "Regen", 0.0, 0.9, 0.35),
        Param("mix", "Mix", default=0.5),
    )

    def _build(self):
        self.fx = pb.Phaser(centre_frequency_hz=1100)

    def process(self, x):
        self.fx.rate_hz = self.values["rate"]
        self.fx.depth = self.values["depth"]
        self.fx.feedback = self.values["feedback"]
        self.fx.mix = self.values["mix"]
        return run(self.fx, x, self.sr)


class Chorus(Pedal):
    TYPE = "chorus"
    NAME = "Tidal"
    TAGLINE = "stereo chorus"
    FINISH = "sky"
    PARAMS = (
        Param("rate", "Rate", 0.1, 6.0, 0.8, "Hz", skew=2.0),
        Param("depth", "Depth", default=0.5),
        Param("mix", "Mix", default=0.5),
    )

    def _build(self):
        self.line = DelayLine(int(self.sr * 0.06))
        self.lfo = Phasor(self.sr)
        self.mix = Ramp()

    def process(self, x):
        n = x.shape[1]
        ph = self.lfo.block(self.values["rate"], n)
        depth = self.values["depth"] * 0.0035 * self.sr
        base = 0.011 * self.sr
        # left and right voices are a quarter cycle apart for stereo width
        delay = base + depth * np.sin(2 * np.pi * (ph[None, :] + np.array([[0.0], [0.25]])))
        self.line.write(x)
        wet = self.line.read(delay, n)
        mix = self.mix.block(self.values["mix"], n)
        return x * (1.0 - mix) + wet * mix


class Tremolo(Pedal):
    TYPE = "tremolo"
    NAME = "Pulse"
    TAGLINE = "tremolo"
    FINISH = "mint"
    PARAMS = (
        Param("rate", "Rate", 0.5, 15.0, 5.0, "Hz", skew=2.0),
        Param("depth", "Depth", default=0.6),
        Param("shape", "Shape", default=0, choices=("Smooth", "Chop", "Pan")),
    )

    def _build(self):
        self.lfo = Phasor(self.sr)

    def process(self, x):
        n = x.shape[1]
        s = self.lfo.sine(self.values["rate"], n)
        shape = int(self.values["shape"])
        if shape == 1:
            s = np.tanh(5.0 * s) / np.tanh(5.0)
        depth = self.values["depth"]
        if shape == 2:  # auto-pan: the two channels move in opposition
            g = 1.0 - depth * 0.5 * (1.0 + np.stack([s, -s]))
        else:
            g = 1.0 - depth * 0.5 * (1.0 + s)
        return x * g.astype(F32)


class Delay(Pedal):
    TYPE = "delay"
    NAME = "Echoplane"
    TAGLINE = "digital / tape / ping-pong delay"
    FINISH = "cream"
    PARAMS = (
        Param("time", "Time", 30.0, 1200.0, 380.0, "ms", skew=2.0),
        Param("feedback", "Repeats", 0.0, 0.95, 0.35),
        Param("mix", "Mix", default=0.3),
        Param("tone", "Tone", default=0.6),
        Param("mode", "Mode", default=0, choices=("Digital", "Tape", "Ping")),
    )

    def _build(self):
        self.echo = Echo(self.sr, max_seconds=2.0)
        self.wow = Phasor(self.sr)
        self.mix = Ramp()
        self._mode = int(self.values["mode"])

    def process(self, x):
        n = x.shape[1]
        mode = int(self.values["mode"])
        if mode != self._mode:
            self.echo.clear()
            self._mode = mode
        tone = self.values["tone"]
        damp = 900.0 * (16000.0 / 900.0) ** tone
        time_s = self.values["time"] / 1000.0
        fb = self.values["feedback"]
        if mode == 1:  # tape: darker, saturating repeats with slow wow
            wob = 0.0009 * self.sr * self.wow.sine(0.7, n)
            wet = self.echo.process(x, time_s, fb, damp_hz=damp * 0.45,
                                    wobble=wob, drive=True)
        elif mode == 2:  # ping-pong: mono in on the left, repeats cross over
            mono = 0.5 * (x[0] + x[1])
            src = np.stack([mono, np.zeros_like(mono)])
            wet = self.echo.process(src, time_s, fb, damp_hz=damp, pingpong=True)
        else:
            wet = self.echo.process(x, time_s, fb, damp_hz=damp if tone < 0.97 else None)
        return x + wet * self.mix.block(self.values["mix"] * 1.4, n)


class Reverb(Pedal):
    TYPE = "reverb"
    NAME = "Cathedral"
    TAGLINE = "reverb"
    FINISH = "ocean"
    PARAMS = (
        Param("size", "Decay", default=0.55),
        Param("tone", "Tone", default=0.5),
        Param("mix", "Mix", default=0.3),
        Param("predelay", "Pre-Dly", 0.0, 150.0, 10.0, "ms", skew=2.0),
    )

    def _build(self):
        self.fx = pb.Reverb(wet_level=1.0, dry_level=0.0, width=1.0)
        self.pre = DelayLine(int(self.sr * 0.2))
        self.mix = Ramp()

    def process(self, x):
        n = x.shape[1]
        self.fx.room_size = 0.15 + 0.84 * self.values["size"]
        self.fx.damping = 1.0 - self.values["tone"]
        self.pre.write(x)
        send = self.pre.read(1.0 + self.values["predelay"] * 0.001 * self.sr, n)
        wet = run(self.fx, send, self.sr)
        mix = self.mix.block(self.values["mix"], n)
        return x * (1.0 - 0.5 * mix) + wet * mix

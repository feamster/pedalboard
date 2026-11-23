"""Rerun - a two-track looper with a built-in drum machine.

The workflow follows the Boss RC-500: one switch cycles record -> overdub ->
play, a double tap stops, undo/redo removes the last overdub, recording can
start on the first note or after a count-in, loops can be a fixed number of
measures, and a rhythm section follows the loop.

Threading: the UI never touches loop state. It queues named commands with
``command()``; the audio thread runs them at the start of the next block.
Blocks are split at every boundary (loop wrap, end of a fixed-length
recording, end of the count-in), so loop lengths are sample-exact and do not
depend on the buffer size.
"""

from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

from .core import F32, Param, Pedal, Ramp
from .drums import KITS, STYLE_NAMES, STYLES, VELOCITY, count_in_style, make_kit

EMPTY, ARMED, COUNT, REC, PLAY, DUB, STOP = "empty", "armed", "count", "rec", "play", "dub", "stop"
MEASURE_CHOICES = ("Free", "1", "2", "3", "4", "6", "8", "12", "16")
COMMANDS = ("press", "hold", "stop", "stopall", "undo", "clear", "track", "drums", "fill", "next")
ARM_THRESHOLD = 0.02     # input peak that starts an armed recording
DOUBLE_TAP = 0.4         # seconds between presses that count as "stop"


class Looper(Pedal):
    TYPE = "looper"
    NAME = "Rerun"
    TAGLINE = "2-track looper + drum machine"
    FINISH = "crimson"
    MAX_SECONDS = 180.0
    PARAMS = (
        Param("tempo", "Tempo", 40.0, 240.0, 96.0, "bpm"),
        Param("drum_level", "Drums", default=0.6),
        Param("level1", "Track 1", default=0.8),
        Param("level2", "Track 2", default=0.8),
        Param("measures", "Measures", default=4, choices=MEASURE_CHOICES),
        Param("start", "Rec Start", default=1, choices=("Now", "Auto", "Count-in")),
        Param("after", "After Rec", default=0, choices=("Overdub", "Play")),
        Param("fill", "Auto Fill", default=1, choices=("Off", "On")),
        Param("style", "Style", default=0, choices=STYLE_NAMES),
        Param("kit", "Kit", default=0, choices=KITS),
        Param("drums", "Rhythm", default=1, choices=("Off", "On")),
        Param("stop", "Stop", default=0, choices=("Now", "Loop End")),
    )

    def __init__(self, sr: float = 48000.0):
        self._cmds: deque = deque()
        self.ui_dirty = False   # set when the audio thread changes a parameter value
        self._alive = 0.0
        super().__init__(sr)

    # -- state ----------------------------------------------------------
    def _build(self):
        sr = int(self.sr)
        self.state = EMPTY
        self.sel = 0                       # selected track
        self.buf = [None, None]            # per track: float32 (2, length)
        self.has = [False, False]
        self.playing = [False, False]      # a track can be stopped while the other keeps going
        self.pending = [False, False]      # ... or be waiting to stop at the end of the loop
        self.gain = [Ramp(0.0), Ramp(0.0)]
        self.undo_buf = [None, None]       # the track as it was before its last overdub
        self.undo_has = [False, False]
        self.redo = [False, False]         # True when "undo" would re-apply the layer
        self._prev_undo = None
        self.length = 0                    # loop length in samples; 0 = no loop yet
        self.loop_bars = 0
        self.pos = 0
        self.rec_end = None                # sample at which the recording closes itself
        self.cap = 0
        self.dub = Ramp(0.0)               # overdub input gain, ramped to avoid clicks
        self.dub_track = 0
        self.dub_started = 0.0
        self.last_press = -10.0
        # transport / drums
        self.quarter = 60.0 / round(self.values["tempo"]) * sr   # samples per quarter note
        self.transport = False
        self.jam = False                   # drums running on their own, no loop driving them
        self.clock = 0
        self.count_end = 0
        self.part = "A"
        self.fill_bar = None
        self.fill_from = 0
        self.switch = False
        self.cur_bar = 0
        self.cur_step = 0
        self.kits = {name: make_kit(name, sr) for name in KITS}
        size = 1 << int(math.ceil(math.log2(2.0 * sr)))
        self.ring = np.zeros(size, dtype=F32)   # mix-ahead buffer the drum hits are added into
        self.mask = size - 1
        self.rpos = 0
        self._ar = np.arange(size)
        self.aux = None                    # drum audio for the engine to add after the chain

    @property
    def style(self):
        return STYLES[int(self.values["style"])]

    @property
    def measure(self) -> float:
        """Measure length in samples."""
        return self.style.quarters * self.quarter

    @property
    def alive(self) -> bool:
        """True while the audio engine is actually calling us."""
        return time.monotonic() - self._alive < 0.5

    def command(self, name: str) -> bool:
        """Queue a control action (see ``COMMANDS``). Ignored if audio is off."""
        if name not in COMMANDS or not self.alive:
            return False
        self._cmds.append(name)
        return True

    def status(self) -> dict:
        """Snapshot for the display (read from the UI thread)."""
        style, measure, state = self.style, self.measure, self.state
        setting = int(self.values["measures"])
        bars = self.loop_bars if self.length else (int(MEASURE_CHOICES[setting]) if setting else 0)
        bar = progress = beat = None
        if state in (REC, PLAY, DUB):
            bar = int(self.pos // measure) + 1
            total = self.length or self.rec_end
            progress = self.pos / total if total else None
        if self.transport:
            beat = self.cur_step * style.beats // style.steps
        return {
            "alive": self.alive, "state": state, "track": self.sel, "has": tuple(self.has),
            "playing": tuple(self.playing), "pending": tuple(self.pending),
            "bar": bar, "bars": bars, "beat": beat, "beats": style.beats, "progress": progress,
            "tempo": 60.0 * self.sr / self.quarter, "style": style.name, "part": self.part,
            "kit": KITS[int(self.values["kit"])], "drums": int(self.values["drums"]) == 1,
            "can_undo": self.undo_buf[self.sel] is not None, "redo": self.redo[self.sel],
            "seconds": self.length / self.sr,
        }

    # -- audio ----------------------------------------------------------
    def process(self, x):
        n = x.shape[1]
        self._alive = time.monotonic()
        while self._cmds:
            self._do(self._cmds.popleft())
        self._sync_tempo()
        if self.state == ARMED and n and float(np.max(np.abs(x))) > ARM_THRESHOLD:
            self._begin_record()
        out = np.empty((2, n), dtype=F32)
        drums = np.empty(n, dtype=F32)
        i = 0
        while i < n:
            m = self._segment_len(n - i)
            out[:, i:i + m] = self._run(x[:, i:i + m], m)
            drums[i:i + m] = self._drums(m)
            i += m
            self._boundary()
        self.aux = drums * F32(self.values["drum_level"] * 0.8)
        return out

    def _segment_len(self, remaining: int) -> int:
        """Samples until the next event that changes what we are doing."""
        state = self.state
        if state == COUNT:
            limit = self.count_end - self.clock
        elif state == REC:
            limit = (self.rec_end if self.rec_end is not None else self.cap) - self.pos
        elif state in (PLAY, DUB):
            limit = self.length - self.pos
        else:
            return remaining
        return max(1, min(remaining, int(limit)))

    def _run(self, seg, m: int):
        state = self.state
        a, b = self.pos, self.pos + m
        if state == REC:
            self.buf[self.sel][:, a:b] = seg
            self.pos = b
            return seg
        if state in (PLAY, DUB):
            y = seg
            for t in (0, 1):
                target = 1.0 if self.playing[t] else 0.0
                if self.has[t] and (target or self.gain[t].value > 0):
                    level = self.gain[t].block(target, m) * F32(self.values[f"level{t + 1}"] / 0.8)
                    y = y + self.buf[t][:, a:b] * level
            target = 1.0 if state == DUB else 0.0
            if target or self.dub.value > 0:
                self.buf[self.dub_track][:, a:b] += seg * self.dub.block(target, m)
            self.pos = b
            return y
        return seg

    def _boundary(self) -> None:
        state = self.state
        if state == COUNT:
            if self.clock >= self.count_end:
                self._begin_record()
        elif state == REC:
            end = self.rec_end if self.rec_end is not None else self.cap
            if self.pos >= end:
                self._finalize(end)
        elif state in (PLAY, DUB) and self.pos >= self.length:
            self.pos = 0
            if any(self.pending):   # tracks that were asked to stop at the end of the loop
                for t in (0, 1):
                    if self.pending[t]:
                        self.playing[t] = self.pending[t] = False
                        self.gain[t].value = 0.0
                if not any(self.playing):
                    self._stop()

    # -- commands (audio thread) ----------------------------------------
    def _do(self, name: str) -> None:
        getattr(self, f"_cmd_{name}")()

    def _cmd_press(self) -> None:
        now = time.monotonic()
        double = now - self.last_press < DOUBLE_TAP
        self.last_press = now
        state = self.state
        if double and state in (REC, PLAY, DUB):
            self.last_press = -10.0
            return self._stop_track(recent=True)
        if state == EMPTY:
            start = int(self.values["start"])
            if start == 1:
                self.state = ARMED
            elif start == 2:
                self._begin_count()
            else:
                self._begin_record()
        elif state in (ARMED, COUNT):
            self.state = EMPTY
            if not self.jam:
                self.transport = False
        elif state == STOP:
            self.pos = 0
            self.jam = False
            self.playing = list(self.has)
            self.gain[0].value = self.gain[1].value = 1.0   # takes already fade in at the seam
            self._start_transport()
            self.state = PLAY
        elif state == REC:
            self._end_record()
        elif state == PLAY:
            t = self.sel
            if self.pending[t]:
                self.pending[t] = False        # changed your mind: keep it playing
            elif self.has[t] and not self.playing[t]:
                self.playing[t] = True         # bring a stopped track back in, in sync
            else:
                self._begin_dub()
        elif state == DUB:
            self.state = PLAY   # the overdub gain ramps out over the next segment

    def _cmd_hold(self) -> None:
        """Main switch held down: undo / redo (the press itself is taken back)."""
        if self.state == DUB and time.monotonic() - self.dub_started < 2.0:
            self._cancel_dub()
        self._cmd_undo()

    def _cmd_stop(self) -> None:
        self._stop_track()

    def _cmd_stopall(self) -> None:
        self._stop()

    def _stop_track(self, recent: bool = False) -> None:
        """Stop the selected track - now, or at the end of the loop (the Stop setting).

        Asking again while it is waiting for the loop end stops it at once.
        The looper as a whole stops when no track is left playing.
        """
        if self.state not in (PLAY, DUB):
            return self._stop(recent)
        t = self.sel
        if self.state == DUB:
            if recent and time.monotonic() - self.dub_started < 0.6:
                self._cancel_dub()   # the first tap of a double tap started this overdub
            else:
                self.state = PLAY
        if not self.playing[t]:
            return
        if int(self.values["stop"]) == 1 and not self.pending[t]:
            self.pending[t] = True
            return
        self.playing[t] = self.pending[t] = False
        if not any(self.playing):
            self._stop()

    def _cmd_undo(self) -> None:
        t = self.sel
        if self.state == DUB and self.dub_track == t:
            self.state = PLAY
            self.dub.value = 0.0
        if self.undo_buf[t] is None or self.state not in (PLAY, STOP):
            return
        self.buf[t], self.undo_buf[t] = self.undo_buf[t], self.buf[t]
        self.has[t], self.undo_has[t] = self.undo_has[t], self.has[t]
        self.redo[t] = not self.redo[t]

    def _cmd_clear(self) -> None:
        t = self.sel
        if self.state in (REC, ARMED, COUNT):
            return self._stop()
        if self.state == DUB and self.dub_track == t:
            self.state = PLAY
            self.dub.value = 0.0
        self.buf[t], self.undo_buf[t] = None, None
        self.has[t] = self.undo_has[t] = self.redo[t] = False
        self.playing[t] = self.pending[t] = False
        if any(self.has) and not any(self.playing) and self.state == PLAY:
            self._stop()             # the only track still playing was the one just cleared
        if not any(self.has):
            self.length = self.loop_bars = self.pos = 0
            self.state = EMPTY
            self.transport = self.jam = False
            self.ring[:] = 0.0

    def _cmd_track(self) -> None:
        if self.state == DUB:
            self.state = PLAY
        self.sel ^= 1

    def _cmd_drums(self) -> None:
        on = 1 - int(self.values["drums"])
        self.values["drums"] = on
        self.ui_dirty = True
        if self.state in (EMPTY, STOP, ARMED):   # nothing playing: drums run on their own
            if on:
                self.jam = True
                self._start_transport()
            else:
                self.jam = self.transport = False
                self.ring[:] = 0.0

    def _cmd_fill(self) -> None:
        if self.transport:
            self.fill_bar, self.fill_from = self.cur_bar, self.cur_step + 1

    def _cmd_next(self) -> None:
        """Fill out the rest of this measure, then switch between parts A and B."""
        if self.transport:
            self._cmd_fill()
            self.switch = True

    # -- recording ------------------------------------------------------
    def _start_transport(self) -> None:
        self.transport = True
        self.clock = 0
        self.cur_bar = self.cur_step = 0
        self.fill_bar = None
        self.switch = False

    def _begin_count(self) -> None:
        measure = self.measure
        if self.jam and self.transport:   # drums already going: come in on the next bar line
            self.count_end = int(round((math.floor(self.clock / measure) + 1) * measure))
        else:
            self._start_transport()
            self.count_end = int(round(measure))
        self.state = COUNT

    def _begin_record(self) -> None:
        if self.length:   # a loop exists: a new track is just an overdub onto silence
            self.state = PLAY
            return self._begin_dub()
        setting = int(self.values["measures"])
        bars = int(MEASURE_CHOICES[setting]) if setting else 0
        self.rec_end = int(round(bars * self.measure)) if bars else None
        self.cap = self.rec_end or int(self.MAX_SECONDS * self.sr)
        self.buf[self.sel] = np.zeros((2, self.cap), dtype=F32)
        self.pos = 0
        if not self.jam:
            self._start_transport()
        self.state = REC

    def _end_record(self) -> None:
        """Main switch pressed while recording."""
        measure = self.measure
        if self.rec_end is not None or int(self.values["drums"]) == 1:
            bars = self.pos / measure
            if self.rec_end is not None:      # fixed length: close at the end of this measure
                bars = max(1, math.ceil(bars - 1e-6))
            else:                             # free, but with drums: snap to the nearest measure
                bars = max(1, round(bars))
            target = int(round(bars * measure))
            if target > self.pos:
                self.rec_end = min(target, self.cap)
            else:
                self._finalize(target)
        elif self.pos >= int(0.2 * self.sr):
            self._derive_tempo(self.pos)
            self._finalize(self.pos)

    def _derive_tempo(self, length: int) -> None:
        """A free-form loop defines the tempo: call it 1, 2, 4... measures."""
        quarters = self.style.quarters
        seconds = length / self.sr
        bars = 1
        for candidate in (1, 2, 4, 8, 16, 32, 64):
            if 70.0 <= candidate * quarters * 60.0 / seconds < 140.0:
                bars = candidate
                break
        self.quarter = length / (bars * quarters)
        self.values["tempo"] = self.param("tempo").clamp(60.0 * self.sr / self.quarter)
        self.clock = 0
        self.ui_dirty = True

    def _finalize(self, length: int) -> None:
        t = self.sel
        carry = max(0, self.pos - length)
        buf = self.buf[t]
        if buf.shape[1] != length:
            buf = np.ascontiguousarray(buf[:, :length])
        fade = max(1, min(length // 4, int(0.003 * self.sr)))
        ramp = np.linspace(0.0, 1.0, fade, dtype=F32)
        buf[:, :fade] *= ramp
        buf[:, -fade:] *= ramp[::-1]
        self.buf[t], self.has[t] = buf, True
        self.playing[t], self.gain[t].value = True, 1.0
        self.undo_buf[t], self.redo[t] = None, False
        self.length = length
        self.loop_bars = max(1, round(length / self.measure))
        self.rec_end = None
        self.pos = carry % length
        self.state = PLAY
        if int(self.values["after"]) == 0:
            self._begin_dub()

    def _begin_dub(self) -> None:
        t = self.sel
        if self.buf[t] is None:
            self.buf[t] = np.zeros((2, self.length), dtype=F32)
        self._prev_undo = (self.undo_buf[t], self.undo_has[t], self.redo[t])
        self.undo_buf[t], self.undo_has[t], self.redo[t] = self.buf[t].copy(), self.has[t], False
        self.has[t] = self.playing[t] = True
        self.pending[t] = False
        if self.dub_track != t:
            self.dub.value = 0.0
        self.dub_track = t
        self.dub_started = time.monotonic()
        self.state = DUB

    def _cancel_dub(self) -> None:
        """Throw away the overdub in progress as if it had never started."""
        t = self.dub_track
        self.buf[t], self.has[t] = self.undo_buf[t], self.undo_has[t]
        self.undo_buf[t], self.undo_has[t], self.redo[t] = self._prev_undo
        self.dub.value = 0.0
        self.state = PLAY

    def _stop(self, recent: bool = False) -> None:
        state = self.state
        if state == REC:
            self.buf[self.sel] = None
            self.rec_end = None
        elif state == DUB and recent and time.monotonic() - self.dub_started < 0.6:
            self._cancel_dub()   # the first tap of a double tap started this overdub
        self.state = STOP if self.length else EMPTY
        self.playing, self.pending = [False, False], [False, False]
        self.gain[0].value = self.gain[1].value = 0.0
        self.dub.value = 0.0
        self.pos = 0
        self.transport = self.jam = False
        self.ring[:] = 0.0

    def _sync_tempo(self) -> None:
        """Follow the tempo knob - until a loop exists, which then owns the tempo."""
        if self.length or self.state in (REC, COUNT):
            return
        quarter = 60.0 / round(self.values["tempo"]) * self.sr
        if quarter != self.quarter:
            if self.transport:
                self.clock = int(self.clock * quarter / self.quarter)
            self.quarter = quarter

    # -- drum machine ---------------------------------------------------
    def _drums(self, m: int) -> np.ndarray:
        if self.transport:
            counting = self.state == COUNT and not self.jam
            style = count_in_style(self.style) if counting else self.style
            audible = counting or int(self.values["drums"]) == 1
            step_len = style.quarters * self.quarter / style.steps
            c = self.clock
            k = int(math.ceil(c / step_len - 1e-9))
            while True:
                t = int(round(k * step_len))
                if t < c:
                    k += 1
                    continue
                if t >= c + m:
                    break
                self._step(style, k, t - c, audible, counting)
                k += 1
            self.clock = c + m
        idx = (self.rpos + self._ar[:m]) & self.mask
        out = self.ring[idx]
        self.ring[idx] = 0.0
        self.rpos = (self.rpos + m) & self.mask
        return out

    def _step(self, style, k: int, offset: int, audible: bool, counting: bool) -> None:
        s, bar = k % style.steps, k // style.steps
        self.cur_bar, self.cur_step = bar, s
        crash = False
        if s == 0 and not counting:
            if self.switch and self.fill_bar is not None and bar > self.fill_bar:
                self.part = "B" if self.part == "A" else "A"
                self.switch = False
                crash = True
            if int(self.values["fill"]) == 1:
                bars = self.loop_bars
                period = bars * math.ceil(4 / bars) if bars else 4   # at the end of the loop
                if (bar + 1) % period == 0:
                    self.fill_bar, self.fill_from = bar, 0
        if not audible:
            return
        filling = self.fill_bar == bar and s >= self.fill_from and not counting
        kit = self.kits[KITS[int(self.values["kit"])]]
        for inst, row in style.parts["fill" if filling else self.part].items():
            if row[s] != ".":
                self._hit(kit[inst], offset, VELOCITY[row[s]])
        if crash:
            self._hit(kit["C"], offset, 0.8)

    def _hit(self, wave: np.ndarray, offset: int, velocity: float) -> None:
        idx = (self.rpos + offset + self._ar[:len(wave)]) & self.mask
        self.ring[idx] += wave * F32(velocity)

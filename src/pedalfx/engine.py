"""Real-time audio engine: input -> pedal chain -> limiter -> output."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .dsp.core import F32, Ramp, db_to_lin
from .sources import demo_riff, load_audio_file

try:  # the engine still works offline (tests, rendering) without PortAudio
    import sounddevice as sd
except Exception:  # pragma: no cover - depends on the machine
    sd = None

SOURCES = ("live", "demo", "file")
SAMPLE_RATES = (44100, 48000, 96000)
BLOCK_SIZES = (64, 128, 256, 512, 1024)


@dataclass
class AudioConfig:
    input_device: str | None = None   # None -> system default
    output_device: str | None = None
    input_channel: int = 1            # 1-based hardware input the guitar is on
    sample_rate: int = 0              # 0 -> whatever rate the device is running at
    block_size: int = 128

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AudioConfig:
        cfg = cls()
        for key, value in (data or {}).items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        if cfg.sample_rate not in (0, *SAMPLE_RATES):
            cfg.sample_rate = 0
        if cfg.block_size not in BLOCK_SIZES:
            cfg.block_size = 128
        cfg.input_channel = max(1, int(cfg.input_channel or 1))
        return cfg


def soft_clip(y: np.ndarray, knee: float = 0.7) -> np.ndarray:
    """Output safety: transparent below the knee, rounds off into +/-1 above."""
    mag = np.abs(y)
    if not mag.size or float(mag.max()) <= knee:
        return y
    over = knee + (1.0 - knee) * np.tanh((mag - knee) / (1.0 - knee))
    return np.where(mag > knee, np.sign(y) * over, y).astype(F32)


def list_devices() -> tuple[list[dict], list[dict]]:
    """(inputs, outputs) as dicts with name / channels / default flag."""
    if sd is None:
        return [], []
    try:
        devices = sd.query_devices()
        default_in, default_out = sd.default.device
    except Exception:
        return [], []
    ins, outs = [], []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            ins.append({"name": dev["name"], "channels": dev["max_input_channels"],
                        "default": i == default_in})
        if dev["max_output_channels"] > 0:
            outs.append({"name": dev["name"], "channels": dev["max_output_channels"],
                         "default": i == default_out})
    return ins, outs


def _device_index(name: str | None, want_input: bool) -> int | None:
    """Resolve a saved device name; None means 'use the system default'."""
    if not name or sd is None:
        return None
    key = "max_input_channels" if want_input else "max_output_channels"
    for i, dev in enumerate(sd.query_devices()):
        if dev["name"] == name and dev[key] > 0:
            return i
    return None


class AudioEngine:
    def __init__(self, sample_rate: int = 48000):
        self.sr = int(sample_rate)
        self.config = AudioConfig()
        self.chain: tuple = ()         # replaced atomically; read by the audio thread
        self.source = "demo"
        self.file_path: str | None = None
        self.input_gain_db = 0.0
        self.master_db = 0.0
        self.in_peak = 0.0             # block peaks; the UI reads and clears them
        self.out_peak = 0.0
        self.last_error: str | None = None
        self.xruns = 0
        self._stream = None
        self._loop = np.zeros(1, dtype=F32)
        self._loop_pos = 0
        self._in_gain = Ramp()
        self._out_gain = Ramp()
        self._was_enabled: dict[int, bool] = {}

    # -- chain --------------------------------------------------------
    def set_chain(self, pedals) -> None:
        pedals = tuple(pedals)
        for pedal in pedals:
            pedal.set_sample_rate(self.sr)
        self.chain = pedals

    def set_sample_rate(self, sr: int) -> None:
        self.sr = int(sr)
        for pedal in self.chain:
            pedal.set_sample_rate(self.sr)

    # -- processing (also used offline) -----------------------------
    def process_block(self, x: np.ndarray) -> np.ndarray:
        """Process one stereo block shaped ``(2, n)``."""
        n = x.shape[1]
        y = np.ascontiguousarray(x, dtype=F32) * self._in_gain.block(db_to_lin(self.input_gain_db), n)
        self.in_peak = max(self.in_peak, float(np.max(np.abs(y))) if n else 0.0)
        aux = None   # audio a pedal sends straight to the output (the looper's drums)
        for pedal in self.chain:
            was = self._was_enabled.get(id(pedal), pedal.enabled)
            now = pedal.enabled
            self._was_enabled[id(pedal)] = now
            if not now and not was:
                continue
            wet = np.ascontiguousarray(pedal.process(y), dtype=F32)
            side = getattr(pedal, "aux", None)
            if side is not None:
                pedal.aux = None
                if now:
                    aux = side if aux is None else aux + side
            if now and was:
                y = wet
            else:  # footswitch just changed: crossfade over this block, no click
                fade = np.linspace(0.0, 1.0, n, dtype=F32)
                y = y + (wet - y) * (fade if now else 1.0 - fade)
        if aux is not None:
            y = y + aux
        y = y * self._out_gain.block(db_to_lin(self.master_db), n)
        y = soft_clip(np.nan_to_num(y, copy=False))
        self.out_peak = max(self.out_peak, float(np.max(np.abs(y))) if n else 0.0)
        return y

    def render(self, mono: np.ndarray, block: int = 256) -> np.ndarray:
        """Offline: run a mono signal through the chain, return stereo."""
        out = np.zeros((2, len(mono)), dtype=F32)
        for s in range(0, len(mono), block):
            seg = mono[s:s + block]
            out[:, s:s + len(seg)] = self.process_block(np.stack([seg, seg]))
        return out

    # -- sources ------------------------------------------------------
    def _prepare_source(self) -> None:
        if self.source == "demo":
            self._loop = demo_riff(self.sr)
        elif self.source == "file":
            if not self.file_path:
                raise RuntimeError("No audio file selected")
            self._loop = load_audio_file(self.file_path, self.sr)
        self._loop_pos = 0

    def _next_loop(self, n: int) -> np.ndarray:
        idx = (self._loop_pos + np.arange(n)) % len(self._loop)
        self._loop_pos = int((self._loop_pos + n) % len(self._loop))
        return self._loop[idx]

    # -- stream -------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def cpu_load(self) -> float:
        try:
            return float(self._stream.cpu_load) if self._stream else 0.0
        except Exception:
            return 0.0

    @property
    def latency_ms(self) -> float:
        if not self._stream:
            return 0.0
        lat = self._stream.latency
        total = sum(lat) if isinstance(lat, (tuple, list)) else lat
        return 1000.0 * float(total)

    def start(self, config: AudioConfig | None = None) -> None:
        if sd is None:
            raise RuntimeError("sounddevice / PortAudio is not available")
        self.stop()
        if config is not None:
            self.config = config
        cfg = self.config
        self.last_error = None
        self.xruns = 0
        live = self.source == "live"
        out_dev = _device_index(cfg.output_device, want_input=False)
        in_dev = _device_index(cfg.input_device, want_input=True) if live else None
        # Running at the device's own rate avoids a resampler (and ~40 ms of
        # extra input latency on USB interfaces).
        native = sd.query_devices(in_dev if live else out_dev, "input" if live else "output")
        self.set_sample_rate(cfg.sample_rate or int(native["default_samplerate"]))
        self._prepare_source()
        # "low" latency asks for the device default, which is far from low on
        # many interfaces; ask for one buffer's worth instead.
        common = {"samplerate": self.sr, "blocksize": cfg.block_size, "dtype": "float32",
                  "latency": cfg.block_size / self.sr}
        if live:
            info = sd.query_devices(in_dev, "input")
            channel = min(cfg.input_channel, int(info["max_input_channels"]))
            if channel < 1:
                raise RuntimeError(f"'{info['name']}' has no input channels")
            self._live_channel = channel - 1
            stream = sd.Stream(device=(in_dev, out_dev), channels=(channel, 2),
                               callback=self._duplex_callback, **common)
        else:
            stream = sd.OutputStream(device=out_dev, channels=2,
                                     callback=self._output_callback, **common)
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.in_peak = self.out_peak = 0.0

    def _emit(self, mono: np.ndarray, outdata) -> None:
        try:
            y = self.process_block(np.stack([mono, mono]))
            outdata[:, 0] = y[0]
            outdata[:, 1] = y[1]
        except Exception as exc:  # never let an exception kill the stream
            self.last_error = f"{type(exc).__name__}: {exc}"
            outdata[:] = 0.0

    def _duplex_callback(self, indata, outdata, frames, time, status) -> None:
        if status:
            self.xruns += 1
        self._emit(indata[:, self._live_channel], outdata)

    def _output_callback(self, outdata, frames, time, status) -> None:
        if status:
            self.xruns += 1
        self._emit(self._next_loop(frames), outdata)

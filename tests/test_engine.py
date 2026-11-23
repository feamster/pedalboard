import numpy as np

from conftest import SR
from pedalfx.dsp import create_pedal
from pedalfx.engine import AudioConfig, AudioEngine, soft_clip
from pedalfx.sources import demo_riff, load_audio_file


def test_empty_chain_passes_audio_through(riff):
    engine = AudioEngine(SR)
    out = engine.render(riff)
    assert np.allclose(out[0], riff, atol=1e-6) and np.allclose(out[1], riff, atol=1e-6)


def test_bypassed_pedal_is_skipped(riff):
    engine = AudioEngine(SR)
    pedal = create_pedal("distortion", SR)
    pedal.enabled = False
    engine.set_chain([pedal])
    assert np.allclose(engine.render(riff)[0], riff, atol=1e-6)


def test_footswitch_crossfades_without_a_click():
    engine = AudioEngine(SR)
    pedal = create_pedal("boost", SR)
    pedal.set("gain", 12.0)
    engine.set_chain([pedal])
    block = np.full((2, 256), 0.1, dtype=np.float32)
    on = engine.process_block(block)
    pedal.enabled = False
    fading = engine.process_block(block)
    off = engine.process_block(block)
    assert on[0, -1] > 0.35
    assert np.abs(np.diff(fading[0])).max() < 0.01      # smooth ramp, no step
    assert abs(fading[0, 0] - on[0, -1]) < 0.01
    assert np.allclose(off, 0.1, atol=1e-6)


def test_chain_order_matters(riff):
    def run(order):
        engine = AudioEngine(SR)
        pedals = {"distortion": create_pedal("distortion", SR), "delay": create_pedal("delay", SR)}
        pedals["distortion"].set("drive", 0.9)
        pedals["delay"].set("mix", 0.6)
        engine.set_chain([pedals[name] for name in order])
        return engine.render(riff)
    assert np.abs(run(["distortion", "delay"]) - run(["delay", "distortion"])).max() > 0.02


def test_output_never_exceeds_full_scale(riff):
    engine = AudioEngine(SR)
    pedal = create_pedal("boost", SR)
    pedal.set("gain", 24.0)
    engine.set_chain([pedal])
    engine.master_db = 12.0
    out = engine.render(riff)
    assert np.abs(out).max() <= 1.0
    quiet = np.linspace(-0.6, 0.6, 50, dtype=np.float32)[None, :]
    assert np.array_equal(soft_clip(quiet), quiet)       # untouched below the knee


def test_meters_and_gains(riff):
    engine = AudioEngine(SR)
    engine.input_gain_db = -6.0
    out = engine.render(riff)
    assert abs(engine.in_peak - 0.3 * 10 ** (-6 / 20)) < 0.01
    assert abs(np.abs(out).max() - engine.out_peak) < 1e-6


def test_set_chain_adopts_engine_sample_rate():
    engine = AudioEngine(44100)
    pedal = create_pedal("chorus", 48000)
    engine.set_chain([pedal])
    assert pedal.sr == 44100
    engine.set_sample_rate(96000)
    assert pedal.sr == 96000


def test_audio_config_sanitizes_saved_values():
    cfg = AudioConfig.from_dict({"sample_rate": 12345, "block_size": 7, "input_channel": 0,
                                 "input_device": "Scarlett 18i8 USB", "unknown": 1})
    assert (cfg.sample_rate, cfg.block_size, cfg.input_channel) == (0, 128, 1)
    assert cfg.input_device == "Scarlett 18i8 USB"
    assert AudioConfig.from_dict(cfg.to_dict()) == cfg


def test_demo_riff_is_a_usable_loop():
    loop = demo_riff(SR)
    assert loop.dtype == np.float32 and 8 * SR < len(loop) < 12 * SR
    assert abs(np.abs(loop).max() - 0.3) < 1e-4
    assert abs(loop[0] - loop[-1]) < 0.15  # tails wrap, so the seam is continuous


def test_loop_source_wraps():
    engine = AudioEngine(SR)
    engine._loop = np.arange(10, dtype=np.float32)
    assert list(engine._next_loop(6)) == [0, 1, 2, 3, 4, 5]
    assert list(engine._next_loop(6)) == [6, 7, 8, 9, 0, 1]


def test_load_audio_file_resamples_to_mono(tmp_path):
    from pedalboard.io import AudioFile

    path = str(tmp_path / "tone.wav")
    t = np.arange(22050) / 22050
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)]).astype(np.float32)
    with AudioFile(path, "w", 22050, 2) as f:
        f.write(stereo * 0.5)
    mono = load_audio_file(path, SR)
    assert mono.ndim == 1 and abs(len(mono) - SR) < 10
    spectrum = np.abs(np.fft.rfft(mono))
    assert abs(np.argmax(spectrum) * SR / len(mono) - 440) < 3

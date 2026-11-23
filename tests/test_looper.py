"""Looper, drum machine and tuner."""

import numpy as np
import pytest

from conftest import SR
from pedalfx.dsp import create_pedal
from pedalfx.dsp.drums import INSTRUMENTS, KITS, STYLES, count_in_style, make_kit
from pedalfx.dsp.looper import ARMED, COUNT, DUB, EMPTY, MEASURE_CHOICES, PLAY, REC, STOP
from pedalfx.dsp.tuner import detect_pitch, note_for
from pedalfx.engine import AudioEngine


def tone(seconds, freq=220.0, amp=0.2):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def feed(looper, mono, block=256):
    """Run ``mono`` through the looper; returns (output left channel, drum audio)."""
    out = np.zeros(len(mono), dtype=np.float32)
    drums = np.zeros(len(mono), dtype=np.float32)
    for s in range(0, len(mono), block):
        seg = mono[s:s + block]
        out[s:s + len(seg)] = looper.process(np.stack([seg, seg]))[0]
        drums[s:s + len(seg)] = looper.aux
    return out, drums


def make(**settings):
    """A looper that is 'alive' (has seen audio). Settings use display values."""
    looper = create_pedal("looper", SR)
    defaults = {"start": "Now", "after": "Play", "drums": "Off", "measures": "1", "tempo": 120}
    for key, value in {**defaults, **settings}.items():
        param = looper.param(key)
        looper.set(key, param.choices.index(value) if param.is_choice else value)
    looper.process(np.zeros((2, 16), dtype=np.float32))
    return looper


def press(looper, spaced=True):
    if spaced:
        looper.last_press = -10.0   # not a double tap
    assert looper.command("press")


MEASURE = 2 * SR   # one 4/4 measure at 120 bpm


# -- recording ----------------------------------------------------------
@pytest.mark.parametrize("block", [64, 256, 1000])
def test_fixed_length_loop_is_sample_exact_and_plays_back(block):
    looper = make(measures="2")
    take = tone(4.0, 220)
    press(looper)
    out, _ = feed(looper, take, block)
    assert looper.state == PLAY and looper.length == 2 * MEASURE and looper.pos == 0
    assert np.array_equal(out, take)                 # monitoring is clean while recording
    silence = np.zeros(2 * MEASURE, dtype=np.float32)
    played, _ = feed(looper, silence, block)
    assert np.allclose(played[500:-500], take[500:-500], atol=1e-6)
    again, _ = feed(looper, silence, block)          # and it loops
    assert np.allclose(again, played, atol=1e-6)


def test_after_rec_overdub_keeps_recording_as_a_new_layer():
    looper = make(measures="1", after="Overdub")
    press(looper)
    feed(looper, tone(1.0, 220))
    assert looper.state == REC
    feed(looper, tone(1.0, 220))
    assert looper.state == DUB and looper.length == MEASURE
    feed(looper, tone(2.0, 330))                     # one full pass of overdub
    press(looper)
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == PLAY
    layered, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    spectrum = np.abs(np.fft.rfft(layered))
    freqs = np.fft.rfftfreq(len(layered), 1 / SR)
    assert spectrum[np.argmin(abs(freqs - 220))] > 100 and spectrum[np.argmin(abs(freqs - 330))] > 100


def test_undo_removes_the_overdub_and_redo_restores_it():
    looper = make(measures="1")
    press(looper)
    feed(looper, tone(2.0, 220))
    silence = np.zeros(MEASURE, dtype=np.float32)
    base, _ = feed(looper, silence)
    press(looper)                                    # overdub one pass
    feed(looper, tone(2.0, 330))
    press(looper)
    both, _ = feed(looper, silence)
    assert np.abs(both - base).max() > 0.1
    assert looper.status()["can_undo"]
    looper.command("undo")
    undone, _ = feed(looper, silence)
    assert np.allclose(undone, base, atol=1e-5)
    looper.command("undo")                           # second time is redo
    redone, _ = feed(looper, silence)
    assert np.allclose(redone[2000:], both[2000:], atol=1e-3)


def test_auto_start_waits_for_the_first_note():
    looper = make(start="Auto", measures="1")
    press(looper)
    feed(looper, np.zeros(SR, dtype=np.float32))
    assert looper.state == ARMED and not looper.transport
    feed(looper, tone(0.5))
    assert looper.state == REC
    assert abs(looper.pos - SR // 2) <= 256          # recording began with the note
    press(looper)                                    # pressing while armed elsewhere cancels:
    other = make(start="Auto")
    press(other)
    feed(other, np.zeros(256, dtype=np.float32))
    press(other)
    feed(other, np.zeros(256, dtype=np.float32))
    assert other.state == EMPTY


def test_count_in_clicks_one_measure_then_records():
    looper = make(start="Count-in", measures="1")
    press(looper)
    _, clicks = feed(looper, np.zeros(MEASURE - 256, dtype=np.float32))
    assert looper.state == COUNT
    beat = SR // 2
    for b in range(4):                               # a click on every beat ...
        assert np.abs(clicks[b * beat: b * beat + 400]).max() > 0.1
        assert np.abs(clicks[b * beat + 9000: (b + 1) * beat - 200]).max() < 1e-3
    feed(looper, tone(256 / SR + 1.0))
    assert looper.state == REC and looper.pos == SR   # ... and recording starts exactly on the bar
    _, after = feed(looper, np.zeros(SR // 2, dtype=np.float32))
    assert np.abs(after).max() < 1e-6                # rhythm is off, so no drums once recording


def test_free_loop_without_drums_sets_the_tempo():
    looper = make(measures="Free", tempo=96)
    press(looper)
    feed(looper, tone(3.0))                          # 3 s = 2 measures of 4/4 at 160? no: 1 at 80
    press(looper)
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == PLAY and looper.length == 3 * SR
    assert looper.loop_bars == 1 and looper.get("tempo") == pytest.approx(80.0)
    assert looper.ui_dirty


def test_free_loop_with_drums_snaps_to_whole_measures():
    late = make(measures="Free", drums="On")
    press(late)
    feed(late, tone(2.25))                           # a little past one measure
    press(late)
    feed(late, np.zeros(256, dtype=np.float32))
    assert late.state == PLAY and late.length == MEASURE
    assert late.pos == SR // 4 + 256                 # playback carries on from the overshoot

    early = make(measures="Free", drums="On")
    press(early)
    feed(early, tone(3.5))                           # nearer two measures: keep recording
    press(early)
    feed(early, tone(0.25))
    assert early.state == REC
    feed(early, tone(0.3))
    assert early.state == PLAY and early.length == 2 * MEASURE


def test_pressing_early_in_fixed_mode_closes_at_the_next_bar_line():
    looper = make(measures="4")
    press(looper)
    feed(looper, tone(2.5))                          # into the second measure
    press(looper)
    feed(looper, tone(1.6))
    assert looper.state == PLAY and looper.length == 2 * MEASURE and looper.loop_bars == 2


# -- transport ----------------------------------------------------------
def test_double_tap_stops_and_discards_the_accidental_overdub():
    looper = make(measures="1")
    press(looper)
    feed(looper, tone(2.0))
    silence = np.zeros(MEASURE, dtype=np.float32)
    base, _ = feed(looper, silence)
    press(looper)                                    # first tap starts an overdub ...
    feed(looper, tone(0.1, 500))
    press(looper, spaced=False)                      # ... second tap means stop
    out, _ = feed(looper, tone(0.5, 500, 0.0))
    assert looper.state == STOP and np.abs(out).max() == 0.0
    press(looper)
    replay, _ = feed(looper, silence)
    assert looper.state == PLAY
    assert np.allclose(replay, base, atol=1e-5)      # the 0.1 s blip was not kept


def test_stop_while_recording_discards_the_take():
    looper = make(measures="4")
    press(looper)
    feed(looper, tone(1.0))
    looper.command("stop")
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == EMPTY and looper.length == 0


def test_second_track_and_clear():
    looper = make(measures="1")
    press(looper)
    feed(looper, tone(2.0, 220))
    looper.command("track")
    press(looper)                                    # track 2 is empty: this overdubs onto it
    feed(looper, tone(2.0, 330))
    press(looper)
    feed(looper, np.zeros(256, dtype=np.float32))
    status = looper.status()
    assert status["has"] == (True, True) and status["track"] == 1
    looper.set("level1", 0.0)
    only_two, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    spectrum = np.abs(np.fft.rfft(only_two))
    freqs = np.fft.rfftfreq(len(only_two), 1 / SR)
    assert spectrum[np.argmin(abs(freqs - 330))] > 50 * spectrum[np.argmin(abs(freqs - 220))]
    looper.command("clear")                          # clears the selected track only
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.status()["has"] == (True, False) and looper.state == PLAY
    looper.command("track")
    looper.command("clear")
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == EMPTY and looper.length == 0


def test_hold_takes_back_the_press_and_undoes_the_last_layer():
    looper = make(measures="1")
    press(looper)
    feed(looper, tone(2.0, 220))
    silence = np.zeros(MEASURE, dtype=np.float32)
    base, _ = feed(looper, silence)
    press(looper)
    feed(looper, tone(2.0, 330))
    press(looper)
    feed(looper, silence)
    press(looper)                                    # the press that begins the hold
    feed(looper, tone(0.2, 700))
    looper.command("hold")
    back, _ = feed(looper, np.zeros(MEASURE - int(0.2 * SR), dtype=np.float32))
    out, _ = feed(looper, silence)
    assert looper.state == PLAY
    assert np.allclose(out, base, atol=1e-5)         # neither the 330 layer nor the 700 blip


def test_commands_are_ignored_while_audio_is_off():
    looper = create_pedal("looper", SR)
    assert not looper.alive and not looper.command("press")
    assert not make().command("explode")


def test_status_counts_measures_and_beats():
    looper = make(measures="2", drums="On")
    press(looper)
    feed(looper, tone(2.0 + 1.3))                    # measure 2, a bit past beat 3
    status = looper.status()
    assert (status["state"], status["bar"], status["bars"]) == (REC, 2, 2)
    assert status["beat"] == 2 and status["beats"] == 4
    assert status["progress"] == pytest.approx(3.3 / 4.0, abs=0.01)
    assert make(measures="Free").status()["bars"] == 0


# -- drum machine -------------------------------------------------------
def test_every_style_and_kit_is_well_formed():
    assert len(STYLES) >= 12 and STYLES[0].name == "Sidestick"
    for style in STYLES:
        assert style.steps % style.beats == 0
        assert set(count_in_style(style).parts["A"]) == {"R"}
    for name in KITS:
        kit = make_kit(name, SR)
        assert set(kit) == set(INSTRUMENTS)
        for wave in kit.values():
            assert wave.dtype == np.float32 and np.isfinite(wave).all()
            assert 0.1 < np.abs(wave).max() <= 1.0 and len(wave) <= 2 * SR
    assert np.array_equal(make_kit("Sidestick", SR)["S"][:50], (make_kit("Studio", SR)["R"] * 1.2)[:50])


@pytest.mark.parametrize("style", [s.name for s in STYLES])
def test_drums_follow_the_loop_and_do_not_depend_on_block_size(style):
    def run(block):
        looper = make(measures="2", drums="On", style=style, fill="On")
        press(looper)
        return feed(looper, tone(9.0), block)
    out_a, drums_a = run(64)
    out_b, drums_b = run(1000)
    assert np.abs(drums_a).max() > 0.1
    assert np.allclose(drums_a, drums_b, atol=1e-6) and np.allclose(out_a, out_b, atol=1e-6)


def test_sidestick_groove_puts_the_rim_on_the_backbeat():
    looper = make(measures="1", drums="On", style="Sidestick", fill="Off")
    looper.set("kit", 0)
    press(looper)
    _, drums = feed(looper, np.zeros(2 * MEASURE, dtype=np.float32))
    rim = make_kit("Studio", SR)["R"]
    beat = SR // 2
    for position in (beat, MEASURE + beat):          # beat 2 (beat 4 overlaps a kick tail)
        window = drums[position: position + len(rim)]
        hat = make_kit("Studio", SR)["H"] * 0.72
        expected = rim * 0.72
        expected[:len(hat)] += hat
        assert np.allclose(window, expected * (0.6 * 0.8), atol=2e-3)
    assert np.abs(drums[3 * beat: 3 * beat + 200]).max() > 0.1   # and something lands on 4


def test_fill_and_part_switch():
    looper = make(measures="Free", drums="On", style="Rock", fill="Off")
    looper.command("drums")                          # off ...
    looper.command("drums")                          # ... and on again: drums jam on their own
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.jam and looper.transport and looper.state == EMPTY
    _, plain = feed(looper, np.zeros(MEASURE - 256, dtype=np.float32))
    feed(looper, np.zeros(SR // 4, dtype=np.float32))
    looper.command("next")
    _, filled = feed(looper, np.zeros(MEASURE - SR // 4, dtype=np.float32))
    assert looper.part == "A" and looper.switch
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.part == "B" and not looper.switch  # switched on the bar line
    assert np.abs(filled[-SR // 2:]).sum() > 1.5 * np.abs(plain[-SR // 2:]).sum()   # the tom run
    looper.command("drums")
    _, quiet = feed(looper, np.zeros(SR, dtype=np.float32))
    assert not looper.transport and np.abs(quiet[256:]).max() == 0.0


def test_tempo_knob_moves_the_beat_until_a_loop_owns_it():
    looper = make(measures="1", tempo=120)
    looper.set("tempo", 60)
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.measure == 4 * SR
    press(looper)
    feed(looper, tone(4.0))
    looper.set("tempo", 200)
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.length == 4 * SR and looper.measure == 4 * SR and looper.status()["tempo"] == 60


def test_measure_choices_cover_common_lengths():
    assert MEASURE_CHOICES[0] == "Free" and {"1", "2", "4", "8", "12", "16"} <= set(MEASURE_CHOICES)
    waltz = make(measures="2", style="Waltz", tempo=120)
    press(waltz)
    feed(waltz, tone(3.1))
    assert waltz.length == 3 * SR                    # two measures of 3/4


def test_drums_bypass_the_pedals_after_the_looper():
    engine = AudioEngine(SR)
    looper = create_pedal("looper", SR)
    mute = create_pedal("tuner", SR)
    mute.set("mode", 1)
    engine.set_chain([looper, mute])                 # everything after the looper is silenced ...
    engine.process_block(np.zeros((2, 256), dtype=np.float32))
    looper.set("start", 0)
    looper.command("press")
    out = engine.render(tone(1.0))
    assert np.abs(out).max() > 0.2                   # ... but the drums still reach the output
    looper.enabled = False
    engine.render(tone(0.1))
    assert np.abs(engine.render(tone(0.5))).max() == 0.0


# -- tuner --------------------------------------------------------------
@pytest.mark.parametrize("freq,name,octave", [(82.41, "E", 2), (110.0, "A", 2), (146.83, "D", 3),
                                              (196.0, "G", 3), (246.94, "B", 3), (329.63, "E", 4)])
def test_tuner_reads_open_strings(freq, name, octave):
    t = np.arange(SR) / SR
    string = sum(np.sin(2 * np.pi * freq * h * t) / h for h in range(1, 7)) * 0.08
    string += 0.3 * 0.08 * np.sin(2 * np.pi * 2 * freq * t)   # strong 2nd harmonic: octave-error bait
    tuner = create_pedal("tuner", SR)
    out = np.concatenate([tuner.process(np.stack([b, b]).astype(np.float32))[0]
                          for b in np.array_split(string, 180)])
    assert np.allclose(out, string, atol=1e-6)       # Thru passes the guitar untouched
    reading = tuner.read()
    assert (reading["note"], reading["octave"]) == (name, octave)
    assert abs(reading["cents"]) < 1.0
    assert tuner.read() is None                      # no new audio since the last reading


def test_tuner_cents_reference_and_silence():
    sharp = 110.0 * 2 ** (20 / 1200)
    t = np.arange(8192) / SR
    assert note_for(detect_pitch(np.sin(2 * np.pi * sharp * t) * 0.1, SR))[2] == pytest.approx(20, abs=0.5)
    assert note_for(440.0, ref=432.0)[0] == "A" and note_for(440.0, ref=432.0)[2] > 30
    assert detect_pitch(np.zeros(4096), SR) is None
    assert detect_pitch(np.random.default_rng(1).standard_normal(4096) * 0.05, SR) is None


def test_tuner_mute_fades_out():
    tuner = create_pedal("tuner", SR)
    block = np.full((2, 256), 0.2, dtype=np.float32)
    tuner.process(block)
    tuner.set("mode", 1)
    fading = tuner.process(block)[0]
    assert fading[0] > 0.15 and fading[-1] < 0.01 and np.all(np.diff(fading) <= 0)
    assert np.abs(tuner.process(block)).max() == 0.0
    tuner.set("mode", 0)
    tuner.process(block)
    assert np.allclose(tuner.process(block), 0.2)


# -- stopping tracks ----------------------------------------------------
def two_tracks(stop="Now"):
    """Track 1 holds 220 Hz, track 2 holds 330 Hz, both playing; track 2 is selected."""
    looper = make(measures="1", stop=stop)
    press(looper)
    feed(looper, tone(2.0, 220))
    looper.command("track")
    press(looper)
    feed(looper, tone(2.0, 330))
    press(looper)
    feed(looper, np.zeros(MEASURE, dtype=np.float32))
    assert looper.state == PLAY and looper.pos == 0 and looper.playing == [True, True]
    return looper


def heard(audio):
    """(level at 220 Hz, level at 330 Hz) in a stretch of looper output."""
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)))) / len(audio)
    freqs = np.fft.rfftfreq(len(audio), 1 / SR)
    return tuple(float(spectrum[np.argmin(abs(freqs - f))]) for f in (220, 330))


def test_stop_only_stops_the_selected_track():
    looper = two_tracks()
    looper.command("stop")                           # track 2
    out, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    low, high = heard(out[4000:])
    assert looper.state == PLAY and looper.playing == [True, False]
    assert low > 0.02 and high < 0.001
    press(looper)                                    # Space brings it back, still in sync
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == PLAY and looper.playing == [True, True]
    out, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    assert min(heard(out)) > 0.02
    looper.command("stop")
    looper.command("track")
    looper.command("stop")                           # last one playing: the looper stops
    out, _ = feed(looper, np.zeros(SR, dtype=np.float32))
    assert looper.state == STOP and not looper.transport and np.abs(out[512:]).max() == 0.0
    press(looper)
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.playing == [True, True]            # play starts everything again


def test_stop_at_loop_end_waits_for_the_bar_line():
    looper = two_tracks(stop="Loop End")
    feed(looper, np.zeros(SR // 2, dtype=np.float32))
    looper.command("stop")                           # track 2, a quarter of the way in
    rest, _ = feed(looper, np.zeros(MEASURE - SR // 2, dtype=np.float32))
    assert looper.status()["pending"] == (False, False) and looper.playing == [True, False]
    assert heard(rest)[1] > 0.02                     # it played out the rest of the loop
    after, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    assert heard(after)[0] > 0.02 and heard(after)[1] < 0.001
    assert looper.pos == 0 and looper.state == PLAY


def test_both_tracks_can_be_queued_to_stop_together():
    looper = two_tracks(stop="Loop End")
    feed(looper, np.zeros(SR // 4, dtype=np.float32))
    looper.command("stop")
    looper.command("track")
    looper.command("stop")
    out, _ = feed(looper, np.zeros(SR, dtype=np.float32))
    assert looper.status()["pending"] == (True, True) and looper.state == PLAY
    assert min(heard(out[4000:])) > 0.02
    out, _ = feed(looper, np.zeros(MEASURE, dtype=np.float32))
    tail = out[MEASURE - SR - SR // 4 + 64:]
    assert looper.state == STOP and looper.pos == 0 and not looper.transport
    assert np.abs(tail).max() == 0.0                 # silent from the bar line on


def test_pending_stop_can_be_cancelled_or_forced():
    looper = two_tracks(stop="Loop End")
    looper.command("stop")
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.pending == [False, True]
    press(looper)                                    # Space: never mind
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.pending == [False, False] and looper.state == PLAY and looper.playing[1]
    looper.command("stop")
    looper.command("stop")                           # asking twice stops it right away
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.playing == [True, False] and looper.pending == [False, False]


def test_stop_all_and_clearing_the_last_playing_track():
    looper = two_tracks(stop="Loop End")
    looper.command("stopall")
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == STOP
    press(looper)
    feed(looper, np.zeros(256, dtype=np.float32))
    looper.set("stop", 0)
    looper.command("track")                          # select track 1 and stop it
    looper.command("stop")
    looper.command("track")                          # then clear track 2, the only one playing
    looper.command("clear")
    feed(looper, np.zeros(256, dtype=np.float32))
    assert looper.state == STOP and looper.has == [True, False]

# Pedalboard — Spec

A real-time guitar pedalboard that looks and behaves like one. This is the living spec for v2:
what is built, the rules new work follows, the interface the sibling
[synth-rack](../synth-rack) depends on, and the backlog. Update it when behaviour changes.
(`specs/001-i-want-to/` describes the original v1 and is historical.)

Detail lives elsewhere and is not repeated here: `README.md` (how to use it),
`docs/EFFECTS.md` (every effect and knob range), `docs/ARCHITECTURE.md` (threads, audio, looper
internals, preset format).

## 1. Goals

- Play guitar through a board of pedals in real time, with latency low enough to feel direct.
- Look and behave like hardware: painted stompboxes, drag to re-wire, knobs you turn, footswitches.
- Usable without the mouse, so a foot controller that types keys can run a set.
- Audition without a guitar (built-in demo riff, or an audio file).
- `pedalboard` on the PATH starts it from anywhere (`bin/pedalboard`, linked into `~/.local/bin` by `install.sh`).
- Boards are saved outside this repository, in the shared presets repo: `pedalboard/` in
  `$GEAR_PRESETS`, else `../gear-presets` (its README describes it); without that checkout,
  `~/.pedalboard/boards`. Each save or delete makes a local git commit there (`presets.git_commit`).
  Boards left in this repo's old `boards/` folder or in `~/.pedalboard/boards` are moved in on start.

## 2. What is built (v2.1)

| Area | State |
|---|---|
| Pedals | Pitchfork (tuner), Squeeze (compressor), Lift (boost), Scorch (drive), Orbit (phaser), Tidal (chorus), Pulse (tremolo), Echoplane (delay), Cathedral (reverb), Prism Console (4-module texture workstation), Rerun (2-track looper + drum machine) |
| Board | Up to 12 pedals in a left-to-right chain; drag to reorder, drag off to remove; 12 finishes; 4 board skins |
| Sources | Live input (device + channel), demo riff, looping audio file |
| Audio | Device / sample rate / buffer settings, input and master gain, meters, soft-clipped output |
| Presets | 8 factory boards (never overwritten), user boards in the presets repo, session restore |
| Control | Keyboard / foot-controller navigation; looper letter keys |

## 3. Rules

- Python, PyQt6, numpy, Spotify `pedalboard`, sounddevice. No scipy.
- `pedalfx/dsp` must not import Qt, so it can run headless and be hosted elsewhere.
- Audio blocks are float32 `(2, n)`. No per-sample Python loops in `process`.
- The UI thread only writes `pedal.values` / `pedal.enabled` and replaces `engine.chain`.
  Stateful pedals take commands (`looper.command(...)`).
- A new pedal = a `Pedal` subclass plus an entry in `PEDAL_CLASSES`; the generic widget, shelf,
  presets and parametrised tests pick it up.
- Results must not depend on buffer size (tested for every deterministic pedal).

## 4. Interface used by synth-rack

synth-rack's *Pedal Loop* module imports this repo's DSP package in-process and runs a saved
board on audio from the rack. It treats this repo as read-only. It relies on:

| What | Where | Contract |
|---|---|---|
| Package location | `src/pedalfx/` next to synth-rack (`../pedalboard`; the old name `../pedalboard-effects` is still found) | `pedalfx.dsp` and `pedalfx.presets` import without Qt |
| Boards | `presets.boards_dir()` (`*.json` there), `presets.FACTORY_BOARDS` | each has `name` and `pedals`; synth-rack calls `boards_dir()` so both apps agree on the folder |
| Building a chain | `presets.pedals_from_board(data, sr)` | returns `Pedal` objects; unknown types skipped |
| Running it | `pedal.process(x)` with float32 `(2, n)`, `pedal.enabled`, `pedal.set_sample_rate(sr)` | state kept between blocks |
| Display | `pedal.TYPE`, `pedal.NAME`, `pedal.finish` / `pedal.FINISH` | finish names as in `ui/theme.FINISHES` |
| Side output | `pedal.aux` | synth-rack clears and ignores it |

Pedal Loop skips `tuner` and `looper` because they need this app's own UI. New pedals added here
appear in Pedal Loop automatically, as long as the points above still hold. **If any of them
changes, update synth-rack's `dsp/utility.py` (`PedalLoop`, `available_boards`) and its copy of
the finish colours (`ui/theme.PEDAL_FINISHES`) in the same sitting.** synth-rack's test
`test_pedal_loop_runs_a_saved_pedalboard` catches a break.

Shared code: synth-rack started from copies of `dsp/core.py` primitives (`Param`, `Ramp`,
`DelayLine`, `Echo`) and the engine's device handling. They are copies, not imports; fixes to one
should be considered for the other.

## 5. Backlog (not built)

- A cleaner visual style to match synth-rack, if wanted (not requested yet).
- MIDI foot controller input alongside key-typing pedals.
- More pedals; pedal ideas from synth-rack modules (and the reverse).
- Record the output to a file from the app.
- Send/return or parallel routing on the board.

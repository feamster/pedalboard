# Architecture

```
            UI thread (PyQt6)                         audio thread (PortAudio callback)
 ┌────────────────────────────────────┐         ┌──────────────────────────────────────┐
 │ MainWindow                         │         │ AudioEngine.process_block            │
 │  ├ transport bar (source, presets) │  sets   │   input gain → meter                 │
 │  ├ BoardView ── PedalWidget × n ───┼────────▶│   for pedal in chain: pedal.process  │
 │  └ PedalBrowser (the shelf)        │ values  │   master gain → soft clip → meter    │
 └────────────────────────────────────┘         └──────────────────────────────────────┘
```

## Layers

- **`pedalfx/dsp`** — no Qt. `core.py` has `Param`, the `Pedal` base class and the primitives
  (`DelayLine`, `Echo`, `Reverser`, `PitchTaps`, `Phasor`, `Ramp`). `pedals.py` has the eight
  stompboxes; `console.py` has Prism Console; `tuner.py`, `looper.py` and `drums.py` the rest. `__init__.py` is the registry (`PEDAL_CLASSES`
  defines shelf order).
- **`pedalfx/engine.py`** — `AudioEngine` owns the chain and the sounddevice stream.
  `process_block` and `render` work without any audio hardware, which is what the tests use.
- **`pedalfx/presets.py`** — factory boards, user boards (JSON) and the session file.
- **`pedalfx/ui`** — everything is painted with `QPainter`; there are no image assets.
  `theme.py` holds finishes, board skins and shared drawing helpers; `widgets.py` the knob,
  footswitch, switches and meters; `pedal_widget.py` the pedals; `board_view.py` the board and
  shelf; `main_window.py` the window, settings dialog and session handling.

## Audio

Blocks are float32, shaped `(2, n)`. Filters and the stock effects (compressor, phaser, reverb,
ladder filter, shelves) are Spotify `pedalboard` plugins called with `reset=False` so they keep
state between blocks. Anything that needs a modulated or processed delay line is numpy code in
`core.py`, vectorised per block — there are no per-sample Python loops. A whole board costs
roughly 0.2–0.5 ms per 128-sample block.

Things worth knowing before changing it:

- **Thread safety is by convention.** The UI thread writes plain floats into `pedal.values` and
  the audio thread reads them; the chain is a tuple that is replaced, never mutated. No locks.
- **The audio callback is Python**, so it shares the GIL with the UI. `app.py` sets
  `sys.setswitchinterval(1e-4)` so the callback is not kept waiting for the default 5 ms, and
  pedal faces are cached as pixmaps so drags repaint cheaply. Measured with a pedal being dragged
  and a knob turning at 60 Hz: 2 of ~1000 callbacks overran a 128-sample buffer; without the
  switch-interval change it was about one in three.
- **Don't use `latency="low"`.** On the Scarlett it resolves to ~65 ms round trip. The engine asks
  for one buffer's worth explicitly and runs at the device's native sample rate.
- **pedalboard's `Limiter` adds make-up gain**, so the output safety stage is a plain soft clipper
  (`engine.soft_clip`): transparent below 0.7, rounded into ±1 above.
- **Feedback delays shorter than the block** are processed in chunks (`Echo.process`), so results
  do not depend on buffer size. The tests check this for every deterministic pedal.
- **Smooth, don't step.** Gains go through `Ramp`; delay time glides at a bounded rate; the
  footswitch crossfades over one block.

## The looper

`dsp/looper.py` is a state machine that runs entirely on the audio thread.

- **Commands, not shared state.** The UI calls `looper.command("press")` etc., which appends to a
  deque; `process` drains it at the top of each block. `status()` is a read-only snapshot for the
  display. Commands are refused when no audio has arrived for 0.5 s, so nothing queues up while
  the engine is off.
- **Blocks are split at every boundary** — loop wrap, the end of a fixed-length recording, the end
  of the count-in — so lengths are sample-exact and identical at any buffer size (tested).
- **Two clocks.** `pos` is the position in the loop; `clock` drives the drum grid. A loop's length
  is always a whole number of measures of the frozen tempo, so they stay locked.
- **Drums use a mix-ahead ring**: each hit is added into a circular buffer at its sample offset and
  the block just reads the next slice. `dsp/drums.py` synthesises the kits once per sample rate.
- **Aux output.** A pedal may leave audio in `pedal.aux`; the engine adds it after the whole chain.
  That is how the drums avoid later pedals.

The tuner follows the same split: the audio thread copies samples into a ring, and
`Tuner.read()` runs the autocorrelation pitch detector on the UI thread when the display polls.

Keyboard control lives in `MainWindow.handle_key`, fed by an application event filter so it works
whichever widget has focus (but not while typing in a text field or with a menu open).

## Adding a pedal

1. Subclass `Pedal` in `dsp/pedals.py`:

   ```python
   class Wah(Pedal):
       TYPE = "wah"                 # id used in preset files
       NAME = "Quack"               # painted on the pedal
       TAGLINE = "auto wah"
       FINISH = "crimson"           # any key of theme.FINISHES
       PARAMS = (
           Param("sens", "Sens", default=0.5),
           Param("freq", "Freq", 300.0, 2500.0, 800.0, "Hz", skew=2.0),
           Param("mode", "Mode", default=0, choices=("LP", "BP")),
       )

       def _build(self):            # create state; called again if the sample rate changes
           self.filt = pb.LadderFilter()

       def process(self, x):        # x is float32 (2, n); read self.values[...] each block
           ...
           return y
   ```

2. Add the class to `PEDAL_CLASSES` in `dsp/__init__.py`.

That is all: the generic `PedalWidget` lays out 2–4 knobs and one switch automatically, the shelf
gets a thumbnail, presets serialise it, and the parametrised tests in `tests/test_dsp.py` pick it
up. A pedal that needs a bespoke face (like the console) subclasses `PedalWidget` and is returned
from `make_pedal_widget`.

## Preset format

```json
{
  "version": 2,
  "name": "My Tone",
  "skin": "walnut",
  "pedals": [
    {"type": "delay", "enabled": true, "finish": null,
     "params": {"time": 380.0, "feedback": 0.35, "mix": 0.3, "tone": 0.6, "mode": 1}},
    {"type": "console", "enabled": true, "finish": null, "order": [0, 1, 2, 3],
     "console_preset": "Custom", "params": {"...": 0}}
  ]
}
```

Unknown pedal types and parameters are skipped on load, and values are clamped to their ranges.
The v1 app kept its presets in `~/.pedalboard/presets/` with a different schema; v2 neither reads nor modifies that subfolder.
v2's own state (`session.json`) sits next to it in `~/.pedalboard/`. It lived in `~/.pedalboard-effects/` until the
repository was renamed; `presets.migrate_home()` moves it across on first run.

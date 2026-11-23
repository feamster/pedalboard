# pedalboard-effects Development Guidelines

Real-time guitar pedalboard: PyQt6 UI (custom painted, drag-and-drop) over a numpy +
Spotify-pedalboard DSP chain. Rewritten as v2 in November 2026; `specs/001-i-want-to/` describes
the original v1 and is historical.

## Technologies
- Python 3.11+, PyQt6, pedalboard (Spotify), sounddevice, numpy. No scipy.

## Project Structure
```
src/main.py            launcher (python src/main.py)
src/pedalfx/dsp/       pedals + DSP primitives; must not import Qt
src/pedalfx/engine.py  audio stream and pedal chain
src/pedalfx/presets.py factory/user boards, session
src/pedalfx/ui/        widgets, board, main window
tests/                 pytest (pythonpath = src)
docs/                  EFFECTS.md, ARCHITECTURE.md
```

## Commands
```
pytest && ruff check .          # from the repo root
python src/main.py              # run the app
python src/main.py --screenshot out.png   # render the UI without audio
```

## Conventions
- Audio blocks are float32 `(2, n)`. No per-sample Python loops in `process`; vectorise.
- The looper is driven by `looper.command(...)` only; never touch its loop state from the UI thread.
- A new pedal = a `Pedal` subclass plus an entry in `PEDAL_CLASSES` (see docs/ARCHITECTURE.md).
- The UI thread only writes `pedal.values` / `pedal.enabled`; replace `engine.chain`, never mutate it.
- Set `PEDALFX_HOME` to a temp dir when running the app from scripts so the user's saved
  session in `~/.pedalboard-effects` is not touched. Tests already use `tmp_path`.
- Opening a real audio stream in a script makes sound: use the "BlackHole 2ch" device or
  `engine.master_db = -90`.

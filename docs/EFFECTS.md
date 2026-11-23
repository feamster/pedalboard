# Effect reference

All pedals process stereo at the engine's sample rate. Guitar input is mono and is fed to both
channels; the stereo pedals (chorus, ping-pong delay, reverb, auto-pan, the console's doubler and
tape effects) open it up from there.

## Stompboxes

### Pitchfork — chromatic tuner
Shows the nearest note, octave, cents off and frequency; the marker turns green within ±3 cents.
Range is roughly 55 Hz–1.4 kHz, so it covers a bass's low A up past a guitar's top fret.

| Control | Notes |
|---|---|
| A4 | Reference pitch, 430–450 Hz |
| Output | **Thru** passes the guitar through while you tune; **Mute** silences everything after it |

The footswitch turns the tuner (and its display) off entirely. It only reads while the engine is on.

### Squeeze — compressor
| Knob | Range | Notes |
|---|---|---|
| Sustain | 0–100 % | Lowers the threshold (−8 → −40 dB) and raises the ratio (2:1 → 10:1), with make-up gain |
| Attack | 1–60 ms | Longer lets the pick attack through |
| Level | ±12 dB | Output trim |

### Lift — clean boost
| Knob | Range | Notes |
|---|---|---|
| Gain | 0–24 dB | Clean gain; use it to push Scorch harder |
| Bass | ±10 dB | Low shelf at 180 Hz |
| Treble | ±10 dB | High shelf at 3.2 kHz |

### Scorch — overdrive / distortion / fuzz
| Control | Notes |
|---|---|
| Drive | Gain into the clipper |
| Tone | Low-pass after the clipper, 700 Hz → 12 kHz |
| Level | Output volume |
| Mode | **OD**: asymmetric soft clip, tight low end. **Dist**: two clipping stages, more gain. **Fuzz**: squared-off, full-range |

There is no oversampling, so very high Drive with Tone fully up can alias a little; rolling Tone
back hides it.

### Orbit — phaser
Rate (0.05–8 Hz), Depth, Regen (feedback) and Mix.

### Tidal — stereo chorus
Rate (0.1–6 Hz), Depth and Mix. The left and right voices are a quarter-cycle apart. Mix at 100 %
is pure pitch vibrato.

### Pulse — tremolo
Rate (0.5–15 Hz), Depth, and a shape switch: **Smooth** (sine), **Chop** (near-square) or **Pan**
(the two channels move in opposition).

### Echoplane — delay
| Control | Notes |
|---|---|
| Time | 30–1200 ms. Turning it while playing glides the pitch like a tape machine changing speed |
| Repeats | Feedback, up to 95 % |
| Mix | Echo level |
| Tone | Low-pass on the repeats; each repeat gets darker |
| Mode | **Digital**: clean. **Tape**: darker, saturating repeats with slow wow. **Ping**: repeats bounce left/right |

### Cathedral — reverb
Decay (room size), Tone (bright ↔ damped), Mix and Pre-Dly (0–150 ms before the reverb starts).

## Rerun — looper and drum machine

Two tracks that share one loop length, one level of undo/redo per track, up to three minutes.

**States.** READY → (ARMED or COUNT) → REC → DUB ⇄ PLAY, and STOP. The main switch moves along
that line; a double tap (two presses within 0.4 s) stops, and discards anything the first tap
started. Stopping during the very first recording throws that take away.

**Loop length.**

| Measures | Rhythm | What decides the length |
|---|---|---|
| 1–16 | either | Closes itself after that many measures at the current tempo. Pressing early closes it at the end of the measure you are in |
| Free | on | Your press, snapped to the nearest whole measure (it keeps recording to the bar line if you were early) |
| Free | off | Exactly your press. The tempo is then set so the loop is 1, 2, 4… measures at 70–140 bpm |

**Stopping.** Stop acts on the selected track only, either immediately or at the end of the loop
(the Stop setting; a track waiting for the loop end flashes on the screen). The other track keeps
playing, and the looper itself stops — drums included — when no track is left playing. Esc stops
everything at once.

**Tracks.** T selects a track. Recording onto the empty track is an overdub against the existing
loop. Track 1 and Track 2 knobs set playback level; Clear empties the selected track, and the
looper returns to READY when both are empty.

**Drum machine.** Styles have an A part, a B part and a fill:

Sidestick · Rock · Driving 8ths · Pop · Half-Time · Funk · Bossa · One Drop · Train · Motown ·
Shuffle (triplet feel) · Waltz (3/4) · 6/8 Ballad · Metronome

Kits: **Studio**, **Sidestick** (snare hits become rim clicks), **Electro** (long sine kick, clap),
**Lo-Fi** (dull and crunchy). All drums are synthesised, not sampled. They start with the loop,
stop with it, and go straight to the output after the pedal chain.

Compared with a real RC-500: no loop FX, no memories/saving loops, tracks cannot have different
lengths, one undo level, no time-stretching when the tempo changes, no MIDI sync.

## Prism Console

Signal flow: `in → [module] → [module] → [module] → [module] → Tilt → Mix → Level → out`, with the
module order set by the ◀ ▶ arrows (default Character → Movement → Diffusion → Texture).

### Global knobs
| Knob | Notes |
|---|---|
| Tilt | Tilt EQ around 650 Hz: left is darker/fuller, right is brighter/thinner (±7 dB) |
| Rate | 0.05–12 Hz. Speed for Movement effects. For **Pitch** it selects the interval instead |
| Time | 40 ms–1.5 s. Echo time for Cascade/Reels/Collage, slice length for Reverse, size for Space |
| Mix | Wet/dry for the whole console |
| Level | ±12 dB output trim (small knob, bottom right) |

### Character
| Effect | Amount does |
|---|---|
| Drive | Soft, asymmetric overdrive; from a hint of grit to full saturation |
| Sweeten | Gentle compression plus high-shelf "air" and a little warmth — an always-on polish |
| Fuzz | Squared-off fuzz |
| Howl | Fuzz through a screaming resonant band-pass; Amount also sweeps the resonant frequency up |
| Swell | Auto volume swell — each new note fades in. Amount sets the fade time (50 ms → 1.3 s) |

### Movement
| Effect | Amount does |
|---|---|
| Doubler | Level of two slowly drifting, cross-panned slap voices |
| Vibrato | Pitch-wobble depth (100 % wet) |
| Phaser | Depth and feedback |
| Tremolo | Depth |
| Pitch | Blend of a pitch-shifted voice. **Rate** picks the interval: −12, −7, −5, +4, +7, +12 semitones from left to right |

### Diffusion
| Effect | Amount does |
|---|---|
| Cascade | Clean echo: level and number of repeats |
| Reels | Tape echo: dark, saturating, wobbling repeats |
| Space | Reverb level (Time sets the size) |
| Collage | Sound-on-sound: what you play is layered into a long loop (2 × Time) that slowly decays |
| Reverse | Level of backwards playback of the last Time-long slice |

### Texture
| Effect | Amount does |
|---|---|
| Filter | Resonant low-pass; higher is darker (16 kHz → 220 Hz) |
| Squash | Slammed compressor with heavy make-up gain |
| Cassette | Wow, flutter, saturation, treble loss and a little hiss |
| Broken | Cassette with a failing transport: deeper warble and random per-channel dropouts |
| Interference | Sample-rate reduction, bit loss and radio crackle |

### Built-in textures
Init · Worn Tape · Glass Double · Howling Reels · Backwards Bloom · Dying Walkman · Shortwave ·
Octave Cloud · Pump & Swirl. Stepping to one resets every console knob except Level; touching a
knob afterwards shows "Custom".

### What it doesn't do
Compared with the hardware Chroma Console: no Gesture recording (knob-movement automation), no
Capture looper, no Drift control, no MIDI, and one effect per module at a time. Compared with RC-20:
no Flux/Magnitude macro. The sounds are approximations tuned by measurement rather than by ear
against the originals.

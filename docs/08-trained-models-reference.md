# Trained Models Reference

**Purpose:** Handoff document for programs and agents that need to USE the trained InputDNA models. Describes every available model, its purpose, how to load it, what it expects as input, and what it produces as output.

**Last trained:** 2026-03-10T12:10:40 (30.8 seconds)

## Table of Contents

- [Overview](#overview)
- [Model Location](#model-location)
- [Loading Models](#loading-models)
- [Mouse Models](#mouse-models)
  - [Path Generator](#path-generator)
  - [Speed Profile](#speed-profile)
  - [Overshoot Predictor](#overshoot-predictor)
  - [Micro-Jitter Generator](#micro-jitter-generator)
- [Keyboard Models](#keyboard-models)
  - [Text Typing Model](#text-typing-model)
  - [Number Typing Model](#number-typing-model)
  - [Key Hold Duration Model](#key-hold-duration-model)
  - [Shortcut Timing Model](#shortcut-timing-model)
- [Inference Pipeline — Mouse Movement](#inference-pipeline--mouse-movement)
- [Inference Pipeline — Keyboard Typing](#inference-pipeline--keyboard-typing)
- [Data Summary](#data-summary)
- [Scan Code Reference](#scan-code-reference)
- [File Sizes](#file-sizes)
- [Limitations and Future Work](#limitations-and-future-work)

---

<a id="overview"></a>

## Overview

InputDNA trains **8 specialized models** that together capture one user's unique input behavior — how they move the mouse and type on the keyboard. These models are an **ensemble** (not one monolithic model). Each handles a specific aspect of behavior.

The models are **statistical/KNN-based** (not deep learning). They use scikit-learn, scipy, and numpy. No GPU required for inference. All models are serialized as Python pickle files.

**Two primary use cases:**

1. **Mouse movement replay:** Given start `(x, y)` and end `(x, y)` coordinates, generate a complete mouse path with realistic timing that matches the user's movement patterns.

2. **Keyboard typing replay:** Given a text string, generate keystroke events with realistic inter-key delays and hold durations that match the user's typing rhythm.

---

<a id="model-location"></a>

## Model Location

Models are stored per-user in their data folder:

```
{APPDATA}/Local/InputDNA/db/{Username}_{Surname}_{DOB}/models/
```

**Current user path:**
```
C:\Users\vurun\AppData\Local\InputDNA\db\Uros_Vuruna_1990-06-20\models\
```

**Files in the models directory:**

| File | Model | Size |
|------|-------|------|
| `path_generator.pkl` | Mouse path generator (KNN) | 174 MB |
| `speed_profile.pkl` | Mouse speed curve | 1.5 KB |
| `overshoot_model.pkl` | Overshoot probability + magnitude | 891 B |
| `jitter_params.pkl` | Hand tremor parameters | 97 B |
| `text_typing.pkl` | Text digraph timing table | 22 KB |
| `number_typing.pkl` | Numpad digraph timing table | 3.4 KB |
| `key_hold.pkl` | Per-key hold durations | 1.9 KB |
| `shortcuts.pkl` | Shortcut timing profiles | 9.2 KB |
| `metadata.json` | Training metadata and stats | 528 B |

**How to determine the user folder programmatically:**

```python
import config
# After login, config knows the active user:
user_folder = config.get_active_user_folder()
models_dir = user_folder / "models"

# Or construct manually:
user_folder = config.get_user_folder("Uros", "Vuruna", "1990-06-20")
models_dir = user_folder / "models"
```

**Check if models exist:**

```python
metadata_path = models_dir / "metadata.json"
if metadata_path.exists():
    import json
    with open(metadata_path) as f:
        meta = json.load(f)
    # meta["models"] shows status of each model
    # meta["trained_at"] shows when training happened
```

---

<a id="loading-models"></a>

## Loading Models

Every model has a `load(path)` classmethod:

```python
from pathlib import Path

models_dir = Path("C:/Users/vurun/AppData/Local/InputDNA/db/Uros_Vuruna_1990-06-20/models")

from ml.mouse.path_model import PathModel
from ml.mouse.speed_model import SpeedModel
from ml.mouse.overshoot_model import OvershootModel
from ml.mouse.jitter_model import JitterModel
from ml.keyboard.text_model import TextTypingModel
from ml.keyboard.number_model import NumberTypingModel
from ml.keyboard.hold_model import HoldModel
from ml.keyboard.shortcut_model import ShortcutModel

path_model     = PathModel.load(models_dir / "path_generator.pkl")
speed_model    = SpeedModel.load(models_dir / "speed_profile.pkl")
overshoot      = OvershootModel.load(models_dir / "overshoot_model.pkl")
jitter_model   = JitterModel.load(models_dir / "jitter_params.pkl")
text_model     = TextTypingModel.load(models_dir / "text_typing.pkl")
number_model   = NumberTypingModel.load(models_dir / "number_typing.pkl")
hold_model     = HoldModel.load(models_dir / "key_hold.pkl")
shortcut_model = ShortcutModel.load(models_dir / "shortcuts.pkl")
```

All models are safe to load from any thread. Inference methods accept an optional `rng` parameter (`numpy.random.Generator`) for reproducibility.

---

<a id="mouse-models"></a>

## Mouse Models

<a id="path-generator"></a>

### Path Generator

**File:** `path_generator.pkl` (174 MB)
**Class:** `ml.mouse.path_model.PathModel`
**Method:** KNN (K-Nearest Neighbors) with normalized recorded paths

**What it does:** Given a start point and end point, generates a complete mouse cursor path — a sequence of (x, y) coordinates with timing — that matches how this specific user would move their mouse over that distance and direction.

**How it works internally:**
1. During training, all 62,929 recorded mouse movements were normalized: translated to origin, rotated so movement direction aligns with x-axis, scaled to unit distance.
2. Each normalized path is stored alongside features: `log(distance)` and `angle`.
3. A BallTree index enables fast nearest-neighbor lookup.
4. At inference: find the 10 most similar recorded movements by distance/angle, pick one weighted by similarity, then denormalize (rotate, scale, translate) to the target coordinates.

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `start_x` | `int` | Starting X coordinate (screen pixels) |
| `start_y` | `int` | Starting Y coordinate (screen pixels) |
| `end_x` | `int` | Target X coordinate (screen pixels) |
| `end_y` | `int` | Target Y coordinate (screen pixels) |
| `rng` | `np.random.Generator` | Optional. Random number generator for reproducibility. |

**Output:** Tuple of three numpy arrays:

| Array | Type | Description |
|-------|------|-------------|
| `path_x` | `np.ndarray[int32]` | X coordinates of each path point |
| `path_y` | `np.ndarray[int32]` | Y coordinates of each path point |
| `dt_us` | `np.ndarray[int64]` | Time delta in microseconds between consecutive points. `dt_us[0]` is always 0. |

**Example:**

```python
path_x, path_y, dt_us = path_model.predict(100, 100, 800, 400, rng=rng)
# path_x = [100, 100, 100, ..., 800, 800, 800]  — 209 points
# path_y = [100, 100,  99, ..., 400, 400, 400]
# dt_us  = [  0, 2793, 2793, ..., 2793]          — ~583ms total
```

**Important notes:**
- The first and last points are guaranteed to be exactly `(start_x, start_y)` and `(end_x, end_y)`.
- The `dt_us` from PathModel is **uniform** (evenly distributed). Use the Speed Profile model to redistribute timing realistically.
- If start == end (distance < 1px), returns a single point with `dt_us=[0]`.
- The generated path is a REAL recorded path adapted to the target — it will have natural curvature, not be a straight line.

**Training stats:**
- 62,929 paths indexed
- Distance range: 3.0 — 37,456 px

---

<a id="speed-profile"></a>

### Speed Profile

**File:** `speed_profile.pkl` (1.5 KB)
**Class:** `ml.mouse.speed_model.SpeedModel`
**Method:** Statistical percentiles from motor control analysis

**What it does:** Takes a generated path and redistributes the timing to match the user's characteristic speed curve — slower at start (acceleration), faster in the middle (cruise), slower at end (deceleration to target).

**How it works internally:**
1. For each recorded movement, extracted instantaneous speed at every path point.
2. Normalized both position (0→1 along path) and speed (0→1 relative to peak).
3. Averaged across 54,406 movements to get the user's typical speed profile.
4. Stored as a 50-bin lookup: normalized_position → normalized_speed.

**The user's speed profile characteristics:**
- Peak speed occurs at position **0.37** (37% along the path — slightly front-loaded)
- Profile peak value: 0.51 (normalized)
- Average movement speed: **0.286 px/ms** (286 px/s)

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path_x` | `np.ndarray[int32]` | X coordinates from PathModel |
| `path_y` | `np.ndarray[int32]` | Y coordinates from PathModel |
| `total_duration_us` | `float` | Total desired movement duration in microseconds |
| `rng` | `np.random.Generator` | Optional. Adds ±5% random variation to the profile. |

**Output:**

| Return | Type | Description |
|--------|------|-------------|
| `dt_us` | `np.ndarray[int64]` | Redistributed time deltas. `dt_us[0]=0`. Segments near start/end are longer (slower), middle segments are shorter (faster). |

**Example:**

```python
dt_us = speed_model.apply(path_x, path_y, total_duration_us=583900, rng=rng)
# dt_us[0]  = 0       (first point)
# dt_us[1]  = 100     (slow start — minimum gap)
# dt_us[5]  = 2820    (still accelerating)
# dt_us[100]= 1500    (cruise — fast)
# dt_us[-2] = 3464    (decelerating)
# dt_us[-1] = 100     (arrival)
```

**Important notes:**
- Minimum gap between points is 100 µs (to prevent zero-time jumps).
- Total duration of the output matches `total_duration_us` exactly.
- The variation parameter adds natural per-movement randomness — no two movements are identical.

---

<a id="overshoot-predictor"></a>

### Overshoot Predictor

**File:** `overshoot_model.pkl` (891 B)
**Class:** `ml.mouse.overshoot_model.OvershootModel`
**Method:** Logistic regression (probability) + Gaussian distributions (magnitude, correction time)

**What it does:** Predicts whether a mouse movement should overshoot the target (move past it and correct back), and if so, how far and how long the correction takes.

**This user's overshoot characteristics:**
- Overshoot rate: **0.41%** (very accurate — overshoots rarely)
- Average overshoot: **3.7%** of movement distance
- Average correction time: **265.5 ms**

**Methods:**

#### `should_overshoot(distance, speed, rng) → bool`

| Parameter | Type | Description |
|-----------|------|-------------|
| `distance` | `float` | Euclidean distance of the movement (px) |
| `speed` | `float` | Average speed (px/ms) |
| `rng` | `np.random.Generator` | Optional |

Returns `True` if this movement should have an overshoot.

#### `sample_overshoot(distance, rng) → (overshoot_px, correction_ms)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `distance` | `float` | Movement distance (px) |
| `rng` | `np.random.Generator` | Optional |

| Return | Type | Description |
|--------|------|-------------|
| `overshoot_px` | `float` | How far past the target (pixels) |
| `correction_ms` | `float` | How long the correction back takes (milliseconds) |

**Example:**

```python
distance = 750.0  # px
speed = 0.5       # px/ms

if overshoot.should_overshoot(distance, speed, rng=rng):
    overshoot_px, correction_ms = overshoot.sample_overshoot(distance, rng=rng)
    # overshoot_px ≈ 28 px (3.7% of 750)
    # correction_ms ≈ 265 ms
    # → extend the path PAST the target by overshoot_px,
    #   then add a correction segment back to the target
```

---

<a id="micro-jitter-generator"></a>

### Micro-Jitter Generator

**File:** `jitter_params.pkl` (97 B)
**Class:** `ml.mouse.jitter_model.JitterModel`
**Method:** Multi-octave sinusoidal noise (Perlin approximation) at physiological tremor frequency

**What it does:** Generates the tiny involuntary hand oscillations that occur during mouse movement. Without jitter, simulated paths look unnaturally smooth. This adds biological realism.

**This user's jitter characteristics:**
- Amplitude: **0.62 ± 0.64 px** (sub-pixel tremor)
- Frequency: **8 Hz** (matches human physiological tremor, 6-12 Hz range)

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `n_points` | `int` | Number of path points |
| `dt_us` | `np.ndarray[int64]` | Time deltas between points (for frequency calculation) |
| `rng` | `np.random.Generator` | Optional |

**Output:** Tuple of two arrays:

| Array | Type | Description |
|-------|------|-------------|
| `jitter_x` | `np.ndarray[float64]` | X displacement to add to each path point (pixels, fractional) |
| `jitter_y` | `np.ndarray[float64]` | Y displacement to add to each path point (pixels, fractional) |

**Example:**

```python
jx, jy = jitter_model.generate_jitter(len(path_x), dt_us, rng=rng)
# jx = [0.0, 0.02, 0.08, ..., -0.15, -0.04, 0.0]
# jy = [0.0, -0.01, 0.05, ..., 0.21, 0.03, 0.0]
# Max amplitude: ~0.95 px (x), ~1.02 px (y)

# Apply to path:
final_x = np.round(path_x + jx).astype(np.int32)
final_y = np.round(path_y + jy).astype(np.int32)
```

**Important notes:**
- Jitter fades in/out at path start/end (first/last 20% of points) to avoid jumps.
- Jitter is multi-octave (3 layers) for natural tremor appearance.
- Sub-pixel values are typical — round to int only at final application.

---

<a id="keyboard-models"></a>

## Keyboard Models

**Critical concept — Scan Codes:** All keyboard models use **scan codes** (physical key positions), NOT virtual keys or characters. A scan code represents where a key IS on the keyboard, regardless of language layout. This means the same model works for English, Serbian, or any other layout.

<a id="text-typing-model"></a>

### Text Typing Model

**File:** `text_typing.pkl` (22 KB)
**Class:** `ml.keyboard.text_model.TextTypingModel`
**Method:** Per-pair Gaussian lookup table + distance-based fallback

**What it does:** Given two consecutive scan codes (the previous key and the next key), returns a realistic inter-key delay in milliseconds that matches this user's typing rhythm.

**Covers:** `typing_mode="text"` and `typing_mode="code"` (regular typing, letters, symbols, punctuation).

**This user's text typing characteristics:**
- **826 unique scan-code pairs** with learned timing
- Global median inter-key delay: **156.7 ms** (~6.4 keys/second)
- Each pair has its own mean and standard deviation

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `from_scan` | `int` | Scan code of the key just pressed |
| `to_scan` | `int` | Scan code of the next key to press |
| `rng` | `np.random.Generator` | Optional |

**Output:**

| Return | Type | Description |
|--------|------|-------------|
| `delay_ms` | `float` | Inter-key delay in milliseconds (always ≥ 10.0) |

**Example:**

```python
# Typing "hello" — H(0x23) E(0x12) L(0x26) L(0x26) O(0x18)
text_model.sample_delay(0x23, 0x12, rng=rng)  # H→E: 112.5 ms
text_model.sample_delay(0x12, 0x26, rng=rng)  # E→L: 118.8 ms
text_model.sample_delay(0x26, 0x26, rng=rng)  # L→L: 146.7 ms (same key repeat)
text_model.sample_delay(0x26, 0x18, rng=rng)  # L→O: 186.7 ms
```

**Fallback behavior:** For scan-code pairs not in the lookup table (unseen during training), the model estimates delay based on:
1. Physical distance between the two keys on the keyboard
2. Global average delay adjusted by distance coefficient

---

<a id="number-typing-model"></a>

### Number Typing Model

**File:** `number_typing.pkl` (3.4 KB)
**Class:** `ml.keyboard.number_model.NumberTypingModel`
**Method:** Same as text model but trained exclusively on numpad data

**What it does:** Same as Text Typing Model but for numpad number entry. This is a SEPARATE model because numpad typing has fundamentally different patterns:
- Single hand (right hand only)
- Compact key layout (smaller distances)
- Often faster and more rhythmic
- Different finger usage patterns

**This user's numpad typing characteristics:**
- **126 unique numpad pairs** with learned timing
- Global median inter-key delay: **178.8 ms** (~5.6 keys/second)

**Interface is identical to TextTypingModel:**

```python
# Typing "42" on numpad — 4(0x4B) 2(0x50)
number_model.sample_delay(0x4B, 0x50, rng=rng)  # 4→2: ~180ms
```

**When to use which model:**
- Use **TextTypingModel** for: letters, symbols, punctuation, number row (top keyboard row)
- Use **NumberTypingModel** for: numpad keys exclusively

**Numpad scan codes:** `0x45` (NumLock), `0xE035` (/), `0x37` (*), `0x4A` (-), `0x4E` (+), `0x47-0x49` (7-9), `0x4B-0x4D` (4-6), `0x4F-0x51` (1-3), `0x52` (0), `0x53` (.), `0xE01C` (NumpadEnter)

---

<a id="key-hold-duration-model"></a>

### Key Hold Duration Model

**File:** `key_hold.pkl` (1.9 KB)
**Class:** `ml.keyboard.hold_model.HoldModel`
**Method:** Per-key Gaussian distribution

**What it does:** Given a scan code, returns how long the user typically holds that key before releasing it. Different keys have different hold durations — modifier keys (Shift, Ctrl) are held much longer than letter keys.

**This user's hold characteristics:**
- **80 unique keys** with learned timing
- Global median hold: **92.9 ms**
- Range: from ~64ms (quick taps) to ~724ms (Shift key held for uppercase)

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `scan_code` | `int` | Scan code of the key |
| `rng` | `np.random.Generator` | Optional |

**Output:**

| Return | Type | Description |
|--------|------|-------------|
| `duration_ms` | `float` | How long to hold the key (milliseconds, always ≥ 10.0) |

**Example:**

```python
hold_model.sample_duration(0x23, rng=rng)  # H: 80.8 ms
hold_model.sample_duration(0x12, rng=rng)  # E: 122.7 ms
hold_model.sample_duration(0x26, rng=rng)  # L: 64.0 ms
hold_model.sample_duration(0x2A, rng=rng)  # Left Shift: 723.7 ms (held for uppercase)
hold_model.sample_duration(0x39, rng=rng)  # Space: ~90 ms
```

**Notable per-key values:**

| Scan Code | Key | Mean Hold | Std |
|-----------|-----|-----------|-----|
| `0x2A` | Left Shift | 723.7 ms | 561.8 ms |
| `0xE05B` | Left Win | 260.3 ms | 250.2 ms |
| `0x12` | E | 107.6 ms | 15.6 ms |
| `0x19` | P | 90.0 ms | 14.5 ms |
| `0x26` | L | 64.0 ms | ~15 ms |

---

<a id="shortcut-timing-model"></a>

### Shortcut Timing Model

**File:** `shortcuts.pkl` (9.2 KB)
**Class:** `ml.keyboard.shortcut_model.ShortcutModel`
**Method:** Per-combo template matching with statistical distributions

**What it does:** Given a keyboard shortcut (e.g., Ctrl+C, Alt+Tab), returns realistic timing for all phases of the shortcut execution: how fast the modifier is pressed, how long the main key is held, and which key is released first.

**This user's shortcut characteristics:**
- **97 unique shortcut combinations** learned
- Global median modifier→main delay: **633 ms**
- Global median main key hold: **95 ms**
- Typical release order: main key first (70% of the time)

**Input:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `combo_key` | `str` | Shortcut identifier in format `"mod_scan1,mod_scan2+main_scan"`. Modifier scans sorted ascending, separated by commas, then `+` then main scan. Example: `"29+46"` for Ctrl+C (0x1D=29, 0x2E=46). |
| `rng` | `np.random.Generator` | Optional |

**Output:** Dictionary with timing values:

| Key | Type | Description |
|-----|------|-------------|
| `modifier_to_main_ms` | `float` | Delay from pressing modifier to pressing main key (ms) |
| `main_hold_ms` | `float` | How long the main key is held (ms) |
| `total_ms` | `float` | Total shortcut duration from first press to last release (ms) |
| `release_order` | `str` | `"main_first"` or `"modifier_first"` — which key is released first |

**Example:**

```python
# Ctrl+C: modifier=0x1D (29), main=0x2E (46)
timing = shortcut_model.sample_timing("29+46", rng=rng)
# {
#     "modifier_to_main_ms": 85.3,
#     "main_hold_ms": 72.1,
#     "total_ms": 195.0,
#     "release_order": "main_first"
# }

# Execution sequence:
# t=0ms:    Press Ctrl
# t=85ms:   Press C
# t=157ms:  Release C (main_first)
# t=195ms:  Release Ctrl
```

**Combo key construction:**

```python
import json

# From scan codes:
modifier_scans = [0x1D]  # Ctrl
main_scan = 0x2E          # C
combo_key = ",".join(str(s) for s in sorted(modifier_scans)) + f"+{main_scan}"
# combo_key = "29+46"

# For Ctrl+Shift+S:
modifier_scans = [0x1D, 0x2A]  # Ctrl, Left Shift
main_scan = 0x1F                # S
combo_key = ",".join(str(s) for s in sorted(modifier_scans)) + f"+{main_scan}"
# combo_key = "29,42+31"
```

---

<a id="inference-pipeline--mouse-movement"></a>

## Inference Pipeline — Mouse Movement

Complete example of generating a realistic mouse movement from point A to point B:

```python
import numpy as np
from pathlib import Path
from ml.mouse.path_model import PathModel
from ml.mouse.speed_model import SpeedModel
from ml.mouse.overshoot_model import OvershootModel
from ml.mouse.jitter_model import JitterModel

models_dir = Path("C:/Users/vurun/AppData/Local/InputDNA/db/Uros_Vuruna_1990-06-20/models")
rng = np.random.default_rng()

# Load all mouse models
path_model = PathModel.load(models_dir / "path_generator.pkl")
speed_model = SpeedModel.load(models_dir / "speed_profile.pkl")
overshoot = OvershootModel.load(models_dir / "overshoot_model.pkl")
jitter = JitterModel.load(models_dir / "jitter_params.pkl")

# ── Step 1: Generate base path ──────────────────────────────
start_x, start_y = 100, 100
end_x, end_y = 800, 400

path_x, path_y, raw_dt = path_model.predict(start_x, start_y, end_x, end_y, rng=rng)
# path_x: [100, 100, ..., 800]  (209 points)
# path_y: [100, 99, ..., 400]
# raw_dt: uniform timing (not realistic yet)

# ── Step 2: Apply speed profile ─────────────────────────────
dt_us = speed_model.apply(path_x, path_y, total_duration_us=raw_dt.sum(), rng=rng)
# dt_us: slow at start, fast in middle, slow at end

# ── Step 3: Check for overshoot ─────────────────────────────
distance = np.sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
avg_speed = distance / (dt_us.sum() / 1000)  # px/ms

if overshoot.should_overshoot(distance, avg_speed, rng=rng):
    overshoot_px, correction_ms = overshoot.sample_overshoot(distance, rng=rng)
    # TODO: Extend path past target by overshoot_px, then add correction back
    # This requires path manipulation (extending then appending return segment)

# ── Step 4: Add micro-jitter ────────────────────────────────
jx, jy = jitter.generate_jitter(len(path_x), dt_us, rng=rng)
final_x = np.round(path_x + jx).astype(np.int32)
final_y = np.round(path_y + jy).astype(np.int32)

# ── Result ──────────────────────────────────────────────────
# final_x, final_y: screen coordinates for each point
# dt_us: microseconds between consecutive points
# To replay: move cursor to (final_x[i], final_y[i]), wait dt_us[i+1] µs
```

**Output format for replay:**

Each point in the sequence:
```
Point 0: x=100, y=100, wait=0 µs (starting position)
Point 1: x=100, y=99,  wait=2820 µs
Point 2: x=101, y=98,  wait=1540 µs
...
Point N: x=800, y=400, wait=3464 µs (arrival)
```

---

<a id="inference-pipeline--keyboard-typing"></a>

## Inference Pipeline — Keyboard Typing

Complete example of generating realistic keystroke events for a text string:

```python
import numpy as np
from pathlib import Path
from ml.keyboard.text_model import TextTypingModel
from ml.keyboard.number_model import NumberTypingModel
from ml.keyboard.hold_model import HoldModel

models_dir = Path("C:/Users/vurun/AppData/Local/InputDNA/db/Uros_Vuruna_1990-06-20/models")
rng = np.random.default_rng()

text_model = TextTypingModel.load(models_dir / "text_typing.pkl")
number_model = NumberTypingModel.load(models_dir / "number_typing.pkl")
hold_model = HoldModel.load(models_dir / "key_hold.pkl")

# ── Character to scan code mapping ──────────────────────────
# You need to convert characters to scan codes before using models.
# This mapping depends on keyboard layout. Example for US QWERTY:
CHAR_TO_SCAN = {
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C, ' ': 0x39, '1': 0x02, '2': 0x03, '3': 0x04,
    '4': 0x05, '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09,
    '9': 0x0A, '0': 0x0B,
}

# ── Generate typing events ──────────────────────────────────
text = "hello world"
events = []
prev_scan = None

for char in text.lower():
    scan = CHAR_TO_SCAN.get(char)
    if scan is None:
        continue

    # Inter-key delay
    if prev_scan is not None:
        delay_ms = text_model.sample_delay(prev_scan, scan, rng=rng)
        events.append({"type": "wait", "duration_ms": delay_ms})

    # Key hold duration
    hold_ms = hold_model.sample_duration(scan, rng=rng)

    events.append({"type": "key_down", "scan_code": scan})
    events.append({"type": "wait", "duration_ms": hold_ms})
    events.append({"type": "key_up", "scan_code": scan})

    prev_scan = scan

# ── Result ──────────────────────────────────────────────────
# events = [
#   {"type": "key_down", "scan_code": 0x23},          # Press H
#   {"type": "wait", "duration_ms": 80.8},             # Hold H
#   {"type": "key_up", "scan_code": 0x23},             # Release H
#   {"type": "wait", "duration_ms": 112.5},            # Wait before E
#   {"type": "key_down", "scan_code": 0x12},           # Press E
#   {"type": "wait", "duration_ms": 122.7},            # Hold E
#   {"type": "key_up", "scan_code": 0x12},             # Release E
#   ...
# ]
```

**For numpad numbers:**

```python
# Typing "42" on numpad
NUMPAD_CHAR_TO_SCAN = {
    '0': 0x52, '1': 0x4F, '2': 0x50, '3': 0x51,
    '4': 0x4B, '5': 0x4C, '6': 0x4D,
    '7': 0x47, '8': 0x48, '9': 0x49,
}

# Use number_model instead of text_model:
delay = number_model.sample_delay(0x4B, 0x50, rng=rng)  # 4→2
```

---

<a id="data-summary"></a>

## Data Summary

Training data statistics (from 17 days of recording, Feb 19 — Mar 8, 2026):

| Category | Metric | Value |
|----------|--------|-------|
| **Mouse** | Total movements | 62,929 |
| | Path points | 12,369,641 |
| | Click-ending movements | 27,374 |
| | Overshoot rate | 0.41% |
| | Average speed | 0.286 px/ms |
| | Jitter amplitude | 0.62 px |
| **Keyboard** | Key transitions | 149,697 |
| | Text transitions | 137,975 |
| | Numpad transitions | 5,260 |
| | Code transitions | 1,254 |
| | Total keystrokes | 153,098 |
| | Unique keys | 80 |
| | Shortcuts | 4,617 |
| | Unique shortcuts | 97 |
| | Text digraph pairs | 826 |
| | Numpad digraph pairs | 126 |

---

<a id="scan-code-reference"></a>

## Scan Code Reference

<details>
<summary>Full scan code table (click to expand)</summary>

### Letter Keys (Row by row)

| Scan Code | Key | Keyboard Row |
|-----------|-----|-------------|
| `0x10` | Q | Row 1 |
| `0x11` | W | Row 1 |
| `0x12` | E | Row 1 |
| `0x13` | R | Row 1 |
| `0x14` | T | Row 1 |
| `0x15` | Y | Row 1 |
| `0x16` | U | Row 1 |
| `0x17` | I | Row 1 |
| `0x18` | O | Row 1 |
| `0x19` | P | Row 1 |
| `0x1E` | A | Row 2 |
| `0x1F` | S | Row 2 |
| `0x20` | D | Row 2 |
| `0x21` | F | Row 2 |
| `0x22` | G | Row 2 |
| `0x23` | H | Row 2 |
| `0x24` | J | Row 2 |
| `0x25` | K | Row 2 |
| `0x26` | L | Row 2 |
| `0x2C` | Z | Row 3 |
| `0x2D` | X | Row 3 |
| `0x2E` | C | Row 3 |
| `0x2F` | V | Row 3 |
| `0x30` | B | Row 3 |
| `0x31` | N | Row 3 |
| `0x32` | M | Row 3 |

### Number Row

| Scan Code | Key |
|-----------|-----|
| `0x02` | 1 |
| `0x03` | 2 |
| `0x04` | 3 |
| `0x05` | 4 |
| `0x06` | 5 |
| `0x07` | 6 |
| `0x08` | 7 |
| `0x09` | 8 |
| `0x0A` | 9 |
| `0x0B` | 0 |

### Numpad

| Scan Code | Key |
|-----------|-----|
| `0x52` | Numpad 0 |
| `0x4F` | Numpad 1 |
| `0x50` | Numpad 2 |
| `0x51` | Numpad 3 |
| `0x4B` | Numpad 4 |
| `0x4C` | Numpad 5 |
| `0x4D` | Numpad 6 |
| `0x47` | Numpad 7 |
| `0x48` | Numpad 8 |
| `0x49` | Numpad 9 |
| `0x53` | Numpad . |
| `0xE01C` | Numpad Enter |
| `0xE035` | Numpad / |
| `0x37` | Numpad * |
| `0x4A` | Numpad - |
| `0x4E` | Numpad + |

### Modifiers

| Scan Code | Key |
|-----------|-----|
| `0x1D` | Left Ctrl |
| `0xE01D` | Right Ctrl |
| `0x38` | Left Alt |
| `0xE038` | Right Alt |
| `0x2A` | Left Shift |
| `0x36` | Right Shift |
| `0x5B` | Left Win |
| `0x5C` | Right Win |

### Special Keys

| Scan Code | Key |
|-----------|-----|
| `0x39` | Space |
| `0x1C` | Enter |
| `0x0F` | Tab |
| `0x0E` | Backspace |
| `0x01` | Escape |
| `0x3A` | Caps Lock |

</details>

---

<a id="file-sizes"></a>

## File Sizes

| Model | File | Size | Load Time |
|-------|------|------|-----------|
| Path Generator | `path_generator.pkl` | 174 MB | ~2s |
| Speed Profile | `speed_profile.pkl` | 1.5 KB | instant |
| Overshoot | `overshoot_model.pkl` | 891 B | instant |
| Jitter | `jitter_params.pkl` | 97 B | instant |
| Text Typing | `text_typing.pkl` | 22 KB | instant |
| Number Typing | `number_typing.pkl` | 3.4 KB | instant |
| Key Hold | `key_hold.pkl` | 1.9 KB | instant |
| Shortcuts | `shortcuts.pkl` | 9.2 KB | instant |
| **Total** | | **~174 MB** | ~2s |

> **Note:** Path Generator is 99.9% of the total size because it stores 62,929 full normalized paths. Future optimization: cluster similar paths and store only representatives.

---

<a id="limitations-and-future-work"></a>

## Limitations and Future Work

### Current Limitations

1. **Path Generator outputs uniform timing** — must apply SpeedModel separately. The two models are decoupled by design but the caller must compose them correctly.

2. **Overshoot is detected but not auto-injected** — the caller must extend the path manually if `should_overshoot()` returns True. The overshoot path segment generation is not yet implemented.

3. **No burst/pause rhythm model** — the current keyboard models treat each transition independently. In reality, users type in bursts (fast sequences) with pauses between words/thoughts. A Hidden Markov Model for this is planned but not yet implemented.

4. **No fatigue model** — typing and mouse speed change over hours of use (slower, less accurate). Currently not modeled.

5. **No uppercase handling in text model** — the model works at scan-code level. For uppercase letters, the caller must insert Shift press/release events manually around the letter.

6. **Path Generator file is large (174 MB)** — stores all recorded paths. Can be reduced to ~10 MB by clustering and keeping only representative paths.

### Planned Improvements

| Improvement | Impact | Effort |
|-------------|--------|--------|
| Burst/pause HMM for typing rhythm | High — makes typing sound natural | Medium |
| VAE path generator (PyTorch) | High — infinite path variation | High |
| Path clustering to reduce model size | Medium — 174MB → ~10MB | Low |
| Fatigue modifier over time | Medium — more realistic long sessions | Low |
| Error injection (typos + corrections) | Medium — very human-like | Medium |
| Time-of-day adjustments | Low — subtle realism | Low |

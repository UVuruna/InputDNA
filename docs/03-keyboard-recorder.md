# Keyboard Input Recorder - Project Specification

## Overview

Extension of the mouse recorder to capture **personal keyboard input patterns**. The goal is to build a database that enables ML-based replication of your unique typing style — speed, rhythm, delays, shortcuts, and error patterns.

Combined with mouse data, this creates a complete **human input fingerprint**.

---

## Core Concept

Every person types differently:
- Different speeds for different key combinations
- Unique rhythm patterns
- Personal shortcut execution style
- Characteristic error/correction behavior

We capture ALL of this to later replay typing that is indistinguishable from your real input.

---

## Typing Contexts (Modes)

Different typing situations have completely different patterns. We must categorize and store them separately.

### 1. **Regular Text**
- Prose, sentences, natural language
- Flow typing with rhythm
- Spaces, punctuation integrated

### 2. **Keyboard Shortcuts**
- Ctrl+C, Ctrl+V, Ctrl+Z, Ctrl+S
- Alt+Tab, Alt+F4
- Win+D, Win+E
- Multi-modifier: Ctrl+Shift+Esc

### 3. **Numbers - Main Keyboard**
- Top row numbers (1-9, 0)
- Often mixed with Shift for symbols
- Different hand position than letters

### 4. **Numbers - Numpad**
- Right hand dedicated
- Usually faster for number sequences
- Different rhythm than main keyboard

### 5. **Programming/Code**
- Brackets: () [] {} <>
- Operators: = + - * / % 
- Special: ; : ' " ` ~ @ # $ 
- Mixed alphanumeric: variable names

### 6. **URLs / Emails**
- Specific patterns: www. .com .org @
- Slash / dot heavy
- Often memorized sequences

### 7. **Passwords**
- We do NOT store actual passwords
- But pattern of: letters → numbers → symbols
- Shift usage for capitals

### 8. **Function Keys**
- F1-F12
- Often with modifiers
- Usually isolated presses

### 9. **Navigation**
- Arrow keys
- Home, End, Page Up/Down
- Often in sequences

---

## Database Schema

### Tables

#### `keystrokes` — Individual key events

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Event ID |
| `session_id` | INTEGER FK | Recording session |
| `sequence_id` | INTEGER FK | Which typing sequence this belongs to |
| `key_code` | INTEGER | Virtual key code |
| `key_name` | TEXT | Human-readable key name |
| `event_type` | TEXT | `press` or `release` |
| `press_duration_ms` | INTEGER | How long key was held (set on release) |
| `timestamp_ms` | INTEGER | Ms since session start |
| `modifier_state` | TEXT | JSON: which modifiers were active |
| `hand` | TEXT | `left`, `right`, `both` (inferred) |
| `finger` | TEXT | Which finger likely used (inferred) |

#### `key_transitions` — Timing between consecutive keys

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Transition ID |
| `session_id` | INTEGER FK | Recording session |
| `from_key` | TEXT | Previous key name |
| `to_key` | TEXT | Next key name |
| `delay_ms` | INTEGER | Time between releases/presses |
| `transition_type` | TEXT | `press_to_press`, `release_to_press` |
| `typing_mode` | TEXT | Context: `text`, `shortcut`, `numpad`, etc. |
| `timestamp` | DATETIME | When this occurred |

#### `digraph_stats` — Aggregated key pair statistics

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Stat ID |
| `from_key` | TEXT | First key |
| `to_key` | TEXT | Second key |
| `typing_mode` | TEXT | Context |
| `sample_count` | INTEGER | How many times recorded |
| `avg_delay_ms` | REAL | Average delay |
| `min_delay_ms` | INTEGER | Fastest recorded |
| `max_delay_ms` | INTEGER | Slowest recorded |
| `stddev_ms` | REAL | Variation |

#### `typing_sequences` — Grouped typing sessions

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Sequence ID |
| `session_id` | INTEGER FK | Recording session |
| `typing_mode` | TEXT | Detected mode |
| `started_at` | DATETIME | When sequence started |
| `ended_at` | DATETIME | When sequence ended |
| `total_keys` | INTEGER | Keys in sequence |
| `duration_ms` | INTEGER | Total duration |
| `avg_speed_cpm` | REAL | Characters per minute |
| `error_count` | INTEGER | Backspaces used |
| `had_shortcuts` | BOOLEAN | Contained shortcuts |

#### `shortcuts` — Keyboard shortcut patterns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Shortcut ID |
| `session_id` | INTEGER FK | Recording session |
| `shortcut_name` | TEXT | e.g., "Ctrl+C", "Alt+Tab" |
| `modifier_keys` | TEXT | JSON array of modifiers |
| `main_key` | TEXT | The non-modifier key |
| `modifier_press_time_ms` | INTEGER | When modifier was pressed |
| `main_key_delay_ms` | INTEGER | Delay after modifier to main key |
| `modifier_release_delay_ms` | INTEGER | When modifier released after main key |
| `overlap_ms` | INTEGER | How long both were held together |
| `total_duration_ms` | INTEGER | Full shortcut execution time |
| `timestamp` | DATETIME | When executed |

#### `error_corrections` — Backspace/delete patterns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Correction ID |
| `session_id` | INTEGER FK | Recording session |
| `sequence_id` | INTEGER FK | Which sequence |
| `error_position` | INTEGER | How many chars before backspace |
| `keys_deleted` | INTEGER | How many backspaces in a row |
| `reaction_time_ms` | INTEGER | Time from last char to first backspace |
| `correction_speed_ms` | REAL | Avg delay between backspaces |
| `timestamp` | DATETIME | When correction occurred |

#### `key_hold_stats` — Per-key press duration statistics

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Stat ID |
| `key_name` | TEXT | Key |
| `typing_mode` | TEXT | Context |
| `sample_count` | INTEGER | Times recorded |
| `avg_duration_ms` | REAL | Average hold time |
| `min_duration_ms` | INTEGER | Shortest |
| `max_duration_ms` | INTEGER | Longest |
| `stddev_ms` | REAL | Variation |

#### `burst_patterns` — Typing rhythm analysis

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Pattern ID |
| `session_id` | INTEGER FK | Recording session |
| `sequence_id` | INTEGER FK | Which sequence |
| `burst_length` | INTEGER | Keys typed in burst |
| `burst_duration_ms` | INTEGER | Duration of burst |
| `pause_after_ms` | INTEGER | Pause before next burst |
| `avg_key_delay_ms` | REAL | Speed within burst |

#### `numpad_vs_main` — Comparison data for numbers

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Record ID |
| `digit` | TEXT | 0-9 |
| `input_source` | TEXT | `numpad` or `main` |
| `sample_count` | INTEGER | Times used |
| `avg_press_duration_ms` | REAL | Hold time |
| `avg_transition_delay_ms` | REAL | Delay to next key |

---

## Key Detection & Classification

### Modifier Key Handling

```
Modifier pressed (timestamp: T1)
    ↓
Main key pressed (timestamp: T2)
    ↓
Main key released (timestamp: T3)
    ↓
Modifier released (timestamp: T4)

Metrics:
- modifier_hold_before = T2 - T1
- main_key_duration = T3 - T2
- modifier_hold_after = T4 - T3
- total_shortcut_time = T4 - T1
- overlap_time = T3 - T2 (both held)
```

### Typing Mode Detection

Heuristics to classify current typing context:

| Indicator | Likely Mode |
|-----------|-------------|
| Only numpad keys | `numpad` |
| Modifier + single key | `shortcut` |
| Continuous letters + space | `text` |
| Brackets, operators | `code` |
| F1-F12 | `function` |
| Arrows, Home/End | `navigation` |
| Contains @ and . | `email` |
| Contains :// or www | `url` |

### Hand & Finger Inference

Based on standard QWERTY layout:

**Left hand:**
- Pinky: Q, A, Z, 1, Tab, Caps, Shift
- Ring: W, S, X, 2
- Middle: E, D, C, 3
- Index: R, T, F, G, V, B, 4, 5

**Right hand:**
- Index: Y, U, H, J, N, M, 6, 7
- Middle: I, K, 8, comma
- Ring: O, L, 9, period
- Pinky: P, ;, /, 0, -, =, Backspace, Enter

This allows per-finger timing analysis.

---

## Privacy Considerations

### What we DO store:
- Key codes and names
- Timing between keys
- Duration of presses
- Sequence patterns

### What we DO NOT store:
- Actual text content / words typed
- Password content
- Sensitive data reconstruction

### Implementation:
- Store individual keystrokes for timing
- Do NOT concatenate into readable text
- Auto-purge raw keystroke data after aggregating stats (optional)

---

## Derived Metrics

### Per-Key Metrics
| Metric | Description |
|--------|-------------|
| `avg_press_duration` | How long you hold this key |
| `press_variance` | Consistency of hold time |

### Per-Digraph Metrics
| Metric | Description |
|--------|-------------|
| `avg_transition_time` | Your speed for this key pair |
| `same_hand_penalty` | Slower when both keys same hand? |
| `same_finger_penalty` | Much slower when same finger? |

### Per-Mode Metrics
| Metric | Description |
|--------|-------------|
| `chars_per_minute` | Typing speed in context |
| `error_rate` | Backspaces per 100 chars |
| `burst_pattern` | Average burst length and pause |

### Shortcut Metrics
| Metric | Description |
|--------|-------------|
| `execution_time` | Full shortcut duration |
| `modifier_timing` | Your Ctrl/Alt/Shift style |
| `release_pattern` | Order of key releases |

---

## Python Implementation Notes

### Key Capture

```python
from pynput import keyboard

# Track press times for duration calculation
press_times = {}

def on_press(key):
    key_name = get_key_name(key)
    press_times[key_name] = time.time()
    # Record press event
    
def on_release(key):
    key_name = get_key_name(key)
    if key_name in press_times:
        duration = time.time() - press_times[key_name]
        # Record release event with duration
        del press_times[key_name]
```

### Modifier State Tracking

```python
modifier_state = {
    'ctrl': False,
    'alt': False,
    'shift': False,
    'win': False
}

def update_modifier_state(key, pressed):
    if key == Key.ctrl_l or key == Key.ctrl_r:
        modifier_state['ctrl'] = pressed
    # ... etc
```

### Shortcut Detection

```python
def is_shortcut():
    return any(modifier_state.values())

def get_current_shortcut(main_key):
    mods = [k for k, v in modifier_state.items() if v]
    return '+'.join(mods + [main_key])
```

---

## Integration with Mouse Recorder

### Shared Components
- Same SQLite database file
- Same recording session management
- Shared timestamp base
- Combined fatigue tracking

### Cross-Analysis
- Keyboard → Mouse transition times (already planned)
- Mouse → Keyboard transition times
- Combined input rhythm patterns

### Unified Architecture

```
input-recorder/
├── main.py
├── listeners/
│   ├── mouse.py
│   └── keyboard.py      # NEW
├── analysis/
│   ├── mouse/
│   │   ├── session.py
│   │   ├── clicks.py
│   │   └── metrics.py
│   └── keyboard/        # NEW
│       ├── sequences.py
│       ├── shortcuts.py
│       ├── digraphs.py
│       └── errors.py
├── database/
│   ├── schema.py        # Extended
│   └── writer.py
├── movements.db         # Combined database
└── README.md
```

---

## MVP Checklist

### Phase 1 — Core Recording
- [ ] Key press/release capture
- [ ] Press duration tracking
- [ ] Basic transition timing
- [ ] Modifier state tracking
- [ ] Database schema implementation

### Phase 2 — Mode Detection
- [ ] Shortcut detection & logging
- [ ] Numpad vs main keyboard differentiation
- [ ] Typing mode classification
- [ ] Sequence grouping

### Phase 3 — Analysis
- [ ] Digraph statistics aggregation
- [ ] Error pattern detection
- [ ] Burst rhythm analysis
- [ ] Hand/finger inference

### Phase 4 — Integration
- [ ] Combined mouse+keyboard sessions
- [ ] Cross-input transition analysis
- [ ] Unified fatigue tracking

---

## Future ML Application

The captured data enables:

### 1. **Digraph-Based Replay**
Given text to type, look up your personal timing for each key pair.

### 2. **Mode-Aware Timing**
Apply different timing models for text vs code vs shortcuts.

### 3. **Error Injection**
Occasionally make realistic typos and corrections based on your error patterns.

### 4. **Rhythm Replication**
Reproduce your burst-pause patterns, not just individual delays.

### 5. **Shortcut Authenticity**
Execute shortcuts with your exact modifier timing signature.

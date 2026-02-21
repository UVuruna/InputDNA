# Schema Optimization — Storage Reduction Plan

## Table of Contents

- [Context](#context)
- [Storage Analysis](#storage-analysis)
- [Design Principles](#design-principles)
- [New Schema — Table by Table](#new-schema--table-by-table)
  - [mouse.db — movements](#mousedb--movements)
  - [mouse.db — path\_points](#mousedb--path_points)
  - [mouse.db — drag\_points](#mousedb--drag_points)
  - [mouse.db — drags](#mousedb--drags)
  - [mouse.db — click\_sequences](#mousedb--click_sequences)
  - [mouse.db — click\_details](#mousedb--click_details)
  - [mouse.db — scrolls](#mousedb--scrolls)
  - [keyboard.db — keystrokes](#keyboarddb--keystrokes)
  - [keyboard.db — key\_transitions](#keyboarddb--key_transitions)
  - [keyboard.db — shortcuts](#keyboarddb--shortcuts)
- [Reconstruction Guide](#reconstruction-guide)
- [Implementation Scope](#implementation-scope)

---

<a id="context"></a>

## Context

After 12.6 hours of recording, mouse.db reached **71.75 MB**.
Projected growth rate: **~5.7 MB/h → ~1 GB/month** at an 8-hour workday.

Root cause analysis:

| Table | Rows | Dominant cost |
|-------|------|---------------|
| `path_points` | 3.1M | `id` (8B × 3.1M = 24MB) + `t_ns` (4B × 3.1M = 12MB) |
| `drag_points` | 262K | Same structure as path_points |
| `keystrokes` | 34K | `modifier_state` JSON string (~62B per row vs 1B bitmask) |

The original schema stores several categories of redundant data:

1. **Auto-increment `id` columns** on path_points and drag_points — these tables already have a natural composite key `(movement_id, seq)` or `(drag_id, seq)`.
2. **Per-point absolute timestamps** (`t_ns`) on path_points and drag_points — replaced with compact `dt_us` (delta microseconds from previous point), which preserves the actual velocity profile at ~2 bytes per point instead of 8.
3. **Computed/derivable columns** — distance, path_length, point_count, hour_of_day, day_of_week, delay_since_prev_ms, direction, key_name, hand, finger, etc.
4. **JSON modifier state** — stored as a ~62-byte text string instead of a 4-bit integer bitmask.

---

<a id="storage-analysis"></a>

## Storage Analysis

### Why `dt_us` per path_point instead of absolute `t_ns`

`WH_MOUSE_LL` fires an event only when the cursor position changes (integer pixel). At 500 Hz, the OS sends a hardware poll every 2ms, but our hook callback only fires if `x` or `y` actually changed. A slow, deliberate movement may produce only 10 position changes in 231ms — those 10 events are spread non-uniformly across the time window.

This means the velocity profile (acceleration → peak speed → deceleration) is encoded in the **timing between consecutive position changes**, not just in the spatial deltas. A uniform interpolation from start/end would make every movement look like constant-speed motion — robotic, not human.

**`dt_us`** stores the actual elapsed microseconds since the previous point:
- `seq=0`: `dt_us=0` (timing anchored by `start_t_ns` in the parent movement)
- `seq>0`: `dt_us = (t_ns[i] - t_ns[i-1]) // 1000`

Full timing reconstruction:
```
t_ns[0] = start_t_ns
t_ns[i] = t_ns[i-1] + dt_us[i] * 1000
```

**Why not keep absolute `t_ns`?** Delta encoding is far more compact. At 500 Hz, typical `dt_us ≈ 2000` → 2 bytes in SQLite varint. Absolute `t_ns` values (~1.7×10¹⁸) always require 8 bytes.

**WH_MOUSE_LL jitter:** `perf_counter_ns()` is called at callback time, so each timestamp includes OS scheduling latency (±100–500 µs). This jitter is present in both consecutive timestamps, so the delta partially cancels it — the velocity shape is preserved even with per-point noise.

---

<a id="design-principles"></a>

## Design Principles

**Keep only what is:**
1. Not derivable in post-processing, OR
2. Too expensive to derive (requires full table scan per record)

**Remove if:**
- Computable from other columns in the same or related table
- Redundant with information already encoded in the primary key
- OS noise rather than behavioral signal

**Keystone change — `path_points` and `drag_points`:**

Remove `id` (auto-increment) and use `(movement_id, seq)` as composite primary key.
Replace absolute `t_ns` with `dt_us` (delta microseconds from previous point).
Result: 5 columns instead of 6, similar row size but with actual velocity profile preserved.

**Modifier state encoding:**

Old: `TEXT` — `{"ctrl": false, "alt": false, "shift": false, "win": false}` — **~62 bytes**
New: `INTEGER` bitmask — **1–2 bytes**

```
Bit 0 (value 1) = Ctrl
Bit 1 (value 2) = Alt
Bit 2 (value 4) = Shift
Bit 3 (value 8) = Win
```

Examples: `0` = no modifiers, `4` = Shift only, `5` = Ctrl+Shift, `15` = all four.

---

<a id="new-schema--table-by-table"></a>

## New Schema — Table by Table

---

<a id="mousedb--movements"></a>

### mouse.db — `movements`

**Primary key:** App-generated `id = session_id × 1_000_000 + seq_within_session`.
This encodes the session directly — `recording_session_id` is redundant and removed.

```sql
CREATE TABLE movements (
    id          INTEGER PRIMARY KEY,   -- session_id * 1_000_000 + seq
    start_x     INTEGER NOT NULL,
    start_y     INTEGER NOT NULL,
    end_x       INTEGER NOT NULL,
    end_y       INTEGER NOT NULL,
    end_event   TEXT    NOT NULL,      -- 'left_click' | 'right_click' | 'idle'
    start_t_ns  INTEGER NOT NULL,      -- perf_counter_ns at movement start
    end_t_ns    INTEGER NOT NULL,      -- perf_counter_ns at movement end
    timestamp   TEXT    NOT NULL       -- wall clock ISO, human readability only
);
```

**Removed columns and why:**

| Removed | Derivation |
|---------|-----------|
| `recording_session_id` | `id // 1_000_000` |
| `duration_ms` | `(end_t_ns - start_t_ns) / 1_000_000` |
| `distance_px` | `sqrt((end_x - start_x)² + (end_y - start_y)²)` |
| `path_length_px` | Sum of Euclidean distances between consecutive path_points |
| `point_count` | `SELECT COUNT(*) FROM path_points WHERE movement_id = ?` |
| `hour_of_day` | `datetime.fromisoformat(timestamp).hour` |
| `day_of_week` | `datetime.fromisoformat(timestamp).weekday()` |

**Added columns:**

| Added | Purpose |
|-------|---------|
| `start_t_ns` | Anchor for path_point timing reconstruction |
| `end_t_ns` | Anchor for path_point timing reconstruction |

---

<a id="mousedb--path_points"></a>

### mouse.db — `path_points`

**Primary key:** Composite `(movement_id, seq)` — no separate `id` column.

```sql
CREATE TABLE path_points (
    movement_id  INTEGER NOT NULL REFERENCES movements(id),
    seq          INTEGER NOT NULL,
    x            INTEGER NOT NULL,   -- delta from previous point (seq > 0), absolute for seq = 0
    y            INTEGER NOT NULL,   -- delta from previous point (seq > 0), absolute for seq = 0
    dt_us        INTEGER NOT NULL,   -- µs since previous point; seq=0 always 0
    PRIMARY KEY (movement_id, seq)
);
```

**Removed columns:**

| Removed | Replaced by |
|---------|-----------|
| `id` | `(movement_id, seq)` is a unique natural key |
| `t_ns` (absolute) | `dt_us` delta — compact and preserves velocity profile |

**Delta encoding:** `seq = 0` stores absolute `(x, y)`, `dt_us=0`. All subsequent rows store `(Δx, Δy)` and `dt_us = µs since previous point`. Small integer deltas use 1–2 bytes in SQLite's variable-length integer encoding.

**Timing reconstruction:** `t_ns[0] = start_t_ns`, `t_ns[i] = t_ns[i-1] + dt_us[i] * 1000`

> **Metadata key `path_encoding`** in mouse.db metadata table is updated to `delta_v3` to signal the new `dt_us` column to post-processing readers.

---

<a id="mousedb--drag_points"></a>

### mouse.db — `drag_points`

Same optimization as path_points.

```sql
CREATE TABLE drag_points (
    drag_id  INTEGER NOT NULL REFERENCES drags(id),
    seq      INTEGER NOT NULL,
    x        INTEGER NOT NULL,   -- delta from previous point (seq > 0), absolute for seq = 0
    y        INTEGER NOT NULL,   -- delta from previous point (seq > 0), absolute for seq = 0
    dt_us    INTEGER NOT NULL,   -- µs since previous point; seq=0 always 0
    PRIMARY KEY (drag_id, seq)
);
```

**Removed:** `id`. Absolute `t_ns` replaced with `dt_us`. Timing reconstruction: `t_ns[0]=drags.start_t_ns`, `t_ns[i]=t_ns[i-1]+dt_us[i]*1000`.

---

<a id="mousedb--drags"></a>

### mouse.db — `drags`

Same session-prefix ID scheme as movements: `session_id × 1_000_000 + seq`.
This also solves the current problem: drags have **no session linkage** in the existing schema.

```sql
CREATE TABLE drags (
    id          INTEGER PRIMARY KEY,   -- session_id * 1_000_000 + seq
    button      TEXT    NOT NULL,
    start_x     INTEGER NOT NULL,
    start_y     INTEGER NOT NULL,
    start_t_ns  INTEGER NOT NULL,
    end_t_ns    INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `end_x, end_y` | `start_x + Σ(delta_x)`, `start_y + Σ(delta_y)` across drag_points |
| `duration_ms` | `(end_t_ns - start_t_ns) / 1_000_000` |
| `point_count` | `SELECT COUNT(*) FROM drag_points WHERE drag_id = ?` |

---

<a id="mousedb--click_sequences"></a>

### mouse.db — `click_sequences`

```sql
CREATE TABLE click_sequences (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id  INTEGER REFERENCES movements(id),
    button       TEXT    NOT NULL
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `click_count` | `SELECT COUNT(*) FROM click_details WHERE sequence_id = ?` |
| `total_duration_ms` | From `click_details`: last `t_ns` + `press_duration_ms` − first `t_ns` |
| `x, y` | Identical to `movements.end_x, end_y` (click always at movement endpoint) |
| `timestamp` | `datetime` derivable from first `click_details.t_ns` |

---

<a id="mousedb--click_details"></a>

### mouse.db — `click_details`

**Primary key:** Composite `(sequence_id, seq)` — no separate `id`.

```sql
CREATE TABLE click_details (
    sequence_id       INTEGER NOT NULL REFERENCES click_sequences(id),
    seq               INTEGER NOT NULL,
    press_duration_ms REAL    NOT NULL,
    t_ns              INTEGER NOT NULL,   -- absolute, not delta — each click is discrete
    PRIMARY KEY (sequence_id, seq)
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `id` | `(sequence_id, seq)` is unique |
| `x, y` | Same as `click_sequences.movement_id → movements.end_x/end_y` |
| `delay_since_prev_ms` | `(t_ns[seq] - t_ns[seq-1]) / 1_000_000` |

> **Note:** `t_ns` is kept here (unlike path_points) because clicks are discrete events with genuine timing variability — double-click speed is a core behavioral fingerprint.

---

<a id="mousedb--scrolls"></a>

### mouse.db — `scrolls`

```sql
CREATE TABLE scrolls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id  INTEGER REFERENCES movements(id),
    delta        INTEGER NOT NULL,   -- +1 = one notch up, -1 = one notch down
    x            INTEGER NOT NULL,
    y            INTEGER NOT NULL,
    t_ns         INTEGER NOT NULL    -- absolute — discrete event
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `direction` | `"up" if delta > 0 else "down"` |
| `timestamp` | Derivable from `t_ns` using session wall-clock anchor |

> **Note:** `t_ns` is kept for scrolls. Each scroll notch is a discrete event with genuine timing signal (scroll rhythm is behavioral).

---

<a id="keyboarddb--keystrokes"></a>

### keyboard.db — `keystrokes`

```sql
CREATE TABLE keystrokes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_code         INTEGER NOT NULL,
    press_duration_ms REAL    NOT NULL,
    modifier_state    INTEGER NOT NULL,   -- bitmask: bit0=Ctrl, bit1=Alt, bit2=Shift, bit3=Win
    t_ns              INTEGER NOT NULL
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `vkey` | `MapVirtualKey(scan_code)` using layout from `session.db system_events` |
| `key_name` | Lookup table from scan_code |
| `hand` | Lookup table from scan_code |
| `finger` | Lookup table from scan_code |
| `active_layout` | Stored once per change in `session.db system_events` (already tracked) |
| `timestamp` | Derivable from `t_ns` using session wall-clock anchor |

**Changed:**

| Column | Old | New |
|--------|-----|-----|
| `modifier_state` | `TEXT` JSON ~62B | `INTEGER` bitmask ~1B |

**Bitmask encoding:**
```python
modifier_state = (
    (1 if ctrl  else 0) |
    (2 if alt   else 0) |
    (4 if shift else 0) |
    (8 if win   else 0)
)
```

**Bitmask decoding in post-processing:**
```python
ctrl  = bool(modifier_state & 1)
alt   = bool(modifier_state & 2)
shift = bool(modifier_state & 4)
win   = bool(modifier_state & 8)
```

---

<a id="keyboarddb--key_transitions"></a>

### keyboard.db — `key_transitions`

```sql
CREATE TABLE key_transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scan   INTEGER NOT NULL,
    to_scan     INTEGER NOT NULL,
    typing_mode TEXT    NOT NULL,
    t_ns        INTEGER NOT NULL
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `from_key_name` | Lookup from `from_scan` |
| `to_key_name` | Lookup from `to_scan` |
| `delay_ms` | `(keystrokes[n+1].t_ns - keystrokes[n].t_ns) / 1_000_000` |

---

<a id="keyboarddb--shortcuts"></a>

### keyboard.db — `shortcuts`

```sql
CREATE TABLE shortcuts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    modifier_scans      TEXT    NOT NULL,   -- JSON array of scan codes, e.g. [42]
    main_scan           INTEGER NOT NULL,
    modifier_to_main_ms REAL    NOT NULL,
    main_hold_ms        REAL    NOT NULL,
    overlap_ms          REAL    NOT NULL,
    total_ms            REAL    NOT NULL,
    release_order       TEXT    NOT NULL,   -- 'main_first' | 'modifier_first'
    t_ns                INTEGER NOT NULL
);
```

**Removed:**

| Removed | Derivation |
|---------|-----------|
| `shortcut_name` | Construct from `modifier_scans` + `main_scan` + active layout |
| `main_key_name` | Lookup from `main_scan` |
| `timestamp` | Derivable from `t_ns` |

---

<a id="reconstruction-guide"></a>

## Reconstruction Guide

Complete reference for post-processing to derive any removed column.

### Timing reconstruction

```python
# Wall clock from t_ns (for any table)
# Anchor: recording_sessions.perf_counter_start_ns + started_at (wall clock)
def t_ns_to_wall_clock(t_ns, session):
    offset_ns = t_ns - session.perf_counter_start_ns
    return datetime.fromisoformat(session.started_at) + timedelta(microseconds=offset_ns / 1000)

# Path point timing (path_points and drag_points)
# dt_us is stored per point (seq=0 has dt_us=0, anchored by start_t_ns)
def path_point_times(movement, path_points):
    t_ns = movement.start_t_ns
    times = [t_ns]
    for pt in path_points[1:]:
        t_ns += pt.dt_us * 1000
        times.append(t_ns)
    return times
```

### Mouse derivations

```python
# movements
recording_session_id = movement_id // 1_000_000
duration_ns          = end_t_ns - start_t_ns
duration_ms          = duration_ns / 1_000_000
distance_px          = sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
hour_of_day          = datetime.fromisoformat(timestamp).hour
day_of_week          = datetime.fromisoformat(timestamp).weekday()

# path_points — reconstruct absolute positions from delta encoding
# seq=0: absolute. seq>0: accumulate deltas
abs_x, abs_y = path_points[0].x, path_points[0].y
for pt in path_points[1:]:
    abs_x += pt.x
    abs_y += pt.y

# path_length_px
path_length = sum(sqrt(pt.x**2 + pt.y**2) for pt in path_points[1:])

# point_count
point_count = SELECT COUNT(*) FROM path_points WHERE movement_id = ?

# click_sequences
click_count       = SELECT COUNT(*) FROM click_details WHERE sequence_id = ?
x, y              = movements.end_x, movements.end_y  (via movement_id)
total_duration_ms = (last_detail.t_ns + last_detail.press_duration_ms*1e6 - first_detail.t_ns) / 1e6

# click_details
delay_since_prev_ms = (t_ns[seq] - t_ns[seq-1]) / 1_000_000   # 0 for seq=0

# drags
end_x       = start_x + sum(pt.x for pt in drag_points)   # delta-encoded
end_y       = start_y + sum(pt.y for pt in drag_points)
duration_ms = (end_t_ns - start_t_ns) / 1_000_000
point_count = SELECT COUNT(*) FROM drag_points WHERE drag_id = ?

# scrolls
direction = "up" if delta > 0 else "down"
```

### Keyboard derivations

```python
# keystrokes — modifier_state bitmask decoding
ctrl  = bool(modifier_state & 1)
alt   = bool(modifier_state & 2)
shift = bool(modifier_state & 4)
win   = bool(modifier_state & 8)

# key_name, hand, finger — from scan_code lookup table (utils/keyboard_layout.py)
from utils.keyboard_layout import SCAN_CODE_MAP
key_name = SCAN_CODE_MAP[scan_code]['name']
hand     = SCAN_CODE_MAP[scan_code]['hand']
finger   = SCAN_CODE_MAP[scan_code]['finger']

# active_layout — from session.db system_events
# Query: SELECT value FROM system_events WHERE key='keyboard_layout' AND t_ns <= keystroke.t_ns ORDER BY t_ns DESC LIMIT 1

# key_transitions
delay_ms = (keystrokes[n+1].t_ns - keystrokes[n].t_ns) / 1_000_000

# shortcuts
main_key_name  = SCAN_CODE_MAP[main_scan]['name']
shortcut_name  = "+".join([SCAN_CODE_MAP[s]['name'] for s in modifier_scans] + [main_key_name])
```

---

<a id="implementation-scope"></a>

## Implementation Scope

Files that must change when implementing this schema:

| File | Change |
|------|--------|
| `database/schema.py` | New `CREATE TABLE` statements for all tables |
| `models/sessions.py` | Update all `write_to_db()` methods + dataclass fields |
| `processors/mouse_session.py` | Remove computed fields, add `start_t_ns`/`end_t_ns` |
| `processors/click_processor.py` | Remove `x, y, timestamp, click_count, total_duration_ms` |
| `processors/drag_detector.py` | Session-prefix ID for drags, add `start_t_ns`/`end_t_ns` |
| `processors/keyboard_processor.py` | Encode `modifier_state` as bitmask, remove derived fields |
| `database/__database.md` | Schema reference update (separate doc) |
| `models/__models.md` | Update record class descriptions |

**Not changed:** `listeners/`, `utils/`, `ui/`, `main.py`, `config.py`

**Existing databases:** Schema change is **not backward compatible**. Existing `.db` files use the old schema. New databases created after implementation will use the new schema. Old databases remain readable with the old schema — post-processing must detect schema version via the `path_encoding` metadata key (`delta_v1` = old, `delta_v2` = intermediate, `delta_v3` = current with `dt_us`).

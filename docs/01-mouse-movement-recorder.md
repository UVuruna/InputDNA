# Mouse Movement Recorder - Project Specification

## Overview

A background Python application that continuously records personal mouse movement patterns to build a database for future ML-based human-like mouse movement simulation.

The goal is to capture **your unique movement fingerprint** — how you personally move the mouse — so it can later be replicated programmatically in automation systems.

---

## Core Concepts

### Movement Session

A **movement session** is defined as:

- **Start Point**: First detected mouse movement after idle period (user grabs the mouse)
- **End Point**: A mouse interaction event occurs:
  - Left click
  - Right click
  - Middle click
  - Scroll (up, down, left, right)
  - Drag start/end
- **Path Data**: All coordinates and timestamps between start and end

### Idle Detection

The system must distinguish between:
- **Pause during movement** (brief hesitation while moving)
- **True idle** (user released the mouse)

Suggested threshold: `150-300ms` of no movement = session end candidate, confirmed by next movement being a "new grab" or timeout.

---

## Database Schema

### Technology
SQLite (lightweight, no server needed, portable `.db` file)

### Tables

#### `movements` — Main movement sessions

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Unique session ID |
| `start_x` | INTEGER | Starting X coordinate |
| `start_y` | INTEGER | Starting Y coordinate |
| `end_x` | INTEGER | Ending X coordinate |
| `end_y` | INTEGER | Ending Y coordinate |
| `end_event` | TEXT | What ended the session: `left_click`, `right_click`, `middle_click`, `scroll_up`, `scroll_down`, `drag_start` |
| `duration_ms` | INTEGER | Total movement duration in milliseconds |
| `distance_px` | REAL | Euclidean distance (straight line) |
| `path_length_px` | REAL | Actual traveled distance (sum of segments) |
| `point_count` | INTEGER | Number of recorded path points |
| `avg_speed` | REAL | Average speed (px/ms) |
| `max_speed` | REAL | Maximum speed during movement |
| `curvature_ratio` | REAL | path_length / distance (1.0 = straight line) |
| `direction_angle` | REAL | atan2(Δy, Δx) — general direction |
| `has_overshoot` | BOOLEAN | Did path overshoot and correct? |
| `overshoot_distance` | REAL | How far past target before correction |
| `pre_click_pause_ms` | INTEGER | Time hovering on target before click |
| `pre_click_jitter_px` | REAL | Micro-movement amplitude while hovering |
| `timestamp` | DATETIME | When session started |
| `hour_of_day` | INTEGER | 0-23, for time patterns |
| `day_of_week` | INTEGER | 0-6, for weekly patterns |
| `session_duration_min` | INTEGER | How long recording has been active (fatigue) |
| `ms_since_last_keypress` | INTEGER | Keyboard→mouse transition timing |
| `prev_movement_id` | INTEGER FK | Link to previous movement (chains) |
| `screen_width` | INTEGER | Screen resolution |
| `screen_height` | INTEGER | Screen resolution |

#### `path_points` — Individual coordinates within each movement

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Point ID |
| `movement_id` | INTEGER FK | References `movements.id` |
| `sequence` | INTEGER | Order in path (0, 1, 2, ...) |
| `x` | INTEGER | X coordinate |
| `y` | INTEGER | Y coordinate |
| `timestamp_ms` | INTEGER | Milliseconds since session start |
| `speed` | REAL | Instantaneous speed at this point |
| `acceleration` | REAL | Speed change from previous point |
| `angle_change` | REAL | Direction change from previous segment |

#### `clicks` — Detailed click behavior

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Click ID |
| `movement_id` | INTEGER FK | Associated movement session |
| `click_type` | TEXT | `left`, `right`, `middle` |
| `press_duration_ms` | INTEGER | Mouse down → mouse up time |
| `post_click_pause_ms` | INTEGER | Time before next movement starts |
| `post_click_recoil_px` | REAL | Small movement after click release |
| `x` | INTEGER | Click position X |
| `y` | INTEGER | Click position Y |
| `timestamp` | DATETIME | When click occurred |

#### `drags` — Drag operations (click-hold-move-release)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Drag ID |
| `start_x` | INTEGER | Drag start position |
| `start_y` | INTEGER | Drag start position |
| `end_x` | INTEGER | Drag end position |
| `end_y` | INTEGER | Drag end position |
| `duration_ms` | INTEGER | Total drag duration |
| `path_length_px` | REAL | Distance traveled while dragging |
| `point_count` | INTEGER | Points recorded during drag |
| `timestamp` | DATETIME | When drag started |

#### `drag_points` — Path during drag operations

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Point ID |
| `drag_id` | INTEGER FK | References `drags.id` |
| `sequence` | INTEGER | Order in drag path |
| `x` | INTEGER | X coordinate |
| `y` | INTEGER | Y coordinate |
| `timestamp_ms` | INTEGER | Ms since drag start |

#### `scrolls` — Scroll behavior patterns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Scroll ID |
| `movement_id` | INTEGER FK | Movement that led to scroll (nullable) |
| `direction` | TEXT | `up`, `down`, `left`, `right` |
| `delta` | INTEGER | Scroll amount |
| `x` | INTEGER | Cursor position during scroll |
| `y` | INTEGER | Cursor position during scroll |
| `timestamp` | DATETIME | When scroll occurred |

#### `keyboard_events` — For keyboard→mouse correlation

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Event ID |
| `event_type` | TEXT | `press` or `release` |
| `timestamp` | DATETIME | When key event occurred |

(We only track timing, not which keys — privacy)

#### `recording_sessions` — Track recording periods

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Session ID |
| `started_at` | DATETIME | When recording started |
| `ended_at` | DATETIME | When recording stopped |
| `total_movements` | INTEGER | Movements captured |
| `total_clicks` | INTEGER | Clicks captured |

#### `metadata` — Config and stats

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PRIMARY KEY | Setting name |
| `value` | TEXT | Setting value |

---

## Python Script Architecture

### Dependencies

```
pynput          # Mouse & keyboard event listening
sqlite3         # Database (built-in)
time            # Timestamps
threading       # Background processing
dataclasses     # Clean data structures
queue           # Thread-safe data passing
```

### Core Components

#### 1. MouseListener
- Hooks into system mouse events via `pynput`
- Captures: `move`, `click`, `scroll` events
- Tracks mouse button state for drag detection
- Runs in dedicated thread

#### 2. KeyboardListener
- Minimal keyboard monitoring (timing only)
- Updates "last keypress" timestamp
- For keyboard→mouse transition analysis

#### 3. SessionManager
- Tracks current movement session state
- Detects session start/end
- Calculates derived metrics
- Detects overshoot patterns
- Measures pre-click hover behavior
- Links sequential movements (chains)

#### 4. ClickAnalyzer
- Measures press duration (down→up)
- Detects post-click pause
- Measures post-click recoil movement

#### 5. DragDetector
- Identifies drag operations
- Records drag path separately

#### 6. DatabaseWriter
- Async/queued writes to SQLite
- Batch inserts for performance
- Handles all table writes

#### 7. FatigueTracker
- Monitors recording session duration
- Tags movements with fatigue context

---

## Data Collection Strategy

### Sampling Rate
- Record every mouse move event from OS
- Or fixed interval: every `8ms` (~125Hz)

### Storage Estimation (Updated)
- ~80 path points per session average
- ~100 sessions per hour
- ~8KB per session with all metadata
- **~800KB per hour → ~6MB per 8-hour day → ~150MB per month**

### Privacy Considerations
- No keylogging (only timing)
- No window titles or app names stored
- Only mouse coordinates and timing data

---

## Derived Metrics

| Metric | Formula | Purpose |
|--------|---------|---------|
| `distance_px` | √((end_x - start_x)² + (end_y - start_y)²) | Straight-line distance |
| `path_length_px` | Σ segment lengths | Actual traveled distance |
| `curvature_ratio` | path_length / distance | 1.0 = straight, >1 = curved |
| `avg_speed` | path_length / duration | Overall speed |
| `max_speed` | max(point speeds) | Peak velocity |
| `direction_angle` | atan2(Δy, Δx) | Movement direction |
| `has_overshoot` | path crosses target then returns | Common human behavior |
| `jitter_amplitude` | stddev of positions during hover | Micro-tremor measurement |

---

## Polling Rate Detection

### Why This Matters

Websites can infer your mouse polling rate from timestamp gaps. To avoid detection, we must replay at YOUR actual polling rate with YOUR actual timing variation.

### What to Capture

From recorded path points, calculate:

```python
# For each movement session
intervals = [point[i+1].timestamp - point[i].timestamp for i in range(len(points)-1)]

polling_metrics = {
    'avg_interval_ms': mean(intervals),           # e.g., 8.0ms
    'interval_stddev_ms': stddev(intervals),      # e.g., 0.4ms
    'detected_polling_rate': 1000 / mean(intervals),  # e.g., 125Hz
    'min_interval_ms': min(intervals),
    'max_interval_ms': max(intervals)
}
```

### Database Storage

Add to `recording_sessions` table:

| Column | Type | Description |
|--------|------|-------------|
| `detected_polling_rate_hz` | REAL | Calculated from intervals (e.g., 125.0) |
| `avg_point_interval_ms` | REAL | Average gap between points (e.g., 8.0) |
| `interval_stddev_ms` | REAL | Timing variation (e.g., 0.4) |

### Expected Values by Mouse Type

| Mouse Type | Polling Rate | Avg Interval | Typical StdDev |
|------------|--------------|--------------|----------------|
| Basic USB | 125 Hz | ~8.0ms | ±0.3-0.5ms |
| Budget gaming | 250 Hz | ~4.0ms | ±0.2-0.4ms |
| Gaming | 500 Hz | ~2.0ms | ±0.1-0.3ms |
| Pro gaming | 1000 Hz | ~1.0ms | ±0.1-0.2ms |

### Replay Application

When replaying movements, use recorded polling characteristics:
- Match your average interval (not assumed 125Hz or 60fps)
- Add your actual variation (gauss distribution with your stddev)
- Result: Timing fingerprint matches your real hardware

---

## File Structure

```
mouse-recorder/
├── main.py              # Entry point
├── listeners/
│   ├── mouse.py         # Mouse event capture
│   └── keyboard.py      # Keyboard timing capture
├── analysis/
│   ├── session.py       # Session management
│   ├── clicks.py        # Click analysis
│   ├── drags.py         # Drag detection
│   └── metrics.py       # Calculations
├── database/
│   ├── schema.py        # Table definitions
│   ├── writer.py        # Async DB writes
│   └── queries.py       # Common queries
├── utils/
│   ├── config.py        # Settings
│   └── fatigue.py       # Session duration tracking
├── movements.db         # SQLite database
└── README.md
```

---

## MVP Checklist

### Phase 1 — Core Recording
- [ ] Mouse listener (move, click, scroll)
- [ ] Basic session detection
- [ ] SQLite schema creation
- [ ] Path point recording
- [ ] Basic metrics calculation
- [ ] Graceful shutdown

### Phase 2 — Enhanced Behavior
- [ ] Click duration tracking
- [ ] Pre-click pause detection
- [ ] Post-click behavior analysis
- [ ] Overshoot detection
- [ ] Micro-jitter measurement

### Phase 3 — Context
- [ ] Keyboard timing correlation
- [ ] Drag operation recording
- [ ] Movement chain linking
- [ ] Fatigue/time tracking
- [ ] Recording session management

---

## Notes

- Run with elevated privileges if needed
- Add hotkey to pause/resume (e.g., Ctrl+Alt+R)
- Backup database periodically
- Consider archiving old path_points data
- Test CPU usage — should be minimal (<1%)

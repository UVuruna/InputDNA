# Implementation Plan — Human Input Recorder v2

## Changes from v1

- Removed overshoot detection from recorder (calculated in post-processing)
- Removed multi-monitor/DPI normalization (same monitors, same DPI)
- Removed session validation from recorder (detectable from timestamps later)
- Removed system_listener (screen lock etc. handled in post-processing)
- Removed raw keystroke auto-purge (no privacy concern)
- Removed validators.py (post-processing task)
- Added `click_sequences` table for unified click tracking (single/double/spam)
- Simplified overall architecture — recorder is DUMB, just captures and stores
- Recording and Robin are mutually exclusive — no concurrent DB access concerns

---

## Design Philosophy

**The recorder's ONLY job is:**
1. Capture raw events with precise timestamps
2. Store them in the database
3. Nothing else

**All analysis, validation, aggregation, overshoot detection, etc. happens LATER in a separate post-processing/ML-prep phase.**

This keeps the recorder simple, fast, and reliable.

---

## Folder Structure

```
human-input-recorder/
├── main.py                          # Entry point, orchestrates everything
├── config.py                        # All settings, thresholds, paths
├── requirements.txt                 # Dependencies
│
├── listeners/
│   ├── __init__.py
│   ├── mouse_listener.py            # pynput mouse hook — raw events
│   └── keyboard_listener.py         # pynput keyboard hook — raw events
│
├── processors/
│   ├── __init__.py
│   ├── mouse_session.py             # Session detection, path building
│   ├── click_processor.py           # Click sequences (single/double/spam)
│   ├── drag_detector.py             # Drag operation detection
│   └── keyboard_processor.py        # Keystroke timing, mode detection
│
├── database/
│   ├── __init__.py
│   ├── schema.py                    # All CREATE TABLE statements
│   └── writer.py                    # Batched DB writer
│
├── models/                          # Data classes (not ML models)
│   ├── __init__.py
│   ├── events.py                    # All raw event types
│   └── sessions.py                  # MovementSession, ClickSequence, etc.
│
├── utils/
│   ├── __init__.py
│   ├── timing.py                    # perf_counter wrappers
│   ├── keyboard_layout.py           # QWERTY map, finger/hand inference
│   └── hotkeys.py                   # Pause/resume hotkey
│
├── ui/
│   ├── __init__.py
│   └── tray_icon.py                 # System tray: pause/resume, stats, quit
│
└── data/
    └── (movements.db created here)
```

Total: **18 Python files** (down from 30+ in v1)

---

## File Descriptions

### `main.py`

Entry point. Simple orchestration:

```
main():
    1. Load config
    2. Init database (create tables if needed)
    3. Create shared event queue (thread-safe)
    4. Start DB writer thread (consumes from queue)
    5. Start mouse listener thread
    6. Start keyboard listener thread
    7. Start processor thread (processes raw events → sessions → queue)
    8. Start tray icon (main thread, blocks until quit)
    9. On quit: stop listeners, flush writer, close DB
```

Hotkey Ctrl+Alt+R pauses/resumes all listeners.

---

### `config.py`

All configurable values:

```python
# Database
DB_PATH = "data/movements.db"

# Session detection
IDLE_THRESHOLD_MS = 200          # No movement for this long = session might end
SESSION_END_TIMEOUT_MS = 300     # Confirmed session end after this idle

# Click detection
CLICK_SEQUENCE_GAP_MS = 500      # Max gap between clicks in same sequence

# Drag detection
DRAG_MIN_DISTANCE_PX = 5         # Min movement during mouse-down to count as drag

# Scroll grouping
SCROLL_SEQUENCE_GAP_MS = 500     # Gap between scroll events to start new sequence

# Database writer
BATCH_SIZE = 100                 # Records per flush
FLUSH_INTERVAL_S = 2.0           # Max seconds between flushes

# Recording
MIN_SESSION_DISTANCE_PX = 3      # Ignore micro-sessions shorter than this
```

---

### listeners/

#### `mouse_listener.py`

Wraps `pynput.mouse.Listener`. Dedicated thread.

Events captured:
- `on_move(x, y)` → `RawMouseMove(x, y, timestamp_ns)`
- `on_click(x, y, button, pressed)` → `RawMouseClick(x, y, button, pressed, timestamp_ns)`
- `on_scroll(x, y, dx, dy)` → `RawMouseScroll(x, y, dx, dy, timestamp_ns)`

All timestamps: `time.perf_counter_ns()` (integer nanoseconds, no float precision loss)

Pushes raw events to shared `queue.Queue` for processor.

Has `pause()` / `resume()` methods for hotkey control.

#### `keyboard_listener.py`

Wraps `pynput.keyboard.Listener`. Dedicated thread.

Events captured:
- `on_press(key)` → `RawKeyPress(vkey, scan_code, key_name, timestamp_ns, modifier_state, layout)`
- `on_release(key)` → `RawKeyRelease(vkey, scan_code, key_name, timestamp_ns)`

Key design: captures BOTH virtual key code (layout-dependent character) AND scan code
(physical key position, layout-independent). ML training uses scan codes for delay
prediction since physical distance determines finger travel time.

Active keyboard layout detected via `ctypes.windll.user32.GetKeyboardLayout()`.

Maintains modifier state dict internally (ctrl, alt, shift, win).

Tracks `press_times` dict for calculating key hold duration on release.

Same queue as mouse listener — processor handles both.

---

### processors/

#### `mouse_session.py`

Consumes `RawMouseMove` events and groups them into `MovementSession` objects.

State machine:
```
IDLE
  └─ on RawMouseMove → start new session, go to MOVING

MOVING
  └─ on RawMouseMove → add point to current session
  └─ on RawMouseClick → end session (end_event = click type), go to IDLE
  └─ on RawMouseScroll → end session (end_event = scroll), go to IDLE
  └─ on idle timeout → end session (end_event = "idle"), go to IDLE
```

When session ends, builds `MovementSession`:
- start_x, start_y, end_x, end_y
- all path points as list of (x, y, timestamp_ns)
- duration_ms (calculated from first/last point timestamps)
- distance_px (euclidean start→end)
- path_length_px (sum of segments)
- point_count
- end_event type
- hour_of_day, day_of_week (from wall clock at session start)
- timestamp (wall clock, for human reference)

Pushes completed `MovementSession` to DB writer queue.

**What it does NOT calculate:**
- curvature_ratio (post-processing)
- avg_speed, max_speed (post-processing — trivially derived from path points)
- overshoot anything (post-processing)
- pre_click_pause (post-processing — derived from last point timestamp vs click timestamp)
- jitter metrics (post-processing)

This keeps the processor simple and fast.

#### `click_processor.py`

Handles ALL click behavior as unified click sequences.

Consumes `RawMouseClick` events (both press and release).

Logic:
1. On mouse_down: record start timestamp, position
2. On mouse_up: calculate press_duration_ms
3. Check if previous click was within CLICK_SEQUENCE_GAP_MS
   - Yes → add to current ClickSequence
   - No → finalize previous sequence, start new one

`ClickSequence` contains:
- `click_count`: 1 = single, 2 = double, 3+ = spam
- `button`: left, right, middle
- `clicks[]`: array of individual clicks, each with:
  - x, y
  - press_duration_ms
  - delay_since_prev_ms (0 for first click)
  - timestamp_ns
- Total sequence duration

This handles ALL click types uniformly. The ML model later decides:
- Single click behavior
- Double click timing (the gap between 2 clicks is personal)
- Spam click rhythm (the gaps between rapid clicks are personal)

#### `drag_detector.py`

Detects drag operations (mouse_down + movement + mouse_up).

Logic:
1. On mouse_down: set `potential_drag = True`, record start position
2. On mouse_move while button held:
   - If moved > DRAG_MIN_DISTANCE_PX → confirmed drag
   - Record all drag path points
3. On mouse_up: end drag, store DragRecord

`DragRecord` contains:
- start_x, start_y, end_x, end_y
- button (usually left)
- path points with timestamps
- duration_ms

#### `keyboard_processor.py`

Processes keyboard events. Focus: key identity + timing.

For each key press/release pair, records:
- key_code, key_name
- press_duration_ms
- timestamp_ns
- modifier_state at time of press

For consecutive key presses, calculates:
- `delay_ms` between previous key press and this key press
- Stores as `KeyTransition(from_scan, to_scan, delay_ms, typing_mode)`
- Uses SCAN CODES for transitions (physical position = what determines delay)
- Virtual key codes stored for context only

Typing mode detection (simple heuristic):
- Active modifiers → "shortcut"
- Only numpad keys → "numpad"
- Letters + spaces → "text"
- Brackets, operators → "code"
- Default → "text"

For shortcuts specifically:
- Records full timing profile: modifier_down → main_key_down → main_key_up → modifier_up
- All 4 timestamps stored

---

### database/

#### `schema.py`

All tables. SQLite with WAL mode.

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA temp_store=MEMORY;
```

**Table: `movements`** — Movement sessions (mouse path from A to B)

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| start_x | INTEGER | Starting X |
| start_y | INTEGER | Starting Y |
| end_x | INTEGER | Ending X |
| end_y | INTEGER | Ending Y |
| end_event | TEXT | "left_click", "right_click", "scroll_up", "idle", etc. |
| duration_ms | REAL | Total movement time |
| distance_px | REAL | Euclidean distance |
| path_length_px | REAL | Sum of all segments |
| point_count | INTEGER | Number of path points |
| hour_of_day | INTEGER | 0-23 |
| day_of_week | INTEGER | 0-6 |
| recording_session_id | INTEGER FK | Which recording session |
| timestamp | TEXT | ISO wall clock time |

**Table: `path_points`** — Raw (x, y, t) for each movement

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| movement_id | INTEGER FK | References movements.id |
| seq | INTEGER | Order in path (0, 1, 2, ...) |
| x | INTEGER | X coordinate |
| y | INTEGER | Y coordinate |
| t_ns | INTEGER | perf_counter_ns timestamp |

Note: `t_ns` is raw perf_counter nanoseconds. Relative timing between points is what matters, not absolute wall clock. This gives maximum precision for interval analysis.

**Table: `click_sequences`** — Unified click tracking

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| movement_id | INTEGER FK | Movement that led to this click (nullable) |
| button | TEXT | "left", "right", "middle" |
| click_count | INTEGER | 1=single, 2=double, 3+=spam |
| total_duration_ms | REAL | First click start → last click end |
| x | INTEGER | Position of first click |
| y | INTEGER | Position of first click |
| timestamp | TEXT | ISO wall clock |

**Table: `click_details`** — Individual clicks within a sequence

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| sequence_id | INTEGER FK | References click_sequences.id |
| seq | INTEGER | Order in sequence (0, 1, 2, ...) |
| x | INTEGER | Click position |
| y | INTEGER | Click position |
| press_duration_ms | REAL | Mouse down → up |
| delay_since_prev_ms | REAL | Gap from previous click (0 for first) |
| t_ns | INTEGER | perf_counter_ns timestamp |

**Table: `drags`** — Drag operations

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| button | TEXT | Usually "left" |
| start_x | INTEGER | Drag start |
| start_y | INTEGER | Drag start |
| end_x | INTEGER | Drag end |
| end_y | INTEGER | Drag end |
| duration_ms | REAL | Total drag time |
| point_count | INTEGER | Points in drag path |
| timestamp | TEXT | ISO wall clock |

**Table: `drag_points`** — Path during drag

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| drag_id | INTEGER FK | References drags.id |
| seq | INTEGER | Order |
| x | INTEGER | X coordinate |
| y | INTEGER | Y coordinate |
| t_ns | INTEGER | perf_counter_ns |

**Table: `scrolls`** — Scroll events

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| movement_id | INTEGER FK | Preceding movement (nullable) |
| direction | TEXT | "up", "down", "left", "right" |
| delta | INTEGER | Scroll amount |
| x | INTEGER | Cursor X during scroll |
| y | INTEGER | Cursor Y during scroll |
| t_ns | INTEGER | perf_counter_ns |
| timestamp | TEXT | ISO wall clock |

**Table: `keystrokes`** — Every key press/release

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| scan_code | INTEGER | Physical key position (layout-independent) |
| vkey | INTEGER | Virtual key code (layout-dependent) |
| key_name | TEXT | Human-readable name |
| press_duration_ms | REAL | Hold time |
| modifier_state | TEXT | JSON: {"ctrl": true, "shift": false, ...} |
| active_layout | TEXT | Keyboard layout ID at time of press |
| hand | TEXT | "left" or "right" (inferred from scan_code position) |
| finger | TEXT | "pinky", "ring", "middle", "index", "thumb" |
| t_ns | INTEGER | perf_counter_ns of press |
| timestamp | TEXT | ISO wall clock |

**Table: `key_transitions`** — Delay between consecutive keys

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| from_scan | INTEGER | Previous key scan code (physical position) |
| to_scan | INTEGER | Next key scan code (physical position) |
| from_key_name | TEXT | Previous key name (for readability) |
| to_key_name | TEXT | Next key name (for readability) |
| delay_ms | REAL | Time between presses |
| typing_mode | TEXT | "text", "shortcut", "numpad", "code" |
| t_ns | INTEGER | perf_counter_ns |

**Table: `shortcuts`** — Keyboard shortcut timing

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| shortcut_name | TEXT | "Ctrl+C", "Alt+Tab", etc. |
| modifier_keys | TEXT | JSON array |
| main_key | TEXT | Non-modifier key |
| modifier_to_main_ms | REAL | Modifier press → main key press |
| main_hold_ms | REAL | Main key hold duration |
| overlap_ms | REAL | Both held simultaneously |
| total_ms | REAL | Full shortcut execution |
| release_order | TEXT | "main_first" or "modifier_first" |
| t_ns | INTEGER | perf_counter_ns |
| timestamp | TEXT | ISO wall clock |

**Table: `recording_sessions`** — Recording periods

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| started_at | TEXT | ISO wall clock |
| ended_at | TEXT | ISO wall clock |
| total_movements | INTEGER | Count |
| total_clicks | INTEGER | Count |
| total_keystrokes | INTEGER | Count |
| perf_counter_start_ns | INTEGER | Reference for converting t_ns to relative time |

**Table: `system_events`** — Tracks system state changes over time

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| key | TEXT | Setting name (e.g. "mouse_speed", "screen_resolution") |
| value | TEXT | Setting value |
| t_ns | INTEGER | perf_counter_ns |
| timestamp | TEXT | ISO wall clock |

Initial state recorded at recording session start. New row inserted only when a value changes.

**Table: `metadata`** — Static key-value config

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PK | Setting name |
| value | TEXT | Setting value |

---

#### `writer.py`

Single-threaded batched database writer.

Consumes from thread-safe `queue.Queue`:
- Accumulates records in memory
- Flushes when BATCH_SIZE reached OR FLUSH_INTERVAL elapsed
- All inserts within single BEGIN/COMMIT transaction
- Simple retry on SQLite busy (shouldn't happen since exclusive access)

```python
class DatabaseWriter:
    def __init__(self, db_path, batch_size=100, flush_interval=2.0):
        self.queue = queue.Queue()
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.running = False

    def start(self):
        """Start writer thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def put(self, record):
        """Add record to write queue. Thread-safe."""
        self.queue.put(record)

    def _run(self):
        """Main writer loop."""
        conn = sqlite3.connect(self.db_path)
        batch = []
        last_flush = time.monotonic()

        while self.running or not self.queue.empty():
            try:
                record = self.queue.get(timeout=0.1)
                batch.append(record)
            except queue.Empty:
                pass

            now = time.monotonic()
            if len(batch) >= self.batch_size or (now - last_flush) >= self.flush_interval:
                if batch:
                    self._flush(conn, batch)
                    batch = []
                    last_flush = now

        # Final flush
        if batch:
            self._flush(conn, batch)
        conn.close()

    def _flush(self, conn, batch):
        """Write batch to database in single transaction."""
        with conn:
            for record in batch:
                record.write_to_db(conn)

    def stop(self):
        """Stop writer, flush remaining."""
        self.running = False
        self.thread.join(timeout=10)
```

Each record type (MovementSession, ClickSequence, etc.) has its own `write_to_db(conn)` method that knows which table(s) to insert into.

---

### models/

#### `events.py`

Raw event data classes — produced by listeners:

```python
@dataclass
class RawMouseMove:
    x: int
    y: int
    t_ns: int  # perf_counter_ns

@dataclass
class RawMouseClick:
    x: int
    y: int
    button: str       # "left", "right", "middle"
    pressed: bool     # True = down, False = up
    t_ns: int

@dataclass
class RawMouseScroll:
    x: int
    y: int
    dx: int
    dy: int
    t_ns: int

@dataclass
class RawKeyPress:
    vkey: int             # Virtual key code (layout-dependent)
    scan_code: int        # Physical key position (layout-independent)
    key_name: str
    t_ns: int
    modifier_state: dict  # {"ctrl": bool, "alt": bool, "shift": bool, "win": bool}
    active_layout: str    # Keyboard layout ID

@dataclass
class RawKeyRelease:
    vkey: int
    scan_code: int
    key_name: str
    t_ns: int
    press_duration_ms: float
```

#### `sessions.py`

Processed session data classes — produced by processors, consumed by DB writer:

```python
@dataclass
class PathPoint:
    x: int
    y: int
    t_ns: int

@dataclass
class MovementSession:
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    end_event: str
    duration_ms: float
    distance_px: float
    path_length_px: float
    point_count: int
    path_points: List[PathPoint]
    hour_of_day: int
    day_of_week: int
    recording_session_id: int
    timestamp: str  # ISO format

    def write_to_db(self, conn): ...

@dataclass
class SingleClick:
    x: int
    y: int
    press_duration_ms: float
    delay_since_prev_ms: float
    t_ns: int

@dataclass
class ClickSequence:
    button: str
    click_count: int
    clicks: List[SingleClick]
    total_duration_ms: float
    movement_id: Optional[int]
    timestamp: str

    def write_to_db(self, conn): ...

@dataclass
class DragRecord:
    button: str
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: float
    path_points: List[PathPoint]
    timestamp: str

    def write_to_db(self, conn): ...

@dataclass
class KeystrokeRecord:
    scan_code: int
    vkey: int
    key_name: str
    press_duration_ms: float
    modifier_state: dict
    active_layout: str
    hand: str
    finger: str
    t_ns: int
    timestamp: str

    def write_to_db(self, conn): ...

@dataclass
class KeyTransitionRecord:
    from_scan: int
    to_scan: int
    from_key_name: str
    to_key_name: str
    delay_ms: float
    typing_mode: str
    t_ns: int

    def write_to_db(self, conn): ...

@dataclass
class ShortcutRecord:
    shortcut_name: str
    modifier_keys: List[str]
    main_key: str
    modifier_to_main_ms: float
    main_hold_ms: float
    overlap_ms: float
    total_ms: float
    release_order: str
    t_ns: int
    timestamp: str

    def write_to_db(self, conn): ...
```

---

### utils/

#### `timing.py`

```python
import time

def now_ns() -> int:
    """Current timestamp in nanoseconds (perf_counter)."""
    return time.perf_counter_ns()

def ns_to_ms(ns: int) -> float:
    """Convert nanoseconds to milliseconds."""
    return ns / 1_000_000

def interval_ms(t1_ns: int, t2_ns: int) -> float:
    """Milliseconds between two perf_counter_ns timestamps."""
    return (t2_ns - t1_ns) / 1_000_000

def wall_clock_iso() -> str:
    """Current wall clock time as ISO string."""
    return datetime.now().isoformat()
```

#### `keyboard_layout.py`

Physical keyboard map based on SCAN CODES (layout-independent):

```python
# Scan codes represent PHYSICAL key positions
# Same scan code = same physical key regardless of language layout
PHYSICAL_LAYOUT = {
    # scan_code: (hand, finger, row, col)
    0x10: ('left', 'pinky', 0, 0),    # Physical Q position
    0x11: ('left', 'ring', 0, 1),     # Physical W position
    0x12: ('left', 'middle', 0, 2),   # Physical E position
    0x13: ('left', 'index', 0, 3),    # Physical R position
    0x14: ('left', 'index', 0, 4),    # Physical T position
    0x15: ('right', 'index', 0, 5),   # Physical Y position
    ...
}

def infer_hand(scan_code: int) -> str: ...
def infer_finger(scan_code: int) -> str: ...
def physical_distance(sc1: int, sc2: int) -> float: ...
def same_hand(sc1: int, sc2: int) -> bool: ...
def same_finger(sc1: int, sc2: int) -> bool: ...
```

This works for ANY keyboard layout (English, Serbian Latin, Serbian Cyrillic, etc.)
because scan codes are based on physical position, not character mapping.

#### `hotkeys.py`

Global hotkey registration for pause/resume:

```python
# Using pynput.keyboard.GlobalHotKeys
def register_hotkeys(on_toggle):
    hotkeys = keyboard.GlobalHotKeys({
        '<ctrl>+<alt>+r': on_toggle
    })
    hotkeys.start()
    return hotkeys
```

---

### ui/

#### `tray_icon.py`

System tray using `pystray`:
- Green icon = recording
- Yellow icon = paused
- Red icon = error
- Menu: Pause/Resume | Stats | Quit
- Stats shows: total sessions, total keystrokes, DB size, uptime

---

## Dependencies

```
# requirements.txt
pynput>=1.7.6          # Mouse & keyboard hooks
pystray>=0.19.5        # System tray icon
Pillow>=10.0           # Required by pystray
```

That's it. No numpy, no pywin32. Pure standard library + pynput + pystray.

Distance and basic math: `math.sqrt`, `math.atan2` from stdlib.
Statistics (if needed): `statistics` module from stdlib.

---

## Implementation Order

### Sprint 1: Foundation (Days 1-2)
1. `config.py`
2. `models/events.py`
3. `models/sessions.py`
4. `utils/timing.py`
5. `database/schema.py`
6. `database/writer.py`
7. `main.py` — skeleton

### Sprint 2: Mouse Recording (Days 3-5)
8. `listeners/mouse_listener.py`
9. `processors/mouse_session.py`
10. `processors/click_processor.py`
11. `processors/drag_detector.py`
12. Test: record 10 min of mouse usage, inspect DB

### Sprint 3: Keyboard Recording (Days 6-8)
13. `listeners/keyboard_listener.py`
14. `processors/keyboard_processor.py`
15. `utils/keyboard_layout.py`
16. Test: record 10 min of typing, inspect DB

### Sprint 4: UI & Polish (Days 9-10)
17. `utils/hotkeys.py`
18. `ui/tray_icon.py`
19. Full integration test: 1 hour recording
20. Verify DB size, CPU usage, memory

### Total: ~10 working days for complete recorder

---

## Performance Targets

| Metric | Target |
|--------|--------|
| CPU usage (idle) | < 0.5% |
| CPU usage (active) | < 2% |
| RAM usage | < 30 MB |
| DB write latency | < 50ms per batch |
| Event processing | < 0.5ms per event |
| DB growth | ~150-200 MB/month |
| Startup time | < 1 second |

---

## Thread Architecture

```
Main Thread ──── tray_icon (blocks, handles menu/quit)
    │
    ├── Thread 1: mouse_listener (pynput hook)
    │       └── pushes RawMouse* events to event_queue
    │
    ├── Thread 2: keyboard_listener (pynput hook)
    │       └── pushes RawKey* events to event_queue
    │
    ├── Thread 3: processor (consumes event_queue)
    │       ├── mouse_session.py
    │       ├── click_processor.py
    │       ├── drag_detector.py
    │       └── keyboard_processor.py
    │       └── pushes processed records to write_queue
    │
    └── Thread 4: db_writer (consumes write_queue)
            └── batched INSERT to SQLite
```

4 threads total. Clean separation. No shared state except queues.

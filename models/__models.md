# models/

Data classes used throughout the recorder. These are NOT ML models — they are
plain Python dataclasses that define the shape of data flowing through the system.

<a id="folder-structure"></a>

## Folder Structure

```
📁 models/
  📝 __models.md
  🐍 __init__.py
  🐍 events.py
  🐍 sessions.py
```

<a id="files"></a>

## Files

### `events.py` — Raw Events (from listeners)

Raw events produced by mouse and keyboard listeners. These are the first thing
created when the OS reports an input event. They contain only what the OS gives
us plus a precise timestamp.

**Mouse events:**

| Class | Trigger | Fields |
|-------|---------|--------|
| `RawMouseMove` | Cursor moved | `x`, `y`, `t_ns` |
| `RawMouseClick` | Button pressed/released | `x`, `y`, `button`, `pressed`, `t_ns` |
| `RawMouseScroll` | Scroll wheel | `x`, `y`, `dx`, `dy`, `t_ns` |

**Keyboard events:**

| Class | Trigger | Fields |
|-------|---------|--------|
| `RawKeyPress` | Key pressed | `scan_code`, `vkey`, `key_name`, `t_ns`, `modifier_state`, `active_layout` |
| `RawKeyRelease` | Key released | `scan_code`, `key_name`, `t_ns`, `press_duration_ms` |

> **Note:** All timestamps use `time.perf_counter_ns()` — monotonic, integer nanoseconds,
> sub-microsecond precision. Never floats, never wall clock.

All event classes use `@dataclass(slots=True)` for minimal memory footprint
since thousands of these are created per second during active use.

### `sessions.py` — Processed Records (for database)

Processed records produced by processors after analyzing raw events.
Each has a `write_to_db(conn)` method that knows how to INSERT itself
into the correct table(s).

**Mouse records:**

| Class | DB Table(s) | Description |
|-------|-------------|-------------|
| `MovementSession` | `movements` + `path_points` | Complete movement with full path, app-generated `movement_id` |
| `SingleClick` | — (embedded in ClickSequence) | One click within a sequence |
| `ClickSequence` | `click_sequences` + `click_details` | Group of clicks (1, 2, 3+) |
| `DragRecord` | `drags` + `drag_points` | Click-hold-move-release |
| `ScrollEvent` | `scrolls` | Single scroll event |

**Keyboard records:**

| Class | DB Table | Description |
|-------|----------|-------------|
| `KeystrokeRecord` | `keystrokes` | One key press with duration, vkey, layout, hand/finger |
| `KeyTransitionRecord` | `key_transitions` | Delay between two consecutive keys |
| `ShortcutRecord` | `shortcuts` | Modifier+key combo timing profile |

**Meta records:**

| Class | DB Table | Description |
|-------|----------|-------------|
| `SystemEventRecord` | `system_events` | Tracks a system state change |
| `RecordingSessionRecord` | `recording_sessions` | One recording period (start→stop) |

<a id="data-flow"></a>

## Data Flow

```mermaid
flowchart LR
    OS((OS)) -- "input event" --> L[Listener]
    L -- "Raw Event\n(events.py)" --> P[Processor]
    P -- "Record\n(sessions.py)" --> W[DB Writer]
    W -- "write_to_db()" --> DB[(SQLite)]
```

**Shared helpers:**

| Function | Description |
|----------|-------------|
| `_delta_encode_points()` | Converts a list of PathPoints to delta-encoded tuples for DB storage (seq=0 absolute, seq>0 deltas) |

> **Note:** Raw events are lightweight and short-lived (queue transit only).
> Processed records are richer and persist to disk via `write_to_db()`.
> Path points use delta encoding — see metadata key `path_encoding=delta_v1`.

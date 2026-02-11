# database/

SQLite database layer. Handles schema creation and batched writing.

<a id="folder-structure"></a>

## Folder Structure

```
📁 database/
  📝 __database.md
  🐍 __init__.py
  🐍 schema.py
  🐍 writer.py
  🐍 rotation.py
```

<a id="files"></a>

## Files

### `schema.py` — Table Definitions

Creates all tables on first run. Sets SQLite pragmas for performance
(WAL mode, memory-mapped I/O, etc.). Safe to call multiple times —
uses `IF NOT EXISTS`.

**Tables created:**

| Table | Category | Description |
|-------|----------|-------------|
| `movements` | Mouse | Movement sessions (start→end with summary metrics) |
| `path_points` | Mouse | Raw (x, y, t_ns) coordinates within movements |
| `click_sequences` | Mouse | Unified click tracking (single/double/spam) |
| `click_details` | Mouse | Individual clicks within sequences |
| `drags` | Mouse | Click-hold-move-release operations |
| `drag_points` | Mouse | Path coordinates during drags |
| `scrolls` | Mouse | Scroll wheel events |
| `keystrokes` | Keyboard | Individual key presses with scan codes, vkey, and layout |
| `key_transitions` | Keyboard | Delay between consecutive keys (scan code pairs) |
| `shortcuts` | Keyboard | Keyboard shortcut timing profiles |
| `recording_sessions` | Meta | Recording periods (start/end/counts) |
| `system_events` | System | Tracks changes to system state (mouse speed, layout, resolution, etc.) |
| `metadata` | Meta | Static key-value config/stats |

**Key schema details:**

- `movements.id` is **app-generated** (not AUTOINCREMENT): format `session * 1_000_000 + seq`. This allows the processor to know the ID before DB write and link clicks/scrolls to their preceding movement.
- `path_points` and `drag_points` use **delta encoding**: seq=0 is absolute, seq>0 stores deltas from previous point. Metadata key `path_encoding=delta_v1` signals this to readers.

**SQLite pragmas applied:**

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=268435456;
```

### `writer.py` — Batched Database Writer

Single-threaded writer that consumes records from a queue and writes them
in batches for performance. All database writes go through this one writer —
no concurrent write issues.

**Batching strategy:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BATCH_SIZE` | 100 | Max records per flush |
| `FLUSH_INTERVAL` | 2.0s | Max time between flushes |

Whichever threshold is hit first triggers a flush. Each flush is a single
transaction. Final flush on shutdown ensures no data loss.

<a id="data-flow"></a>

## Data Flow

```mermaid
flowchart LR
    P[Processors] -- "records" --> Q[Write Queue]
    Q --> W[DatabaseWriter]
    W -- "batched INSERT" --> DB[(SQLite WAL)]
```

> **Note:** The write queue is a standard `queue.Queue` — thread-safe, no locks needed by callers.

<a id="design-decisions"></a>

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| WAL mode | Allows reading while writing (for future stats UI) |
| Single writer | Eliminates all concurrency issues with SQLite |
| `perf_counter_ns` in `t_ns` columns | Maximum precision timestamps (integer nanoseconds) |
| Wall clock in `timestamp` columns | Human readability only — never used for calculations |
| No indexes by default | Added later during ML prep phase if needed (INSERT-heavy workload) |
| Delta-encoded paths | Smaller integers → fewer bytes in SQLite varint encoding (~30% savings) |
| App-generated movement IDs | Processor knows ID before write → can link clicks/scrolls immediately |

### `rotation.py` — DB File Rotation

Archives the active DB when it exceeds `DB_ROTATION_MAX_BYTES` (default 5 GB).
Called once at session start. If rotation triggers:

1. Active DB renamed with timestamp suffix (e.g., `movements_20260211_143022.db`)
2. WAL and SHM files also renamed
3. Old DB VACUUMed in a background daemon thread
4. Fresh DB created at the original path

ML/post-processing discovers all DB files via `glob("db/*.db")`.

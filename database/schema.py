"""
Database schema — CREATE TABLE statements for all three databases.

Each user has three SQLite databases:
- mouse.db:    Movement sessions, paths, clicks, drags, scrolls
- keyboard.db: Keystrokes, key transitions, shortcuts
- session.db:  Recording sessions, system events, metadata

Called once on first run per database. Safe to call again (uses IF NOT EXISTS).
Also sets SQLite pragmas for optimal performance.
"""

import sqlite3
from pathlib import Path


# ── Shared pragmas ──────────────────────────────────────────

_PRAGMAS = """
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    PRAGMA cache_size=-64000;
    PRAGMA temp_store=MEMORY;
    PRAGMA mmap_size=268435456;
"""


def _init(db_path: Path, schema: str) -> sqlite3.Connection:
    """Create database, set pragmas, create tables. Returns open connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_PRAGMAS)
    conn.executescript(schema)
    conn.commit()
    return conn


# ══════════════════════════════════════════════════════════════
# MOUSE DATABASE
# ══════════════════════════════════════════════════════════════

_MOUSE_SCHEMA = """

-- Movement Sessions
-- id: app-generated = session_id × 1_000_000 + seq_within_session
-- start_t_ns / end_t_ns: perf_counter_ns bookends (timing reconstructed from these)
-- end_event: what triggered end — 'click', 'drag', 'scroll', 'idle'
CREATE TABLE IF NOT EXISTS movements (
    id          INTEGER PRIMARY KEY,
    start_x     INTEGER NOT NULL,
    start_y     INTEGER NOT NULL,
    end_x       INTEGER NOT NULL,
    end_y       INTEGER NOT NULL,
    end_event   TEXT    NOT NULL,
    start_t_ns  INTEGER NOT NULL,
    end_t_ns    INTEGER NOT NULL
);

-- Raw path coordinates within movements (delta-encoded)
-- seq=0: absolute (x, y), dt_us=0; seq>0: deltas (Δx, Δy), dt_us=µs since prev point
-- No id column — composite PK (movement_id, seq) is sufficient
-- Timing: t_ns[0]=start_t_ns, t_ns[i]=t_ns[i-1]+dt_us[i]*1000
CREATE TABLE IF NOT EXISTS path_points (
    movement_id  INTEGER NOT NULL REFERENCES movements(id),
    seq          INTEGER NOT NULL,
    x            INTEGER NOT NULL,
    y            INTEGER NOT NULL,
    dt_us        INTEGER NOT NULL,
    PRIMARY KEY (movement_id, seq)
);

-- Click sequences (single / double / spam)
-- movement_id: FK to movements (NULL if click without preceding movement)
-- x, y, button, timestamp, click_count, total_duration_ms: all derivable from click_details
CREATE TABLE IF NOT EXISTS click_sequences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id INTEGER REFERENCES movements(id),
    button      TEXT    NOT NULL
);

-- Individual clicks within sequences
-- No id column — composite PK (sequence_id, seq) is sufficient
-- x, y: derivable from click_sequences or movement end position
-- delay_since_prev_ms: derivable from t_ns differences in post-processing
CREATE TABLE IF NOT EXISTS click_details (
    sequence_id       INTEGER NOT NULL REFERENCES click_sequences(id),
    seq               INTEGER NOT NULL,
    press_duration_ms REAL    NOT NULL,
    t_ns              INTEGER NOT NULL,
    PRIMARY KEY (sequence_id, seq)
);

-- Drag operations (click-hold-move-release)
-- id: app-generated = session_id × 1_000_000 + seq_within_session
-- end_x, end_y, duration_ms, point_count: derivable from drag_points + start_t_ns/end_t_ns
CREATE TABLE IF NOT EXISTS drags (
    id          INTEGER PRIMARY KEY,
    button      TEXT    NOT NULL,
    start_x     INTEGER NOT NULL,
    start_y     INTEGER NOT NULL,
    start_t_ns  INTEGER NOT NULL,
    end_t_ns    INTEGER NOT NULL
);

-- Path coordinates during drags (delta-encoded)
-- seq=0: absolute (x, y), dt_us=0; seq>0: deltas (Δx, Δy), dt_us=µs since prev point
-- No id column — composite PK (drag_id, seq) is sufficient
-- Timing: t_ns[0]=start_t_ns, t_ns[i]=t_ns[i-1]+dt_us[i]*1000
CREATE TABLE IF NOT EXISTS drag_points (
    drag_id  INTEGER NOT NULL REFERENCES drags(id),
    seq      INTEGER NOT NULL,
    x        INTEGER NOT NULL,
    y        INTEGER NOT NULL,
    dt_us    INTEGER NOT NULL,
    PRIMARY KEY (drag_id, seq)
);

-- Scroll wheel events
-- direction: derivable as sign(delta) in post-processing
-- timestamp: derivable from t_ns in post-processing
CREATE TABLE IF NOT EXISTS scrolls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id INTEGER REFERENCES movements(id),
    delta       INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    t_ns        INTEGER NOT NULL
);

-- Key-value metadata (path_encoding, etc.)
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);


"""


# ══════════════════════════════════════════════════════════════
# KEYBOARD DATABASE
# ══════════════════════════════════════════════════════════════

_KEYBOARD_SCHEMA = """

-- Individual key presses
-- modifier_state: INTEGER bitmask (bit0=Ctrl, bit1=Alt, bit2=Shift, bit3=Win)
-- vkey, key_name, active_layout, hand, finger, timestamp: all derivable in post-processing
CREATE TABLE IF NOT EXISTS keystrokes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_code         INTEGER NOT NULL,
    press_duration_ms REAL    NOT NULL,
    modifier_state    INTEGER NOT NULL,
    t_ns              INTEGER NOT NULL
);

-- Delay between consecutive keys (scan code pairs)
-- from_key_name, to_key_name: derivable from scan codes in post-processing
-- delay_ms: derivable from t_ns differences in post-processing
CREATE TABLE IF NOT EXISTS key_transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scan   INTEGER NOT NULL,
    to_scan     INTEGER NOT NULL,
    typing_mode TEXT    NOT NULL,
    t_ns        INTEGER NOT NULL
);

-- Keyboard shortcut timing profiles
-- shortcut_name, main_key_name, timestamp: derivable in post-processing
CREATE TABLE IF NOT EXISTS shortcuts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    modifier_scans       TEXT    NOT NULL,
    main_scan            INTEGER NOT NULL,
    modifier_to_main_ms  REAL    NOT NULL,
    main_hold_ms         REAL    NOT NULL,
    overlap_ms           REAL    NOT NULL,
    total_ms             REAL    NOT NULL,
    release_order        TEXT    NOT NULL,
    t_ns                 INTEGER NOT NULL
);

"""


# ══════════════════════════════════════════════════════════════
# SESSION DATABASE
# ══════════════════════════════════════════════════════════════

_SESSION_SCHEMA = """

-- Recording periods (start/end/counts)
CREATE TABLE IF NOT EXISTS recording_sessions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at             TEXT    NOT NULL,
    ended_at               TEXT,
    total_movements        INTEGER DEFAULT 0,
    total_clicks           INTEGER DEFAULT 0,
    total_keystrokes       INTEGER DEFAULT 0,
    perf_counter_start_ns  INTEGER NOT NULL
);

-- System state changes (mouse speed, layout, resolution, etc.)
CREATE TABLE IF NOT EXISTS system_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    key       TEXT    NOT NULL,
    value     TEXT    NOT NULL,
    t_ns      INTEGER NOT NULL,
    timestamp TEXT    NOT NULL
);

-- Key-value metadata store
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

"""


# ── Public init functions ───────────────────────────────────

def init_mouse_db(db_path: Path) -> sqlite3.Connection:
    """Create mouse database with movement/click/drag/scroll tables."""
    conn = _init(db_path, _MOUSE_SCHEMA)
    # Signal schema version to post-processing readers
    conn.execute(
        "INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)",
        ("path_encoding", "delta_v3"),
    )
    conn.commit()
    return conn


def init_keyboard_db(db_path: Path) -> sqlite3.Connection:
    """Create keyboard database with keystroke/transition/shortcut tables."""
    return _init(db_path, _KEYBOARD_SCHEMA)


def init_session_db(db_path: Path) -> sqlite3.Connection:
    """Create session database with recording sessions/system events/metadata."""
    return _init(db_path, _SESSION_SCHEMA)

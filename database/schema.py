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
CREATE TABLE IF NOT EXISTS movements (
    id                   INTEGER PRIMARY KEY,
    start_x              INTEGER NOT NULL,
    start_y              INTEGER NOT NULL,
    end_x                INTEGER NOT NULL,
    end_y                INTEGER NOT NULL,
    end_event            TEXT    NOT NULL,
    duration_ms          REAL    NOT NULL,
    distance_px          REAL    NOT NULL,
    path_length_px       REAL    NOT NULL,
    point_count          INTEGER NOT NULL,
    hour_of_day          INTEGER NOT NULL,
    day_of_week          INTEGER NOT NULL,
    recording_session_id INTEGER,
    timestamp            TEXT    NOT NULL
);

-- Raw path coordinates within movements (delta-encoded)
CREATE TABLE IF NOT EXISTS path_points (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id  INTEGER NOT NULL REFERENCES movements(id),
    seq          INTEGER NOT NULL,
    x            INTEGER NOT NULL,
    y            INTEGER NOT NULL,
    t_ns         INTEGER NOT NULL
);

-- Click sequences (single / double / spam)
CREATE TABLE IF NOT EXISTS click_sequences (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id       INTEGER REFERENCES movements(id),
    button            TEXT    NOT NULL,
    click_count       INTEGER NOT NULL,
    total_duration_ms REAL    NOT NULL,
    x                 INTEGER NOT NULL,
    y                 INTEGER NOT NULL,
    timestamp         TEXT    NOT NULL
);

-- Individual clicks within sequences
CREATE TABLE IF NOT EXISTS click_details (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id          INTEGER NOT NULL REFERENCES click_sequences(id),
    seq                  INTEGER NOT NULL,
    x                    INTEGER NOT NULL,
    y                    INTEGER NOT NULL,
    press_duration_ms    REAL    NOT NULL,
    delay_since_prev_ms  REAL    NOT NULL,
    t_ns                 INTEGER NOT NULL
);

-- Drag operations (click-hold-move-release)
CREATE TABLE IF NOT EXISTS drags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    button      TEXT    NOT NULL,
    start_x     INTEGER NOT NULL,
    start_y     INTEGER NOT NULL,
    end_x       INTEGER NOT NULL,
    end_y       INTEGER NOT NULL,
    duration_ms REAL    NOT NULL,
    point_count INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL
);

-- Path coordinates during drags (delta-encoded)
CREATE TABLE IF NOT EXISTS drag_points (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    drag_id  INTEGER NOT NULL REFERENCES drags(id),
    seq      INTEGER NOT NULL,
    x        INTEGER NOT NULL,
    y        INTEGER NOT NULL,
    t_ns     INTEGER NOT NULL
);

-- Scroll wheel events
CREATE TABLE IF NOT EXISTS scrolls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id INTEGER REFERENCES movements(id),
    direction   TEXT    NOT NULL,
    delta       INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    t_ns        INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL
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

-- Individual key presses with scan codes, vkey, and layout
CREATE TABLE IF NOT EXISTS keystrokes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_code         INTEGER NOT NULL,
    vkey              INTEGER NOT NULL,
    key_name          TEXT    NOT NULL,
    press_duration_ms REAL    NOT NULL,
    modifier_state    TEXT    NOT NULL,
    active_layout     TEXT    NOT NULL,
    hand              TEXT    NOT NULL,
    finger            TEXT    NOT NULL,
    t_ns              INTEGER NOT NULL,
    timestamp         TEXT    NOT NULL
);

-- Delay between consecutive keys (scan code pairs)
CREATE TABLE IF NOT EXISTS key_transitions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scan     INTEGER NOT NULL,
    to_scan       INTEGER NOT NULL,
    from_key_name TEXT    NOT NULL,
    to_key_name   TEXT    NOT NULL,
    delay_ms      REAL    NOT NULL,
    typing_mode   TEXT    NOT NULL,
    t_ns          INTEGER NOT NULL
);

-- Keyboard shortcut timing profiles
CREATE TABLE IF NOT EXISTS shortcuts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcut_name        TEXT    NOT NULL,
    modifier_scans       TEXT    NOT NULL,
    main_scan            INTEGER NOT NULL,
    main_key_name        TEXT    NOT NULL,
    modifier_to_main_ms  REAL    NOT NULL,
    main_hold_ms         REAL    NOT NULL,
    overlap_ms           REAL    NOT NULL,
    total_ms             REAL    NOT NULL,
    release_order        TEXT    NOT NULL,
    t_ns                 INTEGER NOT NULL,
    timestamp            TEXT    NOT NULL
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
    # Signal delta encoding to post-processing readers
    conn.execute(
        "INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)",
        ("path_encoding", "delta_v1"),
    )
    conn.commit()
    return conn


def init_keyboard_db(db_path: Path) -> sqlite3.Connection:
    """Create keyboard database with keystroke/transition/shortcut tables."""
    return _init(db_path, _KEYBOARD_SCHEMA)


def init_session_db(db_path: Path) -> sqlite3.Connection:
    """Create session database with recording sessions/system events/metadata."""
    return _init(db_path, _SESSION_SCHEMA)

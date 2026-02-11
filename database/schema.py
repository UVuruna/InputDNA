"""
Database schema — all CREATE TABLE statements.

Called once on first run. Safe to call again (uses IF NOT EXISTS).
Also sets SQLite pragmas for optimal performance.
"""

import sqlite3
from pathlib import Path


def init_db(db_path: Path) -> sqlite3.Connection:
    """
    Create database, set pragmas, create all tables.
    Returns an open connection.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))

    # ── Performance pragmas ────────────────────────────────
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA cache_size=-64000;
        PRAGMA temp_store=MEMORY;
        PRAGMA mmap_size=268435456;
    """)

    # ── Create tables ──────────────────────────────────────
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


_SCHEMA = """

-- ══════════════════════════════════════════════════════════
-- MOUSE: Movement Sessions
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS movements (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
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
    recording_session_id INTEGER REFERENCES recording_sessions(id),
    timestamp            TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS path_points (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id  INTEGER NOT NULL REFERENCES movements(id),
    seq          INTEGER NOT NULL,
    x            INTEGER NOT NULL,
    y            INTEGER NOT NULL,
    t_ns         INTEGER NOT NULL
);

-- ══════════════════════════════════════════════════════════
-- MOUSE: Click Sequences (single / double / spam)
-- ══════════════════════════════════════════════════════════

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

-- ══════════════════════════════════════════════════════════
-- MOUSE: Drag Operations
-- ══════════════════════════════════════════════════════════

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

CREATE TABLE IF NOT EXISTS drag_points (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    drag_id  INTEGER NOT NULL REFERENCES drags(id),
    seq      INTEGER NOT NULL,
    x        INTEGER NOT NULL,
    y        INTEGER NOT NULL,
    t_ns     INTEGER NOT NULL
);

-- ══════════════════════════════════════════════════════════
-- MOUSE: Scroll Events
-- ══════════════════════════════════════════════════════════

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

-- ══════════════════════════════════════════════════════════
-- KEYBOARD: Individual Keystrokes
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS keystrokes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_code         INTEGER NOT NULL,
    key_name          TEXT    NOT NULL,
    press_duration_ms REAL    NOT NULL,
    modifier_state    TEXT    NOT NULL,
    hand              TEXT    NOT NULL,
    finger            TEXT    NOT NULL,
    t_ns              INTEGER NOT NULL,
    timestamp         TEXT    NOT NULL
);

-- ══════════════════════════════════════════════════════════
-- KEYBOARD: Key Transitions (scan code pairs + delay)
-- ══════════════════════════════════════════════════════════

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

-- ══════════════════════════════════════════════════════════
-- KEYBOARD: Shortcuts
-- ══════════════════════════════════════════════════════════

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

-- ══════════════════════════════════════════════════════════
-- RECORDING SESSIONS
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS recording_sessions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at             TEXT    NOT NULL,
    ended_at               TEXT,
    total_movements        INTEGER DEFAULT 0,
    total_clicks           INTEGER DEFAULT 0,
    total_keystrokes       INTEGER DEFAULT 0,
    perf_counter_start_ns  INTEGER NOT NULL
);

-- ══════════════════════════════════════════════════════════
-- METADATA (key-value store)
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

"""

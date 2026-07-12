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


def apply_pragmas(conn: sqlite3.Connection) -> None:
    """
    Apply the recorder's performance pragmas to a connection.

    Pragmas like synchronous, cache_size, temp_store and mmap_size are
    per-connection (only journal_mode=WAL persists in the file), so every
    connection that writes on the hot path — not just the one that created
    the schema — must set them, or it silently runs at SQLite defaults
    (synchronous=FULL, tiny cache).
    """
    conn.executescript(_PRAGMAS)


def _init(db_path: Path, schema: str) -> sqlite3.Connection:
    """Create database, set pragmas, create tables. Returns open connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    apply_pragmas(conn)
    conn.executescript(schema)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str,
                    columns: list[tuple[str, str]]) -> None:
    """
    Add columns that are missing from an existing table (idempotent).

    CREATE TABLE IF NOT EXISTS never alters an existing table, so a schema
    that grows a column would silently keep the old layout on databases
    created by an earlier version. This adds any missing column via
    ALTER TABLE ADD COLUMN — a non-destructive, in-place operation that
    backfills existing rows with the column default (NULL unless specified).
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


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
) WITHOUT ROWID;

-- Click sequences (single / double / spam)
-- movement_id: FK to movements (NULL if click without preceding movement)
-- recording_session_id: owning recording session (movements/drags encode this in
--   their app-generated id; AUTOINCREMENT tables carry it as an explicit column)
-- button, click_count, total_duration_ms: all derivable from click_details
CREATE TABLE IF NOT EXISTS click_sequences (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id           INTEGER REFERENCES movements(id),
    button                TEXT    NOT NULL,
    recording_session_id  INTEGER NOT NULL DEFAULT 0
);

-- Individual clicks within sequences
-- No id column — composite PK (sequence_id, seq) is sufficient
-- x, y: press (button-down) position of this click. NULL for rows written
--       before click coordinates were captured (legacy data).
-- delay_since_prev_ms: derivable from t_ns differences in post-processing
CREATE TABLE IF NOT EXISTS click_details (
    sequence_id       INTEGER NOT NULL REFERENCES click_sequences(id),
    seq               INTEGER NOT NULL,
    press_duration_ms REAL    NOT NULL,
    x                 INTEGER,
    y                 INTEGER,
    t_ns              INTEGER NOT NULL,
    PRIMARY KEY (sequence_id, seq)
) WITHOUT ROWID;

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
) WITHOUT ROWID;

-- Scroll wheel events
-- dx, dy: signed scroll amount per axis (dy = vertical +up/-down, dx = horizontal
--   +right/-left). Preserves the axis, which the legacy merged `delta` loses.
-- delta: legacy merged column (= dy if dy != 0 else dx), retained so existing
--   readers keep working; NULL-free but derivable from dx/dy.
-- timestamp: derivable from t_ns in post-processing
CREATE TABLE IF NOT EXISTS scrolls (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id           INTEGER REFERENCES movements(id),
    delta                 INTEGER NOT NULL,
    dx                    INTEGER,
    dy                    INTEGER,
    x                     INTEGER NOT NULL,
    y                     INTEGER NOT NULL,
    t_ns                  INTEGER NOT NULL,
    recording_session_id  INTEGER NOT NULL DEFAULT 0
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
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_code             INTEGER NOT NULL,
    press_duration_ms     REAL    NOT NULL,
    modifier_state        INTEGER NOT NULL,
    t_ns                  INTEGER NOT NULL,
    recording_session_id  INTEGER NOT NULL DEFAULT 0
);

-- Delay between consecutive keys (scan code pairs)
-- from_key_name, to_key_name: derivable from scan codes in post-processing
-- delay_ms: derivable from t_ns differences in post-processing
-- is_repeat: 1 = OS auto-repeat (held key), a from_scan==to_scan run at the
--   hardware repeat rate. Excluded from digraph/flight-time stats; kept as a
--   hold-to-repeat behavioral signal. 0 = genuine consecutive key press.
CREATE TABLE IF NOT EXISTS key_transitions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scan             INTEGER NOT NULL,
    to_scan               INTEGER NOT NULL,
    typing_mode           TEXT    NOT NULL,
    is_repeat             INTEGER NOT NULL DEFAULT 0,
    t_ns                  INTEGER NOT NULL,
    recording_session_id  INTEGER NOT NULL DEFAULT 0
);

-- Keyboard shortcut timing profiles
-- shortcut_name, main_key_name, timestamp: derivable in post-processing
CREATE TABLE IF NOT EXISTS shortcuts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    modifier_scans        TEXT    NOT NULL,
    main_scan             INTEGER NOT NULL,
    modifier_to_main_ms   REAL    NOT NULL,
    main_hold_ms          REAL    NOT NULL,
    overlap_ms            REAL    NOT NULL,
    total_ms              REAL    NOT NULL,
    release_order         TEXT    NOT NULL,
    t_ns                  INTEGER NOT NULL,
    recording_session_id  INTEGER NOT NULL DEFAULT 0
);

"""


# ══════════════════════════════════════════════════════════════
# SESSION DATABASE
# ══════════════════════════════════════════════════════════════

_SESSION_SCHEMA = """

-- Recording periods (start/end/counts)
-- perf_counter_start_ns / perf_counter_end_ns: monotonic bookends of the session,
--   giving a recoverable boundary even when ended_at (wall clock) is NULL on crash
CREATE TABLE IF NOT EXISTS recording_sessions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at             TEXT    NOT NULL,
    ended_at               TEXT,
    total_movements        INTEGER DEFAULT 0,
    total_clicks           INTEGER DEFAULT 0,
    total_keystrokes       INTEGER DEFAULT 0,
    perf_counter_start_ns  INTEGER NOT NULL,
    perf_counter_end_ns    INTEGER
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

_SESSION_ID_COL = ("recording_session_id",
                   "recording_session_id INTEGER NOT NULL DEFAULT 0")


def init_mouse_db(db_path: Path) -> sqlite3.Connection:
    """Create mouse database with movement/click/drag/scroll tables."""
    conn = _init(db_path, _MOUSE_SCHEMA)
    # Backfill columns added after the initial delta_v3 release.
    _ensure_columns(conn, "click_details", [
        ("x", "x INTEGER"),
        ("y", "y INTEGER"),
    ])
    _ensure_columns(conn, "click_sequences", [_SESSION_ID_COL])
    _ensure_columns(conn, "scrolls", [
        ("dx", "dx INTEGER"),
        ("dy", "dy INTEGER"),
        _SESSION_ID_COL,
    ])
    # Signal schema version to post-processing readers
    conn.execute(
        "INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)",
        ("path_encoding", "delta_v3"),
    )
    conn.commit()
    return conn


def init_keyboard_db(db_path: Path) -> sqlite3.Connection:
    """Create keyboard database with keystroke/transition/shortcut tables."""
    conn = _init(db_path, _KEYBOARD_SCHEMA)
    # Backfill columns added after the initial delta_v3 release.
    _ensure_columns(conn, "key_transitions", [
        ("is_repeat", "is_repeat INTEGER NOT NULL DEFAULT 0"),
        _SESSION_ID_COL,
    ])
    _ensure_columns(conn, "keystrokes", [_SESSION_ID_COL])
    _ensure_columns(conn, "shortcuts", [_SESSION_ID_COL])
    conn.commit()
    return conn


def init_session_db(db_path: Path) -> sqlite3.Connection:
    """Create session database with recording sessions/system events/metadata."""
    conn = _init(db_path, _SESSION_SCHEMA)
    _ensure_columns(conn, "recording_sessions", [
        ("perf_counter_end_ns", "perf_counter_end_ns INTEGER"),
    ])
    conn.commit()
    return conn

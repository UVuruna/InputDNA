"""
Processed record data classes — produced by processors, consumed by DB writer.

Each record type has a write_to_db(conn) method that performs the actual
INSERT into the appropriate SQLite table(s).

Path points use delta encoding: seq=0 stores absolute (x, y),
seq>0 stores deltas from the previous point (dx, dy).
Each point also stores dt_us: microseconds elapsed since the previous point.
seq=0 always has dt_us=0 (timing anchored by start_t_ns in the parent record).
Full timing reconstruction: t_ns[0]=start_t_ns, t_ns[i]=t_ns[i-1]+dt_us[i]*1000
Metadata key 'path_encoding'='delta_v3' signals this schema to readers.
"""

from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────────────────────
# SHARED
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class PathPoint:
    """Single coordinate in a mouse path or drag path."""
    x: int
    y: int
    t_ns: int   # Used for downsampling, computing dt_us between points,
                # and extracting start_t_ns / end_t_ns on the movement/drag.
                # NOT written to DB directly — stored as dt_us deltas instead.


def _delta_encode_points(parent_id: int, points: List[PathPoint]) -> list[tuple]:
    """
    Delta-encode a list of PathPoints for DB storage.

    Returns list of (parent_id, seq, x_or_dx, y_or_dy, dt_us) tuples.
    First point (seq=0): absolute (x, y), dt_us=0 (timing from parent start_t_ns).
    Subsequent points: delta (dx, dy), dt_us=microseconds since previous point.
    Full timing reconstruction: t_ns[0]=start_t_ns, t_ns[i]=t_ns[i-1]+dt_us[i]*1000
    """
    if not points:
        return []
    rows = [(parent_id, 0, points[0].x, points[0].y, 0)]
    for i in range(1, len(points)):
        dt_us = (points[i].t_ns - points[i - 1].t_ns) // 1000
        rows.append((
            parent_id, i,
            points[i].x - points[i - 1].x,
            points[i].y - points[i - 1].y,
            dt_us,
        ))
    return rows


# ─────────────────────────────────────────────────────────────
# MOUSE RECORDS
# ─────────────────────────────────────────────────────────────

@dataclass
class MovementSession:
    """
    Complete mouse movement from first move to end event.
    Contains the full path (list of PathPoints) plus bookend timestamps.

    movement_id is app-generated: session_num * 1_000_000 + seq.
    This makes IDs globally unique across DB files and allows the
    processor to link clicks/scrolls to their preceding movement
    without waiting for DB auto-increment.

    start_t_ns / end_t_ns are perf_counter_ns bookends. All per-point
    timing is reconstructed in post-processing — no t_ns stored per point.
    """
    _db_target = "mouse"

    movement_id: int            # App-generated: session * 1_000_000 + seq
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    end_event: str              # "left_click", "right_click", "scroll_up", "idle", etc.
    start_t_ns: int
    end_t_ns: int
    path_points: List[PathPoint]

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO movements
               (id, start_x, start_y, end_x, end_y, end_event, start_t_ns, end_t_ns)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.movement_id, self.start_x, self.start_y, self.end_x,
             self.end_y, self.end_event, self.start_t_ns, self.end_t_ns)
        )
        if self.path_points:
            cur.executemany(
                "INSERT INTO path_points (movement_id, seq, x, y, dt_us) VALUES (?,?,?,?,?)",
                _delta_encode_points(self.movement_id, self.path_points),
            )


@dataclass(slots=True)
class SingleClick:
    """One click within a click sequence."""
    press_duration_ms: float
    x: int              # Press (button-down) position
    y: int
    t_ns: int


@dataclass
class ClickSequence:
    """
    Group of clicks: single (1), double (2), or spam (3+).
    All clicks are same button and within CLICK_SEQUENCE_GAP_MS of each other.
    """
    _db_target = "mouse"

    button: str                     # "left", "right", "middle"
    clicks: List[SingleClick]
    movement_id: Optional[int]      # Preceding movement (bound at first mouse-down)
    recording_session_id: int = 0   # Owning recording session (set by EventProcessor)

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO click_sequences (movement_id, button, recording_session_id) "
            "VALUES (?,?,?)",
            (self.movement_id, self.button, self.recording_session_id)
        )
        seq_id = cur.lastrowid
        cur.executemany(
            """INSERT INTO click_details
               (sequence_id, seq, press_duration_ms, x, y, t_ns)
               VALUES (?,?,?,?,?,?)""",
            [(seq_id, i, c.press_duration_ms, c.x, c.y, c.t_ns)
             for i, c in enumerate(self.clicks)]
        )


@dataclass
class DragRecord:
    """Click-hold-move-release operation."""
    _db_target = "mouse"

    drag_id: int                # App-generated: session * 1_000_000 + seq
    button: str
    start_x: int
    start_y: int
    start_t_ns: int
    end_t_ns: int
    path_points: List[PathPoint]

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO drags
               (id, button, start_x, start_y, start_t_ns, end_t_ns)
               VALUES (?,?,?,?,?,?)""",
            (self.drag_id, self.button, self.start_x, self.start_y,
             self.start_t_ns, self.end_t_ns)
        )
        if self.path_points:
            cur.executemany(
                "INSERT INTO drag_points (drag_id, seq, x, y, dt_us) VALUES (?,?,?,?,?)",
                _delta_encode_points(self.drag_id, self.path_points),
            )


@dataclass
class ScrollEvent:
    """Single scroll event."""
    _db_target = "mouse"

    movement_id: Optional[int]  # Preceding movement (nullable)
    dx: int                     # Horizontal scroll (+right / -left)
    dy: int                     # Vertical scroll (+up / -down)
    x: int
    y: int
    t_ns: int
    recording_session_id: int = 0

    @property
    def delta(self) -> int:
        """Legacy merged scroll amount: vertical if present, else horizontal."""
        return self.dy if self.dy != 0 else self.dx

    def write_to_db(self, conn):
        conn.execute(
            "INSERT INTO scrolls (movement_id, delta, dx, dy, x, y, t_ns, "
            "recording_session_id) VALUES (?,?,?,?,?,?,?,?)",
            (self.movement_id, self.delta, self.dx, self.dy, self.x, self.y,
             self.t_ns, self.recording_session_id)
        )


# ─────────────────────────────────────────────────────────────
# KEYBOARD RECORDS
# ─────────────────────────────────────────────────────────────

@dataclass
class KeystrokeRecord:
    """One complete key press (down + up) with duration."""
    _db_target = "keyboard"

    scan_code: int
    press_duration_ms: float
    modifier_state: int         # Bitmask: bit0=Ctrl, bit1=Alt, bit2=Shift, bit3=Win
    t_ns: int
    recording_session_id: int = 0

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO keystrokes
               (scan_code, press_duration_ms, modifier_state, t_ns,
                recording_session_id)
               VALUES (?,?,?,?,?)""",
            (self.scan_code, self.press_duration_ms, self.modifier_state,
             self.t_ns, self.recording_session_id)
        )


@dataclass
class KeyTransitionRecord:
    """Delay between two consecutive key presses (scan code pair)."""
    _db_target = "keyboard"

    from_scan: int
    to_scan: int
    typing_mode: str            # "text", "shortcut", "numpad", "code"
    t_ns: int
    is_repeat: int = 0          # 1 = OS auto-repeat run (held key), not a digraph
    recording_session_id: int = 0

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO key_transitions
               (from_scan, to_scan, typing_mode, is_repeat, t_ns,
                recording_session_id)
               VALUES (?,?,?,?,?,?)""",
            (self.from_scan, self.to_scan, self.typing_mode,
             self.is_repeat, self.t_ns, self.recording_session_id)
        )


@dataclass
class ShortcutRecord:
    """Keyboard shortcut with full timing profile."""
    _db_target = "keyboard"

    modifier_scans: str         # JSON array of modifier scan codes
    main_scan: int              # Main key scan code
    modifier_to_main_ms: float  # Modifier down → main key down
    main_hold_ms: float         # Main key down → main key up
    overlap_ms: float           # Both held simultaneously
    total_ms: float             # Full execution time
    release_order: str          # "main_first" or "modifier_first"
    t_ns: int
    recording_session_id: int = 0

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO shortcuts
               (modifier_scans, main_scan, modifier_to_main_ms, main_hold_ms,
                overlap_ms, total_ms, release_order, t_ns, recording_session_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (self.modifier_scans, self.main_scan, self.modifier_to_main_ms,
             self.main_hold_ms, self.overlap_ms, self.total_ms,
             self.release_order, self.t_ns, self.recording_session_id)
        )


# ─────────────────────────────────────────────────────────────
# SYSTEM EVENTS
# ─────────────────────────────────────────────────────────────

@dataclass
class SystemEventRecord:
    """Tracks a system state change (mouse speed, resolution, layout, etc.)."""
    _db_target = "session"

    key: str        # e.g. "mouse_speed", "screen_resolution", "mouse_acceleration"
    value: str
    t_ns: int
    timestamp: str

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO system_events (key, value, t_ns, timestamp)
               VALUES (?,?,?,?)""",
            (self.key, self.value, self.t_ns, self.timestamp)
        )


# ─────────────────────────────────────────────────────────────
# RECORDING SESSION
# ─────────────────────────────────────────────────────────────

@dataclass
class RecordingSessionRecord:
    """One recording period (start → stop/quit)."""
    _db_target = "session"

    started_at: str
    ended_at: Optional[str] = None
    total_movements: int = 0
    total_clicks: int = 0
    total_keystrokes: int = 0
    perf_counter_start_ns: int = 0
    perf_counter_end_ns: Optional[int] = None
    _db_id: Optional[int] = None

    def write_start(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO recording_sessions
               (started_at, perf_counter_start_ns)
               VALUES (?,?)""",
            (self.started_at, self.perf_counter_start_ns)
        )
        self._db_id = cur.lastrowid
        return self._db_id

    def write_end(self, conn):
        if self._db_id is None:
            return
        conn.execute(
            """UPDATE recording_sessions
               SET ended_at=?, total_movements=?, total_clicks=?,
                   total_keystrokes=?, perf_counter_end_ns=?
               WHERE id=?""",
            (self.ended_at, self.total_movements, self.total_clicks,
             self.total_keystrokes, self.perf_counter_end_ns, self._db_id)
        )

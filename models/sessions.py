"""
Processed record data classes — produced by processors, consumed by DB writer.

Each record type has a write_to_db(conn) method that performs the actual
INSERT into the appropriate SQLite table(s).
"""

from dataclasses import dataclass, field
from typing import List, Optional
import math


# ─────────────────────────────────────────────────────────────
# SHARED
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class PathPoint:
    """Single coordinate in a mouse path or drag path."""
    x: int
    y: int
    t_ns: int


# ─────────────────────────────────────────────────────────────
# MOUSE RECORDS
# ─────────────────────────────────────────────────────────────

@dataclass
class MovementSession:
    """
    Complete mouse movement from first move to end event.
    Contains the full path (list of PathPoints) plus summary metrics.
    """
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    end_event: str              # "left_click", "right_click", "scroll_up", "idle", etc.
    duration_ms: float
    distance_px: float          # Euclidean start→end
    path_length_px: float       # Sum of all segments
    point_count: int
    path_points: List[PathPoint]
    hour_of_day: int            # 0-23
    day_of_week: int            # 0=Monday, 6=Sunday
    recording_session_id: int
    timestamp: str              # ISO wall clock

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO movements
               (start_x, start_y, end_x, end_y, end_event, duration_ms,
                distance_px, path_length_px, point_count, hour_of_day,
                day_of_week, recording_session_id, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self.start_x, self.start_y, self.end_x, self.end_y,
             self.end_event, self.duration_ms, self.distance_px,
             self.path_length_px, self.point_count, self.hour_of_day,
             self.day_of_week, self.recording_session_id, self.timestamp)
        )
        mov_id = cur.lastrowid
        if self.path_points:
            cur.executemany(
                "INSERT INTO path_points (movement_id, seq, x, y, t_ns) VALUES (?,?,?,?,?)",
                [(mov_id, i, p.x, p.y, p.t_ns) for i, p in enumerate(self.path_points)]
            )


@dataclass(slots=True)
class SingleClick:
    """One click within a click sequence."""
    x: int
    y: int
    press_duration_ms: float
    delay_since_prev_ms: float  # 0.0 for first click in sequence
    t_ns: int


@dataclass
class ClickSequence:
    """
    Group of clicks: single (1), double (2), or spam (3+).
    All clicks are same button and within CLICK_SEQUENCE_GAP_MS of each other.
    """
    button: str                     # "left", "right", "middle"
    click_count: int
    clicks: List[SingleClick]
    total_duration_ms: float        # First click start → last click end
    movement_id: Optional[int]      # Preceding movement (set after movement is written)
    timestamp: str

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO click_sequences
               (movement_id, button, click_count, total_duration_ms, x, y, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (self.movement_id, self.button, self.click_count,
             self.total_duration_ms,
             self.clicks[0].x, self.clicks[0].y, self.timestamp)
        )
        seq_id = cur.lastrowid
        cur.executemany(
            """INSERT INTO click_details
               (sequence_id, seq, x, y, press_duration_ms, delay_since_prev_ms, t_ns)
               VALUES (?,?,?,?,?,?,?)""",
            [(seq_id, i, c.x, c.y, c.press_duration_ms, c.delay_since_prev_ms, c.t_ns)
             for i, c in enumerate(self.clicks)]
        )


@dataclass
class DragRecord:
    """Click-hold-move-release operation."""
    button: str
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: float
    path_points: List[PathPoint]
    timestamp: str

    def write_to_db(self, conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO drags
               (button, start_x, start_y, end_x, end_y, duration_ms, point_count, timestamp)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.button, self.start_x, self.start_y, self.end_x, self.end_y,
             self.duration_ms, len(self.path_points), self.timestamp)
        )
        drag_id = cur.lastrowid
        if self.path_points:
            cur.executemany(
                "INSERT INTO drag_points (drag_id, seq, x, y, t_ns) VALUES (?,?,?,?,?)",
                [(drag_id, i, p.x, p.y, p.t_ns) for i, p in enumerate(self.path_points)]
            )


@dataclass(slots=True)
class ScrollEvent:
    """Single scroll event."""
    movement_id: Optional[int]  # Preceding movement (nullable)
    direction: str              # "up", "down", "left", "right"
    delta: int                  # Scroll amount
    x: int
    y: int
    t_ns: int
    timestamp: str

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO scrolls
               (movement_id, direction, delta, x, y, t_ns, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (self.movement_id, self.direction, self.delta,
             self.x, self.y, self.t_ns, self.timestamp)
        )


# ─────────────────────────────────────────────────────────────
# KEYBOARD RECORDS
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class KeystrokeRecord:
    """One complete key press (down + up) with duration."""
    scan_code: int
    vkey: int                   # Virtual key code (layout-dependent)
    key_name: str               # For human readability only
    press_duration_ms: float
    modifier_state: str         # JSON string
    active_layout: str          # Keyboard layout ID at time of press
    hand: str                   # "left", "right", "unknown"
    finger: str                 # "pinky", "ring", "middle", "index", "thumb", "unknown"
    t_ns: int
    timestamp: str

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO keystrokes
               (scan_code, vkey, key_name, press_duration_ms, modifier_state,
                active_layout, hand, finger, t_ns, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.scan_code, self.vkey, self.key_name, self.press_duration_ms,
             self.modifier_state, self.active_layout, self.hand, self.finger,
             self.t_ns, self.timestamp)
        )


@dataclass(slots=True)
class KeyTransitionRecord:
    """Delay between two consecutive key presses (scan code pair)."""
    from_scan: int
    to_scan: int
    from_key_name: str          # For readability
    to_key_name: str            # For readability
    delay_ms: float
    typing_mode: str            # "text", "shortcut", "numpad", "code"
    t_ns: int

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO key_transitions
               (from_scan, to_scan, from_key_name, to_key_name,
                delay_ms, typing_mode, t_ns)
               VALUES (?,?,?,?,?,?,?)""",
            (self.from_scan, self.to_scan, self.from_key_name,
             self.to_key_name, self.delay_ms, self.typing_mode, self.t_ns)
        )


@dataclass(slots=True)
class ShortcutRecord:
    """Keyboard shortcut with full timing profile."""
    shortcut_name: str          # "Ctrl+C", "Alt+Tab", etc.
    modifier_scans: str         # JSON array of modifier scan codes
    main_scan: int              # Main key scan code
    main_key_name: str          # For readability
    modifier_to_main_ms: float  # Modifier down → main key down
    main_hold_ms: float         # Main key down → main key up
    overlap_ms: float           # Both held simultaneously
    total_ms: float             # Full execution time
    release_order: str          # "main_first" or "modifier_first"
    t_ns: int
    timestamp: str

    def write_to_db(self, conn):
        conn.execute(
            """INSERT INTO shortcuts
               (shortcut_name, modifier_scans, main_scan, main_key_name,
                modifier_to_main_ms, main_hold_ms, overlap_ms, total_ms,
                release_order, t_ns, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (self.shortcut_name, self.modifier_scans, self.main_scan,
             self.main_key_name, self.modifier_to_main_ms, self.main_hold_ms,
             self.overlap_ms, self.total_ms, self.release_order,
             self.t_ns, self.timestamp)
        )


# ─────────────────────────────────────────────────────────────
# SYSTEM EVENTS
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class SystemEventRecord:
    """Tracks a system state change (mouse speed, resolution, layout, etc.)."""
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
    started_at: str
    ended_at: Optional[str] = None
    total_movements: int = 0
    total_clicks: int = 0
    total_keystrokes: int = 0
    perf_counter_start_ns: int = 0
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
               SET ended_at=?, total_movements=?, total_clicks=?, total_keystrokes=?
               WHERE id=?""",
            (self.ended_at, self.total_movements, self.total_clicks,
             self.total_keystrokes, self._db_id)
        )

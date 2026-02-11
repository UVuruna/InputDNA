"""
Raw event data classes — produced by listeners.

These represent the rawest form of input data, directly from the OS.
All timestamps are perf_counter_ns (nanoseconds, monotonic, high-precision).
"""

from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────
# MOUSE EVENTS
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class RawMouseMove:
    """Cursor moved to a new position."""
    x: int
    y: int
    t_ns: int

@dataclass(slots=True)
class RawMouseClick:
    """Mouse button pressed or released."""
    x: int
    y: int
    button: str    # "left", "right", "middle"
    pressed: bool  # True = down, False = up
    t_ns: int

@dataclass(slots=True)
class RawMouseScroll:
    """Scroll wheel event."""
    x: int
    y: int
    dx: int  # Horizontal scroll (usually 0)
    dy: int  # Vertical scroll (+1 = up, -1 = down)
    t_ns: int


# ─────────────────────────────────────────────────────────────
# KEYBOARD EVENTS
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class RawKeyPress:
    """Keyboard key pressed down."""
    scan_code: int          # Physical key position (layout-independent)
    key_name: str           # Human-readable name (for DB readability only)
    t_ns: int
    modifier_state: dict    # {"ctrl": bool, "alt": bool, "shift": bool, "win": bool}

@dataclass(slots=True)
class RawKeyRelease:
    """Keyboard key released."""
    scan_code: int
    key_name: str
    t_ns: int
    press_duration_ms: float  # Calculated: release_t - press_t

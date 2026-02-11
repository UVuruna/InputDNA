"""
System state monitor.

Periodically checks system settings that affect input behavior:
- Windows mouse speed (1-20)
- Mouse acceleration (enhance pointer precision)
- Screen resolution
- Keyboard layout (foreground window)

On recording start, captures initial state. Then polls at a configurable
interval, emitting SystemEventRecord only when a value changes.

Polling rate is estimated separately from mouse move event timestamps
(see estimate_polling_rate).
"""

import ctypes
import logging
import threading
import time
from typing import Callable, Optional

import config
from models.sessions import SystemEventRecord
from utils.timing import now_ns, wall_clock_iso

logger = logging.getLogger(__name__)

_user32 = ctypes.windll.user32

# ─────────────────────────────────────────────────────────────
# SYSTEM STATE READERS
# ─────────────────────────────────────────────────────────────

def get_mouse_speed() -> int:
    """
    Get Windows mouse speed setting (1-20).
    Control Panel → Mouse → Pointer Options → Motion slider.
    """
    speed = ctypes.c_int()
    ctypes.windll.user32.SystemParametersInfoW(0x0070, 0, ctypes.byref(speed), 0)  # SPI_GETMOUSESPEED
    return speed.value


def get_mouse_acceleration() -> bool:
    """
    Check if 'Enhance pointer precision' (mouse acceleration) is enabled.
    Returns True if acceleration is on.
    """
    params = (ctypes.c_int * 3)()
    ctypes.windll.user32.SystemParametersInfoW(0x0003, 0, params, 0)  # SPI_GETMOUSE
    # params[2] is the acceleration flag: 0=off, nonzero=on
    return bool(params[2])


def get_screen_resolution() -> str:
    """
    Get primary monitor resolution as 'WIDTHxHEIGHT' string.
    Uses virtual screen metrics to account for multi-monitor setups.
    """
    # SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79 (total virtual desktop)
    # SM_CXSCREEN=0, SM_CYSCREEN=1 (primary monitor)
    w = _user32.GetSystemMetrics(0)
    h = _user32.GetSystemMetrics(1)
    return f"{w}x{h}"


def get_keyboard_layout() -> str:
    """Get active keyboard layout for the foreground window."""
    hwnd = _user32.GetForegroundWindow()
    thread_id = _user32.GetWindowThreadProcessId(hwnd, None)
    layout_id = _user32.GetKeyboardLayout(thread_id)
    return hex(layout_id & 0xFFFFFFFF)


def get_all_state() -> dict[str, str]:
    """Read all monitored system settings as a dict."""
    return {
        "mouse_speed": str(get_mouse_speed()),
        "mouse_acceleration": str(get_mouse_acceleration()),
        "screen_resolution": get_screen_resolution(),
        "keyboard_layout": get_keyboard_layout(),
    }


# ─────────────────────────────────────────────────────────────
# POLLING RATE ESTIMATION
# ─────────────────────────────────────────────────────────────

class PollingRateEstimator:
    """
    Estimates mouse polling rate from move event timestamps.

    Feed it timestamps of consecutive mouse move events. After enough
    samples, it calculates the median interval and derives Hz.
    """

    def __init__(self, sample_count: int = config.POLLING_RATE_SAMPLE_COUNT):
        self._sample_count = sample_count
        self._intervals_ns: list[int] = []
        self._last_t_ns: Optional[int] = None
        self._estimated_hz: Optional[int] = None

    def add_move_timestamp(self, t_ns: int):
        """Feed a mouse move event timestamp. Call for each RawMouseMove."""
        if self._estimated_hz is not None:
            return  # Already estimated

        if self._last_t_ns is not None:
            interval = t_ns - self._last_t_ns
            if interval > 0:
                self._intervals_ns.append(interval)

        self._last_t_ns = t_ns

        if len(self._intervals_ns) >= self._sample_count:
            self._calculate()

    def _calculate(self):
        """Calculate polling rate from collected intervals."""
        sorted_intervals = sorted(self._intervals_ns)
        # Use median to avoid outlier influence
        median_ns = sorted_intervals[len(sorted_intervals) // 2]
        if median_ns > 0:
            self._estimated_hz = round(1_000_000_000 / median_ns)
            logger.info(f"Mouse polling rate estimated: ~{self._estimated_hz} Hz")

    @property
    def estimated_hz(self) -> Optional[int]:
        return self._estimated_hz


# ─────────────────────────────────────────────────────────────
# SYSTEM MONITOR (change detection thread)
# ─────────────────────────────────────────────────────────────

class SystemMonitor:
    """
    Polls system state periodically and emits SystemEventRecord
    when any monitored value changes.

    Usage:
        monitor = SystemMonitor(on_event=db_writer.put)
        monitor.start()    # Records initial state + starts polling
        ...
        monitor.stop()
    """

    def __init__(self, on_event: Callable[[SystemEventRecord], None]):
        self._on_event = on_event
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_state: dict[str, str] = {}

    def start(self):
        """Record initial state and start polling for changes."""
        self._running = True

        # Capture and emit initial state
        self._last_state = get_all_state()
        t = now_ns()
        ts = wall_clock_iso()
        for key, value in self._last_state.items():
            self._on_event(SystemEventRecord(key=key, value=value, t_ns=t, timestamp=ts))
        logger.info(f"System monitor: initial state recorded ({len(self._last_state)} settings)")

        # Start polling thread
        self._thread = threading.Thread(target=self._poll_loop, name="system-monitor", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the polling thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("System monitor stopped")

    @property
    def current_state(self) -> dict[str, str]:
        """Get last known system state (for GUI display)."""
        return self._last_state.copy()

    def _poll_loop(self):
        """Poll system state at configured interval, emit changes."""
        while self._running:
            time.sleep(config.SYSTEM_MONITOR_INTERVAL_S)
            if not self._running:
                break

            current = get_all_state()
            t = now_ns()
            ts = wall_clock_iso()

            for key, value in current.items():
                if value != self._last_state.get(key):
                    logger.info(f"System change: {key} = {self._last_state.get(key)} → {value}")
                    self._on_event(SystemEventRecord(key=key, value=value, t_ns=t, timestamp=ts))

            self._last_state = current

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


def speed_to_multiplier(speed: int) -> float:
    """
    Convert Windows pointer speed (SPI_GETMOUSESPEED, 1-20) to cursor multiplier.

    With Enhanced Pointer Precision OFF, cursor movement is:
        cursor_pixels = mouse_counts * multiplier

    Default speed is 10 → multiplier 1.0 (1:1 mapping).

    Lookup table derived from Windows pointer ballistics:
      Speed  1-2:  multiplier = speed / 32
      Speed  3-10: multiplier = (speed - 2) / 8
      Speed 11-20: multiplier = (speed - 6) / 4
    """
    if speed <= 0:
        return 1.0
    if speed <= 2:
        return speed / 32.0
    elif speed <= 10:
        return (speed - 2) / 8.0
    else:
        return (speed - 6) / 4.0


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
    """Get active keyboard layout name for the foreground window.

    Returns human-readable name like 'English (United States)'.
    Falls back to hex layout ID if name lookup fails.
    """
    hwnd = _user32.GetForegroundWindow()
    thread_id = _user32.GetWindowThreadProcessId(hwnd, None)
    layout_id = _user32.GetKeyboardLayout(thread_id)
    lang_id = layout_id & 0xFFFF

    # LOCALE_SLANGUAGE = 0x2 — full localized language name
    buf = ctypes.create_unicode_buffer(256)
    if ctypes.windll.kernel32.GetLocaleInfoW(lang_id, 0x2, buf, 256) and buf.value:
        return buf.value

    return hex(layout_id & 0xFFFFFFFF)


def get_system_double_click_time() -> int:
    """
    Get Windows system double-click time in milliseconds.
    This is the maximum interval Windows considers a double-click.
    Control Panel → Mouse → Buttons → Double-click speed.
    """
    return _user32.GetDoubleClickTime()


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
        """Calculate polling rate from collected intervals.

        Uses 10th percentile instead of median.  The shortest intervals
        represent back-to-back hardware polls where the cursor actually
        moved.  Slow mouse movement produces longer gaps (zero-delta
        polls are suppressed by Windows), inflating the median.
        """
        sorted_intervals = sorted(self._intervals_ns)
        idx = max(0, len(sorted_intervals) // 10)
        p10_ns = sorted_intervals[idx]
        if p10_ns > 0:
            self._estimated_hz = round(1_000_000_000 / p10_ns)
            logger.info(f"Mouse polling rate estimated: ~{self._estimated_hz} Hz "
                        f"(p10={p10_ns/1e6:.2f} ms from {len(sorted_intervals)} samples)")

    @property
    def estimated_hz(self) -> Optional[int]:
        return self._estimated_hz


def start_polling_estimation(on_done: Optional[Callable[[int], None]] = None) -> PollingRateEstimator:
    """
    Start a temporary mouse listener to estimate polling rate.

    Runs in the background. Once enough samples are collected, the
    listener stops itself and calls on_done(hz) on the listener thread.
    Also sets config.ESTIMATED_POLLING_HZ.

    Returns the estimator so callers can check .estimated_hz later.
    """
    from pynput import mouse as _mouse
    from utils.timing import now_ns as _now_ns

    estimator = PollingRateEstimator()
    holder: dict = {"listener": None}

    def _on_move(x, y):
        t = _now_ns()
        estimator.add_move_timestamp(t)
        if estimator.estimated_hz is not None:
            raw_hz = estimator.estimated_hz
            snapped = config.snap_polling_rate(raw_hz)
            config.ESTIMATED_POLLING_HZ = snapped
            logger.info(f"Polling rate set: raw ~{raw_hz} Hz → snapped {snapped} Hz")
            if on_done is not None:
                on_done(snapped)
            listener = holder.get("listener")
            if listener is not None:
                listener.stop()

    listener = _mouse.Listener(on_move=_on_move)
    listener.daemon = True
    holder["listener"] = listener
    listener.start()
    logger.info("Polling rate estimation started (temporary mouse listener)")
    return estimator


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
        self._stop_event = threading.Event()
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
        """Stop the polling thread. Wakes it immediately via Event."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("System monitor stopped")

    @property
    def current_state(self) -> dict[str, str]:
        """Get last known system state (for GUI display)."""
        return self._last_state.copy()

    def _poll_loop(self):
        """Poll system state at configured interval, emit changes."""
        while self._running:
            self._stop_event.wait(timeout=config.SYSTEM_MONITOR_INTERVAL_S)
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

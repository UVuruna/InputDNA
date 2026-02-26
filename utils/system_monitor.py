"""
System state monitor.

Periodically checks system settings that affect input behavior:
- Windows mouse speed (1-20)
- Mouse acceleration (enhance pointer precision)
- Screen resolution
- Keyboard layout (foreground window)

On recording start, captures initial state. Then polls at a configurable
interval, emitting SystemEventRecord only when a value changes.

Polling rate is estimated separately via PollingRateEstimator, which now uses
Windows Raw Input (WM_INPUT) + QueryPerformanceCounter instead of the previous
WH_MOUSE_LL (pynput) approach. Raw Input posts WM_INPUT directly to a dedicated
message pump thread without cross-process hook delivery overhead, giving accurate
QPC timestamps. This eliminates the false 3ms/4ms/5ms median readings that
occurred when the hook thread was preempted at 500 Hz.
"""

import ctypes
import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

import config
from models.sessions import SystemEventRecord
from utils.timing import now_ns, wall_clock_iso
from utils.raw_input import RawInputMouseReader, RawMouseEvent

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

    Receives timestamps from a RawInputMouseReader (WM_INPUT + QPC), not from
    WH_MOUSE_LL, so delivery jitter is sub-millisecond rather than several ms.

    Maintains a rolling window of recent inter-event intervals. Intervals
    outside the physically plausible range are discarded before entering
    the window:
      - Below POLLING_RATE_MIN_INTERVAL_NS: burst artifacts (rapid-succession
        events when the message pump catches up after a brief preemption).
      - Above POLLING_RATE_MAX_INTERVAL_NS: idle gaps where the cursor was
        not moving (not representative of the hardware poll rate).

    After the window fills, calculates using the median of stored intervals
    and snaps to the nearest standard rate. Each calculation also logs a full
    quality report (P10/P50/P90 and % clean) so anomalies are visible in logs.

    Recalculates periodically (POLLING_RATE_UPDATE_INTERVAL_S cooldown) so a
    changed USB report rate or a bad initial estimate is eventually corrected.

    Thread-safe under CPython GIL: reader thread writes, Qt thread reads
    estimated_hz.
    """

    def __init__(self, sample_count: int = config.POLLING_RATE_SAMPLE_COUNT):
        self._sample_count        = sample_count
        self._intervals_ns: deque[int] = deque(maxlen=sample_count)
        self._last_t_ns: Optional[int] = None
        self._estimated_hz: Optional[int] = None
        self._last_calculated_ns: int = 0  # 0 = never calculated

    def add_move_timestamp(self, t_ns: int) -> Optional[int]:
        """
        Feed a mouse move event timestamp.

        Returns the new snapped Hz if the estimate changed, else None.
        """
        if self._last_t_ns is not None:
            interval = t_ns - self._last_t_ns
            if config.POLLING_RATE_MIN_INTERVAL_NS <= interval <= config.POLLING_RATE_MAX_INTERVAL_NS:
                self._intervals_ns.append(interval)

        self._last_t_ns = t_ns

        if len(self._intervals_ns) < self._sample_count:
            return None  # Window not full yet

        # First estimate: calculate immediately when window fills.
        # Subsequent estimates: respect cooldown to avoid excess CPU.
        cooldown_ns = int(config.POLLING_RATE_UPDATE_INTERVAL_S * 1_000_000_000)
        if self._last_calculated_ns == 0 or (t_ns - self._last_calculated_ns) >= cooldown_ns:
            return self._calculate(t_ns)

        return None

    def _calculate(self, now: int) -> Optional[int]:
        """
        Calculate polling rate from the rolling window using median.

        Logs a full quality report with P10/P50/P90 and percentage of clean
        intervals so timing anomalies are immediately visible in logs.

        Returns new snapped Hz if the value changed, else None.
        """
        self._last_calculated_ns = now
        intervals = list(self._intervals_ns)
        n = len(intervals)
        if not intervals:
            return None

        sorted_iv   = sorted(intervals)
        p10_ns      = sorted_iv[n // 10]
        p50_ns      = sorted_iv[n // 2]        # median
        p90_ns      = sorted_iv[int(n * 0.9)]

        if p50_ns <= 0:
            return None

        raw_hz  = round(1_000_000_000 / p50_ns)
        snapped = config.snap_polling_rate(raw_hz)

        # "Clean" = within 1.5× the median interval (e.g. <3ms for a 500Hz mouse)
        threshold_ns = int(p50_ns * 1.5)
        anomalous    = sum(1 for iv in intervals if iv > threshold_ns)
        pct_clean    = 100.0 * (n - anomalous) / n

        logger.info(
            f"Mouse polling rate: raw={raw_hz} Hz → snapped={snapped} Hz | "
            f"P10={p10_ns/1e6:.3f}ms P50={p50_ns/1e6:.3f}ms P90={p90_ns/1e6:.3f}ms | "
            f"{n} samples, {pct_clean:.1f}% clean"
        )

        if pct_clean < 95.0:
            logger.warning(
                f"Mouse polling rate: {100.0 - pct_clean:.1f}% of intervals "
                f"exceed {threshold_ns/1e6:.1f}ms — timestamp jitter detected"
            )

        if snapped != self._estimated_hz:
            self._estimated_hz = snapped
            return snapped

        return None

    @property
    def estimated_hz(self) -> Optional[int]:
        return self._estimated_hz


def start_polling_estimation(on_done: Optional[Callable[[int], None]] = None) -> Callable[[], None]:
    """
    Start a continuous background listener to estimate mouse polling rate.

    Uses Windows Raw Input (WM_INPUT) + QueryPerformanceCounter via
    RawInputMouseReader. This replaces the previous pynput (WH_MOUSE_LL)
    approach which caused false 3–5ms median readings due to cross-process
    hook delivery jitter at 500 Hz.

    Runs until the returned stop() callable is called (e.g. on logout).
    Calls on_done(hz) on the reader thread each time the estimate changes.
    Also updates config.ESTIMATED_POLLING_HZ on each change.

    Returns a stop() callable. Store it and call it on logout.
    """
    estimator     = PollingRateEstimator()
    _last_reported: dict = {"hz": None}
    holder: dict  = {"reader": None}

    def _on_event(ev: RawMouseEvent):
        if ev.rel_x == 0 and ev.rel_y == 0:
            return  # button-only event, no movement — skip
        new_hz = estimator.add_move_timestamp(ev.t_ns)
        if new_hz is not None and new_hz != _last_reported["hz"]:
            _last_reported["hz"] = new_hz
            config.ESTIMATED_POLLING_HZ = new_hz
            if on_done is not None:
                on_done(new_hz)

    def stop():
        reader = holder.get("reader")
        if reader is not None:
            reader.stop()
            holder["reader"] = None
            logger.info("Polling rate estimation stopped")

    reader = RawInputMouseReader(callback=_on_event)
    reader.start()
    holder["reader"] = reader
    logger.info("Polling rate estimation started (Raw Input background listener)")
    return stop


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

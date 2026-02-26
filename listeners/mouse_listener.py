"""
Mouse event listener.

Hooks into OS-level mouse events via Windows Raw Input API (WM_INPUT) and
pushes raw events to a shared queue. Runs in a dedicated message pump thread.

Uses Raw Input instead of WH_MOUSE_LL (pynput) because:
  - WH_MOUSE_LL delivers events via cross-process synchronous SendMessage with
    variable scheduling jitter at 500 Hz (multiple ms, measured in logs).
  - WM_INPUT is posted directly to a dedicated message pump with lower and
    more consistent delivery latency.
  - WM_MOUSEMOVE in the message queue can be coalesced by Windows; WM_INPUT
    is never coalesced — every hardware report arrives as a distinct message.

Timestamps are captured via time.perf_counter_ns() as the FIRST operation in
the WM_INPUT handler — before GetCursorPos(), before queue.put() — giving
sub-millisecond accuracy that reflects actual event arrival time.

Timing quality is logged every TIMING_QUALITY_LOG_INTERVAL_S seconds so
anomalies are visible in logs without reading the full database.

Captures: move, click (press/release), scroll (vertical and horizontal).
All timestamps: perf_counter_ns (sub-microsecond, monotonic).
"""

import queue
import logging
import time
from typing import Callable

import config
from models.events import RawMouseMove, RawMouseClick, RawMouseScroll
from utils.raw_input import (
    RawInputMouseReader, RawMouseEvent,
    BUTTON_LEFT_DOWN, BUTTON_LEFT_UP,
    BUTTON_RIGHT_DOWN, BUTTON_RIGHT_UP,
    BUTTON_MIDDLE_DOWN, BUTTON_MIDDLE_UP,
    BUTTON_WHEEL, BUTTON_HWHEEL, WHEEL_DELTA,
)

logger = logging.getLogger(__name__)


class MouseListener:
    """
    Captures mouse events and pushes them to a shared queue.

    Usage:
        q = queue.Queue()
        ml = MouseListener(q)
        ml.start()
        ...
        ml.stop()
    """

    def __init__(
        self,
        event_queue: queue.Queue,
        poll_feed: Callable[[int], None] | None = None,
    ):
        self._queue     = event_queue
        self._poll_feed = poll_feed
        self._reader: RawInputMouseReader | None = None

        # Timing quality tracking — lightweight, for periodic log reports
        self._quality_intervals: list[int] = []   # recent inter-move intervals (ns)
        self._last_move_t_ns: int | None   = None
        self._last_quality_log_t            = time.monotonic()

    def start(self):
        """Start listening for mouse events in a background thread."""
        self._reader = RawInputMouseReader(callback=self._on_event)
        self._reader.start()
        logger.info("Mouse listener started")

    def stop(self):
        """Stop listening."""
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
            logger.info("Mouse listener stopped")

    # ── Event handler ─────────────────────────────────────────────────────────

    def _on_event(self, ev: RawMouseEvent):
        x, y, t = ev.cursor_x, ev.cursor_y, ev.t_ns

        # Feed every WM_INPUT timestamp to the polling rate estimator.
        # The estimator needs hardware poll intervals (2ms at 500Hz), not just
        # position-change intervals. During slow movement, the cursor position
        # changes every 2-4 polls (4-8ms at 500Hz), so feeding only
        # position-change events produces false low estimates (250→125 Hz).
        # Zero-delta reports (rel_x=rel_y=0 but still a valid 500Hz poll)
        # preserve the true 2ms spacing.
        if self._poll_feed is not None:
            self._poll_feed(t)

        # Move — emit when there is actual cursor displacement
        if ev.rel_x != 0 or ev.rel_y != 0:
            self._queue.put(RawMouseMove(x=x, y=y, t_ns=t))
            self._track_quality(t)

        # Button / scroll events
        flags = ev.button_flags
        if flags:
            if flags & BUTTON_LEFT_DOWN:
                self._queue.put(RawMouseClick(x=x, y=y, button="left",   pressed=True,  t_ns=t))
            if flags & BUTTON_LEFT_UP:
                self._queue.put(RawMouseClick(x=x, y=y, button="left",   pressed=False, t_ns=t))
            if flags & BUTTON_RIGHT_DOWN:
                self._queue.put(RawMouseClick(x=x, y=y, button="right",  pressed=True,  t_ns=t))
            if flags & BUTTON_RIGHT_UP:
                self._queue.put(RawMouseClick(x=x, y=y, button="right",  pressed=False, t_ns=t))
            if flags & BUTTON_MIDDLE_DOWN:
                self._queue.put(RawMouseClick(x=x, y=y, button="middle", pressed=True,  t_ns=t))
            if flags & BUTTON_MIDDLE_UP:
                self._queue.put(RawMouseClick(x=x, y=y, button="middle", pressed=False, t_ns=t))
            if flags & BUTTON_WHEEL:
                notches = _wheel_notches(ev.button_data)
                if notches:
                    self._queue.put(RawMouseScroll(x=x, y=y, dx=0,      dy=notches, t_ns=t))
            if flags & BUTTON_HWHEEL:
                notches = _wheel_notches(ev.button_data)
                if notches:
                    self._queue.put(RawMouseScroll(x=x, y=y, dx=notches, dy=0,      t_ns=t))

    # ── Timing quality tracking ───────────────────────────────────────────────

    def _track_quality(self, t_ns: int):
        """Track inter-move interval for periodic quality reporting."""
        if self._last_move_t_ns is not None:
            interval = t_ns - self._last_move_t_ns
            # Use Hz-aware tight max when polling rate is known (3× expected,
            # e.g. 6ms for 500Hz). This filters inter-burst gaps (5-15ms) that
            # would corrupt P50 when using the wide estimator bound (20ms).
            hz = config.ESTIMATED_POLLING_HZ
            max_ns = (1_000_000_000 // hz) * 3 if hz else config.POLLING_RATE_MAX_INTERVAL_NS
            if config.POLLING_RATE_MIN_INTERVAL_NS <= interval <= max_ns:
                self._quality_intervals.append(interval)
        self._last_move_t_ns = t_ns

        now = time.monotonic()
        if now - self._last_quality_log_t >= config.TIMING_QUALITY_LOG_INTERVAL_S:
            self._log_quality()
            self._last_quality_log_t = now

    def _log_quality(self):
        """Log interval distribution statistics to help detect timestamp jitter."""
        intervals = self._quality_intervals
        self._quality_intervals = []

        n = len(intervals)
        if n < 10:
            logger.info(f"Mouse timing quality: not enough data ({n} intervals)")
            return

        sorted_iv = sorted(intervals)
        p10 = sorted_iv[n // 10]
        p50 = sorted_iv[n // 2]
        p90 = sorted_iv[int(n * 0.9)]
        iv_max = sorted_iv[-1]

        # Anomaly threshold: 1.5× expected interval when Hz is known.
        # P50-based threshold fails when inter-burst gaps inflate the median.
        hz = config.ESTIMATED_POLLING_HZ
        if hz:
            expected_ns = 1_000_000_000 // hz
            threshold = int(expected_ns * 1.5)
            hz_label = f"@{hz}Hz"
        else:
            threshold = int(p50 * 1.5)
            hz_label = "(Hz unknown)"

        anomalous = sum(1 for iv in intervals if iv > threshold)
        pct_clean = 100.0 * (n - anomalous) / n

        logger.info(
            f"Mouse timing quality {hz_label}: "
            f"P10={p10/1e6:.3f}ms P50={p50/1e6:.3f}ms P90={p90/1e6:.3f}ms "
            f"max={iv_max/1e6:.3f}ms | "
            f"{n} intervals, {pct_clean:.1f}% clean "
            f"(>{threshold/1e6:.1f}ms = anomalous)"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wheel_notches(button_data: int) -> int:
    """Convert raw usButtonData (unsigned short) to signed notch count."""
    # usButtonData is c_ushort (0-65535). Sign-extend: >32767 means negative.
    delta = button_data if button_data < 32768 else button_data - 65536
    return delta // WHEEL_DELTA

"""
Stats tracker — total and time-windowed counters for dashboard display.

Two classes:
  TimeWindowCounter — per-minute circular buffer for rolling window queries
  StatsTracker — manages named counters (total + windowed) in one place

All data is in-memory only. No database reads. Thread-safe under CPython
GIL for single-writer (processor thread) + single-reader (Qt timer thread).
"""

import time


class TimeWindowCounter:
    """
    Tracks a count in per-minute buckets using a circular buffer.

    Supports rolling window queries: "how many events in the last N minutes?"
    Fixed memory: 60 int slots regardless of event volume.
    """

    _MAX_MINUTES = 60

    def __init__(self):
        self._buckets: list[int] = [0] * self._MAX_MINUTES
        self._current_minute: int = 0
        self._start_time: float = time.monotonic()

    def _elapsed_minutes(self) -> int:
        return int((time.monotonic() - self._start_time) / 60)

    def _advance(self):
        """Clear any buckets that were skipped since last update."""
        new_minute = self._elapsed_minutes()
        if new_minute > self._current_minute:
            steps = min(new_minute - self._current_minute, self._MAX_MINUTES)
            for i in range(1, steps + 1):
                idx = (self._current_minute + i) % self._MAX_MINUTES
                self._buckets[idx] = 0
            self._current_minute = new_minute

    def increment(self, amount: int = 1):
        """Add to the current minute's bucket."""
        self._advance()
        self._buckets[self._current_minute % self._MAX_MINUTES] += amount

    def get_total(self, minutes: int) -> int:
        """Sum the last N minutes (including current partial minute)."""
        self._advance()
        minutes = min(minutes, self._MAX_MINUTES)
        current_idx = self._current_minute % self._MAX_MINUTES
        total = 0
        for i in range(minutes):
            total += self._buckets[(current_idx - i) % self._MAX_MINUTES]
        return total


class StatsTracker:
    """
    Named counters with both lifetime totals and per-minute windowed counts.

    Usage:
        tracker = StatsTracker(["clicks", "drags", "scrolls"])
        tracker.increment("clicks")
        tracker.increment("drags", 3)

        totals = tracker.get_totals()       # {"clicks": 1, "drags": 3, "scrolls": 0}
        windowed = tracker.get_windowed(30)  # last 30 min
    """

    def __init__(self, counter_names: list[str]):
        self._totals: dict[str, int] = {name: 0 for name in counter_names}
        self._windows: dict[str, TimeWindowCounter] = {
            name: TimeWindowCounter() for name in counter_names
        }

    def increment(self, name: str, amount: int = 1):
        """Increment a named counter (both total and windowed)."""
        self._totals[name] += amount
        self._windows[name].increment(amount)

    def total(self, name: str) -> int:
        """Get the lifetime total for a single counter."""
        return self._totals.get(name, 0)

    def get_totals(self) -> dict[str, int]:
        """Get all lifetime totals as a dict."""
        return self._totals.copy()

    def get_windowed(self, minutes: int) -> dict[str, int]:
        """Get all windowed totals for the last N minutes."""
        return {
            name: wc.get_total(minutes)
            for name, wc in self._windows.items()
        }

"""
Timestamp utilities.

All timing in the recorder goes through these functions.
We use perf_counter_ns exclusively for event timestamps because:
  - Monotonic (never goes backward, unlike time.time with NTP adjustments)
  - Sub-microsecond precision (~100ns on Windows)
  - Integer nanoseconds (no float precision loss)

Wall clock (datetime) is only used for human-readable fields in the DB.
"""

import time
from datetime import datetime


def now_ns() -> int:
    """Current timestamp in nanoseconds (monotonic, high-precision)."""
    return time.perf_counter_ns()


def ns_to_ms(ns: int) -> float:
    """Convert nanoseconds to milliseconds."""
    return ns / 1_000_000


def interval_ms(t1_ns: int, t2_ns: int) -> float:
    """Milliseconds between two perf_counter_ns timestamps."""
    return (t2_ns - t1_ns) / 1_000_000


def wall_clock_iso() -> str:
    """Current wall clock time as ISO 8601 string."""
    return datetime.now().isoformat()

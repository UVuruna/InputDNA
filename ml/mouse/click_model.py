"""
Mouse click behavior model.

Learns the user's click characteristics across all button types:
- Press duration per button (how long they hold the mouse button)
- Pre-click pause (delay between arriving at target and clicking)
- Multi-click timing (double/triple/spam click rhythm)
- Per-click press duration within sequences (1st vs 2nd vs 3rd click)
- Spam acceleration (clicks get faster through a sequence)

Key findings from data analysis:
- Right click is very consistent (std 27ms) vs left (std 163ms)
- Second click in double-click is slightly longer than first
- Spam clicking accelerates: first gap ~176ms, stabilizes at ~157ms
- Pre-click pause median is 65ms (user's reaction time before clicking)
"""

import logging
import pickle
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Maximum press duration for a normal click (ms).
# Longer holds are likely drags or held-down buttons, not clicks.
_MAX_CLICK_DURATION_MS = 1000.0

# Maximum pre-click pause to consider (ms).
# Longer pauses indicate the user was thinking, not aiming.
_MAX_PRE_CLICK_PAUSE_MS = 2000.0

# Maximum number of spam click positions to track independently
_MAX_SPAM_POSITIONS = 10

# Minimum samples for a button to get its own stats
_MIN_BUTTON_SAMPLES = 5


@dataclass
class ButtonStats:
    """Press duration statistics for one mouse button."""
    mean_ms: float
    std_ms: float
    median_ms: float
    count: int


class ClickModel:
    """
    Mouse click behavior model.

    Captures per-button press duration, pre-click pause timing,
    and multi-click rhythm with acceleration pattern.
    """

    def __init__(self):
        # Per-button single-click press duration
        self._button_stats: dict[str, ButtonStats] = {}
        self._global_press_mean_ms: float = 90.0
        self._global_press_std_ms: float = 30.0

        # Pre-click pause (time from movement end to click start)
        self._pre_click_mean_ms: float = 65.0
        self._pre_click_std_ms: float = 100.0
        self._pre_click_percentiles: np.ndarray | None = None  # P10-P90

        # Multi-click inter-click interval
        # Position in sequence → (mean_ms, std_ms)
        # Position 0 = gap between 1st and 2nd click, etc.
        self._multiclick_intervals: dict[int, tuple[float, float]] = {}
        self._global_interval_mean_ms: float = 165.0
        self._global_interval_std_ms: float = 50.0

        # Per-position press duration in multi-click sequences
        # Position 0 = 1st click, 1 = 2nd click, etc.
        self._multiclick_press: dict[int, tuple[float, float]] = {}

        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, mouse_db_path: Path) -> dict:
        """
        Train click model directly from mouse.db.

        Reads click_sequences, click_details, and movements tables.
        """
        logger.info("Training click model...")

        conn = sqlite3.connect(str(mouse_db_path))
        conn.row_factory = sqlite3.Row

        # ── Single click press duration per button ────────────
        cursor = conn.execute(
            "SELECT cs.button, cd.press_duration_ms "
            "FROM click_sequences cs "
            "JOIN click_details cd ON cs.id = cd.sequence_id "
            "WHERE cd.seq = 0 "
            "AND (SELECT COUNT(*) FROM click_details cd2 "
            "     WHERE cd2.sequence_id = cs.id) = 1"
        )

        by_button: dict[str, list[float]] = {}
        for row in cursor:
            dur = row["press_duration_ms"]
            if 0 < dur < _MAX_CLICK_DURATION_MS:
                by_button.setdefault(row["button"], []).append(dur)

        for button, durations in by_button.items():
            if len(durations) < _MIN_BUTTON_SAMPLES:
                continue
            arr = np.array(durations)
            # Trim outliers
            q5, q95 = np.percentile(arr, [5, 95])
            trimmed = arr[(arr >= q5) & (arr <= q95)]
            if len(trimmed) >= _MIN_BUTTON_SAMPLES:
                self._button_stats[button] = ButtonStats(
                    mean_ms=float(np.mean(trimmed)),
                    std_ms=max(float(np.std(trimmed)), 5.0),
                    median_ms=float(np.median(trimmed)),
                    count=len(trimmed),
                )

        # Global fallback
        all_single = []
        for durations in by_button.values():
            all_single.extend(durations)
        if all_single:
            arr = np.array(all_single)
            self._global_press_mean_ms = float(np.median(arr))
            self._global_press_std_ms = max(float(np.std(arr)), 10.0)

        logger.info(
            f"  Button stats: {', '.join(f'{b}={s.median_ms:.0f}ms(n={s.count})' for b, s in self._button_stats.items())}"
        )

        # ── Pre-click pause ───────────────────────────────────
        cursor = conn.execute(
            "SELECT cd.t_ns - m.end_t_ns as pause_ns "
            "FROM click_sequences cs "
            "JOIN click_details cd ON cs.id = cd.sequence_id AND cd.seq = 0 "
            "JOIN movements m ON cs.movement_id = m.id "
            "WHERE cs.movement_id IS NOT NULL"
        )

        pauses = []
        for row in cursor:
            pause_ms = row["pause_ns"] / 1_000_000
            if 0 < pause_ms < _MAX_PRE_CLICK_PAUSE_MS:
                pauses.append(pause_ms)

        if pauses:
            arr = np.array(pauses)
            self._pre_click_mean_ms = float(np.mean(arr))
            self._pre_click_std_ms = max(float(np.std(arr)), 10.0)
            self._pre_click_percentiles = np.percentile(
                arr, [10, 25, 50, 75, 90]
            )
            logger.info(
                f"  Pre-click pause: median={self._pre_click_percentiles[2]:.0f}ms "
                f"(n={len(pauses)}, P10={self._pre_click_percentiles[0]:.0f}, "
                f"P90={self._pre_click_percentiles[4]:.0f})"
            )

        # ── Multi-click intervals by position ─────────────────
        cursor = conn.execute(
            "SELECT cd1.seq, cd2.t_ns - cd1.t_ns as gap_ns, "
            "       cd1.press_duration_ms as press1, cd2.press_duration_ms as press2 "
            "FROM click_details cd1 "
            "JOIN click_details cd2 "
            "  ON cd1.sequence_id = cd2.sequence_id AND cd2.seq = cd1.seq + 1 "
            "JOIN click_sequences cs ON cs.id = cd1.sequence_id "
            "WHERE cs.button = 'left'"
        )

        intervals_by_pos: dict[int, list[float]] = {}
        press_by_pos: dict[int, list[float]] = {}

        for row in cursor:
            pos = row["seq"]  # 0 = gap between 1st and 2nd click
            gap_ms = row["gap_ns"] / 1_000_000

            if 0 < gap_ms < _MAX_CLICK_DURATION_MS:
                if pos <= _MAX_SPAM_POSITIONS:
                    intervals_by_pos.setdefault(pos, []).append(gap_ms)

            # Press duration of the second click at each position
            press2 = row["press2"]
            if 0 < press2 < _MAX_CLICK_DURATION_MS:
                press_by_pos.setdefault(pos + 1, []).append(press2)

        # Also collect first-click press durations from multi-click sequences
        cursor = conn.execute(
            "SELECT cd.press_duration_ms "
            "FROM click_details cd "
            "JOIN click_sequences cs ON cs.id = cd.sequence_id "
            "WHERE cd.seq = 0 AND cs.button = 'left' "
            "AND (SELECT COUNT(*) FROM click_details cd2 "
            "     WHERE cd2.sequence_id = cs.id) >= 2"
        )
        first_presses = [
            row["press_duration_ms"] for row in cursor
            if 0 < row["press_duration_ms"] < _MAX_CLICK_DURATION_MS
        ]
        if first_presses:
            press_by_pos.setdefault(0, []).extend(first_presses)

        # Compute stats
        for pos, gaps in intervals_by_pos.items():
            if len(gaps) >= _MIN_BUTTON_SAMPLES:
                arr = np.array(gaps)
                self._multiclick_intervals[pos] = (
                    float(np.mean(arr)),
                    max(float(np.std(arr)), 5.0),
                )

        for pos, presses in press_by_pos.items():
            if len(presses) >= _MIN_BUTTON_SAMPLES:
                arr = np.array(presses)
                self._multiclick_press[pos] = (
                    float(np.mean(arr)),
                    max(float(np.std(arr)), 5.0),
                )

        # Global multi-click interval
        all_intervals = []
        for gaps in intervals_by_pos.values():
            all_intervals.extend(gaps)
        if all_intervals:
            arr = np.array(all_intervals)
            self._global_interval_mean_ms = float(np.median(arr))
            self._global_interval_std_ms = max(float(np.std(arr)), 10.0)

        if self._multiclick_intervals:
            positions = sorted(self._multiclick_intervals.keys())
            parts = [
                f"#{p+1}->{p+2}={self._multiclick_intervals[p][0]:.0f}ms"
                for p in positions[:6]
            ]
            logger.info(f"  Multi-click intervals: {', '.join(parts)}")

        if self._multiclick_press:
            positions = sorted(self._multiclick_press.keys())
            parts = [
                f"click#{p+1}={self._multiclick_press[p][0]:.0f}ms"
                for p in positions[:4]
            ]
            logger.info(f"  Multi-click press duration: {', '.join(parts)}")

        conn.close()
        self._trained = True

        return {
            "status": "trained",
            "buttons": {b: s.count for b, s in self._button_stats.items()},
            "pre_click_median_ms": float(self._pre_click_percentiles[2]) if self._pre_click_percentiles is not None else 0,
            "multiclick_positions": len(self._multiclick_intervals),
            "pre_click_samples": len(pauses) if pauses else 0,
        }

    def sample_press_duration(
        self, button: str = "left",
        rng: np.random.Generator | None = None,
    ) -> float:
        """
        Sample single-click press duration for a button.

        Args:
            button: "left", "right", "middle", "button4", "button5"

        Returns:
            Press duration in milliseconds.
        """
        if not self._trained:
            raise RuntimeError("Click model not trained")
        if rng is None:
            rng = np.random.default_rng()

        if button in self._button_stats:
            s = self._button_stats[button]
            dur = rng.normal(s.mean_ms, s.std_ms)
        else:
            dur = rng.normal(self._global_press_mean_ms, self._global_press_std_ms)

        return max(dur, 5.0)

    def sample_pre_click_pause(
        self, rng: np.random.Generator | None = None,
    ) -> float:
        """
        Sample the pause between arriving at target and clicking.

        Uses percentile-based sampling for more realistic distribution
        (the distribution is right-skewed, not Gaussian).

        Returns:
            Pre-click pause in milliseconds.
        """
        if not self._trained:
            raise RuntimeError("Click model not trained")
        if rng is None:
            rng = np.random.default_rng()

        if self._pre_click_percentiles is not None:
            # Sample from a skewed distribution using percentile interpolation
            # Pick a random percentile and interpolate
            p = rng.uniform(0, 1)
            # Map to percentile values: 0→P10, 0.25→P25, 0.5→P50, 0.75→P75, 1.0→P90
            pct_positions = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
            pause = float(np.interp(p, pct_positions, self._pre_click_percentiles))
            # Add small Gaussian noise
            pause += rng.normal(0, 5.0)
        else:
            pause = rng.normal(self._pre_click_mean_ms, self._pre_click_std_ms)

        return max(pause, 1.0)

    def sample_multiclick(
        self, click_count: int,
        rng: np.random.Generator | None = None,
    ) -> list[dict]:
        """
        Generate timing for a multi-click sequence (double, triple, spam).

        Args:
            click_count: Number of clicks (2=double, 3=triple, 4+=spam)

        Returns:
            List of dicts, one per click:
            [
                {"press_duration_ms": 88.4, "delay_before_ms": 0.0},    # 1st click
                {"press_duration_ms": 94.5, "delay_before_ms": 176.0},  # 2nd click
                ...
            ]
            delay_before_ms is the gap AFTER the previous click's release.
        """
        if not self._trained:
            raise RuntimeError("Click model not trained")
        if rng is None:
            rng = np.random.default_rng()

        clicks = []

        for i in range(click_count):
            # Press duration for this position in the sequence
            if i in self._multiclick_press:
                mean, std = self._multiclick_press[i]
            else:
                mean = self._global_press_mean_ms
                std = self._global_press_std_ms
            press_ms = max(rng.normal(mean, std), 10.0)

            # Delay before this click (0 for the first click)
            if i == 0:
                delay_ms = 0.0
            else:
                pos = i - 1  # interval position: 0 = gap between 1st and 2nd
                if pos in self._multiclick_intervals:
                    int_mean, int_std = self._multiclick_intervals[pos]
                else:
                    # Extrapolate: spam stabilizes at last known interval
                    last_known = max(self._multiclick_intervals.keys()) if self._multiclick_intervals else 0
                    if last_known in self._multiclick_intervals:
                        int_mean, int_std = self._multiclick_intervals[last_known]
                    else:
                        int_mean = self._global_interval_mean_ms
                        int_std = self._global_interval_std_ms
                delay_ms = max(rng.normal(int_mean, int_std), 20.0)

            clicks.append({
                "press_duration_ms": press_ms,
                "delay_before_ms": delay_ms,
            })

        return clicks

    def save(self, path: Path) -> None:
        """Save trained model to disk."""
        data = {
            "button_stats": {
                b: (s.mean_ms, s.std_ms, s.median_ms, s.count)
                for b, s in self._button_stats.items()
            },
            "global_press_mean_ms": self._global_press_mean_ms,
            "global_press_std_ms": self._global_press_std_ms,
            "pre_click_mean_ms": self._pre_click_mean_ms,
            "pre_click_std_ms": self._pre_click_std_ms,
            "pre_click_percentiles": self._pre_click_percentiles,
            "multiclick_intervals": self._multiclick_intervals,
            "global_interval_mean_ms": self._global_interval_mean_ms,
            "global_interval_std_ms": self._global_interval_std_ms,
            "multiclick_press": self._multiclick_press,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Click model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "ClickModel":
        """Load trained model from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._button_stats = {
            b: ButtonStats(mean_ms=v[0], std_ms=v[1], median_ms=v[2], count=v[3])
            for b, v in data["button_stats"].items()
        }
        model._global_press_mean_ms = data["global_press_mean_ms"]
        model._global_press_std_ms = data["global_press_std_ms"]
        model._pre_click_mean_ms = data["pre_click_mean_ms"]
        model._pre_click_std_ms = data["pre_click_std_ms"]
        model._pre_click_percentiles = data["pre_click_percentiles"]
        model._multiclick_intervals = data["multiclick_intervals"]
        model._global_interval_mean_ms = data["global_interval_mean_ms"]
        model._global_interval_std_ms = data["global_interval_std_ms"]
        model._multiclick_press = data["multiclick_press"]
        model._trained = True
        return model

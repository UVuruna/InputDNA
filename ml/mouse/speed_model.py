"""
Mouse speed profile model.

Learns the user's characteristic speed curve during mouse movements:
how they accelerate at the start, cruise in the middle, and decelerate
before reaching the target.

Uses the minimum jerk model from motor control theory as a baseline,
then fits user-specific parameters from recorded data.

The speed profile is represented as normalized position (0→1) mapped
to normalized speed (0→1), computed from real path point timing.
"""

import logging
import pickle
from pathlib import Path

import numpy as np
from scipy.interpolate import interp1d

from ml.preprocessing.mouse_data import MouseDataset

logger = logging.getLogger(__name__)

# Number of bins for the normalized speed profile
_PROFILE_BINS = 50

# Minimum movements to compute a reliable speed profile
_MIN_MOVEMENTS = 30

# Minimum path points per movement to compute speed
_MIN_POINTS = 10


class SpeedModel:
    """
    Statistical speed profile model.

    Stores the user's average speed curve as a function of
    normalized position along the path (0.0 = start, 1.0 = end).
    """

    def __init__(self):
        self._profile_mean: np.ndarray | None = None  # (BINS,) mean speed at each position
        self._profile_std: np.ndarray | None = None    # (BINS,) std at each position
        self._positions: np.ndarray | None = None      # (BINS,) bin centers
        self._avg_speed_px_per_ms: float = 0.0
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: MouseDataset) -> dict:
        """
        Train speed profile from recorded movements.

        Extracts the instantaneous speed at each point along each path,
        normalizes by position and speed, then computes the average profile.
        """
        logger.info("Training speed profile model...")

        all_profiles = []

        for movement in dataset.movements:
            if len(movement.path_x) < _MIN_POINTS:
                continue

            profile = self._extract_speed_profile(movement)
            if profile is not None:
                all_profiles.append(profile)

        if len(all_profiles) < _MIN_MOVEMENTS:
            logger.warning(
                f"Only {len(all_profiles)} valid speed profiles — "
                f"need at least {_MIN_MOVEMENTS}"
            )
            return {
                "status": "skipped",
                "reason": f"insufficient data ({len(all_profiles)} < {_MIN_MOVEMENTS})",
            }

        # Stack all profiles: each is (_PROFILE_BINS,) normalized speeds
        stacked = np.array(all_profiles)  # (N, BINS)

        self._positions = np.linspace(0, 1, _PROFILE_BINS)
        self._profile_mean = np.mean(stacked, axis=0)
        self._profile_std = np.std(stacked, axis=0)

        # Compute average movement speed for scaling
        speeds = []
        for m in dataset.movements:
            dur_ms = (m.end_t_ns - m.start_t_ns) / 1_000_000
            if dur_ms > 0:
                dx = m.end_x - m.start_x
                dy = m.end_y - m.start_y
                dist = np.sqrt(dx * dx + dy * dy)
                speeds.append(dist / dur_ms)
        self._avg_speed_px_per_ms = float(np.median(speeds)) if speeds else 1.0

        self._trained = True

        logger.info(
            f"  Speed profile trained from {len(all_profiles):,} movements\n"
            f"  Average speed: {self._avg_speed_px_per_ms:.2f} px/ms"
        )

        return {
            "status": "trained",
            "movements_used": len(all_profiles),
            "avg_speed_px_per_ms": self._avg_speed_px_per_ms,
        }

    def apply(
        self, path_x: np.ndarray, path_y: np.ndarray,
        total_duration_us: float,
        rng: np.random.Generator | None = None,
    ) -> np.ndarray:
        """
        Apply the speed profile to a generated path.

        Redistributes timing (dt_us) along the path according to the
        learned speed curve — slower at start/end, faster in the middle.

        Returns:
            dt_us array with realistic timing per segment.
        """
        if not self._trained:
            raise RuntimeError("Speed model not trained")

        if rng is None:
            rng = np.random.default_rng()

        n = len(path_x)
        if n < 2:
            return np.array([0], dtype=np.int64)

        # Compute cumulative arc length along the path
        dx = np.diff(path_x.astype(np.float64))
        dy = np.diff(path_y.astype(np.float64))
        segment_lengths = np.sqrt(dx * dx + dy * dy)
        cumulative = np.concatenate([[0], np.cumsum(segment_lengths)])
        total_length = cumulative[-1]

        if total_length < 1.0:
            dt = np.full(n, total_duration_us / max(n - 1, 1), dtype=np.int64)
            dt[0] = 0
            return dt

        # Normalized position along the path (0 to 1) for each point
        positions = cumulative / total_length

        # Sample speed profile at each point (with slight random variation)
        variation = 1.0 + rng.normal(0, 0.05, size=_PROFILE_BINS)
        varied_profile = self._profile_mean * np.clip(variation, 0.8, 1.2)

        # Interpolate speed at each path point's position
        speed_interp = interp1d(
            self._positions, varied_profile,
            kind="linear", fill_value="extrapolate",
        )
        speeds_at_points = speed_interp(positions)
        speeds_at_points = np.maximum(speeds_at_points, 0.01)  # Avoid division by zero

        # Speed → time: dt ∝ segment_length / speed
        # For each segment, time = length / speed_at_midpoint
        midpoint_speeds = (speeds_at_points[:-1] + speeds_at_points[1:]) / 2
        raw_dt = segment_lengths / midpoint_speeds

        # Normalize so total matches target duration
        raw_dt *= total_duration_us / raw_dt.sum()

        dt_us = np.empty(n, dtype=np.int64)
        dt_us[0] = 0
        dt_us[1:] = np.round(raw_dt).astype(np.int64)

        # Ensure no zero gaps (minimum 100µs between points)
        dt_us[1:] = np.maximum(dt_us[1:], 100)

        return dt_us

    def save(self, path: Path) -> None:
        data = {
            "profile_mean": self._profile_mean,
            "profile_std": self._profile_std,
            "positions": self._positions,
            "avg_speed": self._avg_speed_px_per_ms,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Speed model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "SpeedModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._profile_mean = data["profile_mean"]
        model._profile_std = data["profile_std"]
        model._positions = data["positions"]
        model._avg_speed_px_per_ms = data["avg_speed"]
        model._trained = True
        return model

    @staticmethod
    def _extract_speed_profile(movement) -> np.ndarray | None:
        """
        Extract normalized speed profile from a single movement.

        Returns (_PROFILE_BINS,) array of normalized speeds, or None.
        """
        px = movement.path_x.astype(np.float64)
        py = movement.path_y.astype(np.float64)
        t_ns = movement.path_t_ns.astype(np.float64)

        n = len(px)

        # Compute segment speeds (px/ns → px/ms for readability)
        dx = np.diff(px)
        dy = np.diff(py)
        dt_ns = np.diff(t_ns)

        # Filter zero-time segments
        valid = dt_ns > 0
        if valid.sum() < 5:
            return None

        segment_lengths = np.sqrt(dx[valid] ** 2 + dy[valid] ** 2)
        segment_speeds = segment_lengths / (dt_ns[valid] / 1_000_000)  # px/ms

        # Compute cumulative distance for position normalization
        cum_lengths = np.concatenate([[0], np.cumsum(segment_lengths)])
        total_length = cum_lengths[-1]
        if total_length < 1.0:
            return None

        # Normalized positions of segment midpoints
        midpoints = (cum_lengths[:-1] + cum_lengths[1:]) / (2 * total_length)

        # Normalize speeds (0 to 1)
        max_speed = segment_speeds.max()
        if max_speed < 0.001:
            return None
        norm_speeds = segment_speeds / max_speed

        # Resample to fixed number of bins
        try:
            interp = interp1d(
                midpoints, norm_speeds,
                kind="linear", bounds_error=False,
                fill_value=(norm_speeds[0], norm_speeds[-1]),
            )
            positions = np.linspace(0, 1, _PROFILE_BINS)
            profile = interp(positions)
            return profile
        except ValueError:
            return None

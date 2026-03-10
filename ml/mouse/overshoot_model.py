"""
Mouse overshoot predictor.

Detects whether the user tends to overshoot targets (move past them
and correct back), and models the overshoot characteristics:
- Probability of overshoot (depends on distance, speed, angle)
- Overshoot magnitude (how far past the target)
- Correction time (how long the correction takes)

Uses logistic regression for probability and statistical distributions
for magnitude/timing — simple, interpretable, works with limited data.
"""

import logging
import pickle
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from ml.preprocessing.mouse_data import MouseDataset, MovementData

logger = logging.getLogger(__name__)

# Minimum distance to endpoint before reversing to count as overshoot (px)
_OVERSHOOT_THRESHOLD_PX = 5

# Minimum movements to train the overshoot model
_MIN_MOVEMENTS = 100

# Minimum overshoots to train probability model
_MIN_OVERSHOOTS = 10


class OvershootModel:
    """
    Predicts overshoot probability and characteristics.

    Analyzes the end portion of each movement to detect if the user
    passed the target and corrected back.
    """

    def __init__(self):
        self._classifier: LogisticRegression | None = None
        self._overshoot_rate: float = 0.0
        # Overshoot magnitude distribution (px, as fraction of distance)
        self._magnitude_mean: float = 0.0
        self._magnitude_std: float = 0.0
        # Correction duration distribution (ms)
        self._correction_mean_ms: float = 0.0
        self._correction_std_ms: float = 0.0
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: MouseDataset) -> dict:
        """
        Train overshoot model by analyzing movement endpoints.

        Looks at movements that end with clicks (intentional targets)
        to detect overshoot patterns.
        """
        logger.info("Training overshoot model...")

        # Only analyze click-ending movements (these have definite targets)
        click_movements = [
            m for m in dataset.movements
            if m.movement_id in dataset.click_movement_ids
            and len(m.path_x) >= 10
        ]

        if len(click_movements) < _MIN_MOVEMENTS:
            logger.warning(
                f"Only {len(click_movements)} click-movements — "
                f"need {_MIN_MOVEMENTS} for overshoot model"
            )
            return {
                "status": "skipped",
                "reason": f"insufficient click-movements ({len(click_movements)})",
            }

        # Detect overshoots in each movement
        features = []
        labels = []
        magnitudes = []
        correction_times_ms = []

        for i, m in enumerate(click_movements):
            dist = np.sqrt(
                (m.end_x - m.start_x) ** 2 + (m.end_y - m.start_y) ** 2
            )
            if dist < 10:
                continue

            dur_ms = (m.end_t_ns - m.start_t_ns) / 1_000_000
            avg_speed = dist / dur_ms if dur_ms > 0 else 0

            overshoot_info = self._detect_overshoot(m)

            features.append([
                np.log1p(dist),
                avg_speed,
            ])
            labels.append(1 if overshoot_info else 0)

            if overshoot_info:
                mag_px, corr_ms = overshoot_info
                magnitudes.append(mag_px / dist)  # Normalize by distance
                correction_times_ms.append(corr_ms)

        if len(features) < _MIN_MOVEMENTS:
            return {"status": "skipped", "reason": "not enough analyzable movements"}

        features_arr = np.array(features)
        labels_arr = np.array(labels)

        n_overshoots = labels_arr.sum()
        self._overshoot_rate = n_overshoots / len(labels_arr)

        logger.info(
            f"  Overshoot rate: {self._overshoot_rate:.1%} "
            f"({n_overshoots}/{len(labels_arr)})"
        )

        if n_overshoots >= _MIN_OVERSHOOTS:
            # Train logistic regression for overshoot probability
            self._classifier = LogisticRegression(max_iter=1000)
            self._classifier.fit(features_arr, labels_arr)

            # Magnitude and correction time distributions
            mag_arr = np.array(magnitudes)
            corr_arr = np.array(correction_times_ms)
            self._magnitude_mean = float(np.mean(mag_arr))
            self._magnitude_std = float(np.std(mag_arr))
            self._correction_mean_ms = float(np.mean(corr_arr))
            self._correction_std_ms = float(np.std(corr_arr))
        else:
            logger.info("  Too few overshoots for classifier — using global rate only")
            self._classifier = None

        self._trained = True

        return {
            "status": "trained",
            "movements_analyzed": len(features),
            "overshoot_rate": self._overshoot_rate,
            "overshoots_detected": int(n_overshoots),
            "magnitude_mean_pct": self._magnitude_mean * 100,
            "correction_mean_ms": self._correction_mean_ms,
        }

    def should_overshoot(
        self, distance: float, speed: float,
        rng: np.random.Generator | None = None,
    ) -> bool:
        """Predict whether this movement should have an overshoot."""
        if not self._trained:
            return False

        if rng is None:
            rng = np.random.default_rng()

        if self._classifier is not None:
            features = np.array([[np.log1p(distance), speed]])
            prob = self._classifier.predict_proba(features)[0, 1]
        else:
            prob = self._overshoot_rate

        return bool(rng.random() < prob)

    def sample_overshoot(
        self, distance: float,
        rng: np.random.Generator | None = None,
    ) -> tuple[float, float]:
        """
        Sample overshoot magnitude and correction time.

        Returns:
            (overshoot_px, correction_ms)
        """
        if rng is None:
            rng = np.random.default_rng()

        # Sample magnitude (as fraction of distance)
        mag_frac = rng.normal(self._magnitude_mean, max(self._magnitude_std, 0.01))
        mag_frac = max(mag_frac, 0.02)  # At least 2% of distance
        overshoot_px = mag_frac * distance

        # Sample correction time
        corr_ms = rng.normal(self._correction_mean_ms, max(self._correction_std_ms, 5.0))
        corr_ms = max(corr_ms, 10.0)  # At least 10ms

        return overshoot_px, corr_ms

    def save(self, path: Path) -> None:
        data = {
            "classifier": self._classifier,
            "overshoot_rate": self._overshoot_rate,
            "magnitude_mean": self._magnitude_mean,
            "magnitude_std": self._magnitude_std,
            "correction_mean_ms": self._correction_mean_ms,
            "correction_std_ms": self._correction_std_ms,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Overshoot model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "OvershootModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._classifier = data["classifier"]
        model._overshoot_rate = data["overshoot_rate"]
        model._magnitude_mean = data["magnitude_mean"]
        model._magnitude_std = data["magnitude_std"]
        model._correction_mean_ms = data["correction_mean_ms"]
        model._correction_std_ms = data["correction_std_ms"]
        model._trained = True
        return model

    @staticmethod
    def _detect_overshoot(movement: MovementData) -> tuple[float, float] | None:
        """
        Detect overshoot in a movement's path.

        Looks at the last portion of the path. If the distance to the
        endpoint increases then decreases, that's an overshoot.

        Returns (overshoot_magnitude_px, correction_time_ms) or None.
        """
        px = movement.path_x.astype(np.float64)
        py = movement.path_y.astype(np.float64)
        t_ns = movement.path_t_ns

        end_x = float(movement.end_x)
        end_y = float(movement.end_y)

        # Distance from each point to the endpoint
        dist_to_end = np.sqrt((px - end_x) ** 2 + (py - end_y) ** 2)

        # Look at the last 30% of the path for overshoot
        start_idx = int(len(dist_to_end) * 0.7)
        tail = dist_to_end[start_idx:]

        if len(tail) < 3:
            return None

        # Find the minimum distance (closest approach to target)
        min_idx = np.argmin(tail)

        # If minimum is not at the end, check if there's a peak after it
        # (that would mean we passed the target and came back)
        if min_idx >= len(tail) - 2:
            # Minimum is at/near the end — no overshoot
            return None

        # Check if path goes PAST the target then comes back
        # Look for a peak between the first close approach and the final position
        after_min = tail[min_idx:]
        if len(after_min) < 2:
            return None

        peak_after = np.max(after_min)
        if peak_after < _OVERSHOOT_THRESHOLD_PX:
            return None

        # Overshoot detected
        overshoot_px = peak_after
        peak_idx_global = start_idx + min_idx + np.argmax(after_min)

        # Correction time: from peak to end of path
        if peak_idx_global < len(t_ns) - 1:
            correction_ns = t_ns[-1] - t_ns[peak_idx_global]
            correction_ms = correction_ns / 1_000_000
        else:
            correction_ms = 0.0

        return float(overshoot_px), float(correction_ms)

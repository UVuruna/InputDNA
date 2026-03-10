"""
Key hold duration model.

Learns how long the user holds each key before releasing.
Hold duration varies by key, typing speed, and context.

Simple statistical model: per-key Gaussian distribution.
"""

import logging
import pickle
from pathlib import Path

import numpy as np

from ml.preprocessing.keyboard_data import KeyboardDataset

logger = logging.getLogger(__name__)


class HoldModel:
    """
    Per-key hold duration model.

    Stores (mean, std) of press duration for each scan code.
    Falls back to global average for unseen keys.
    """

    def __init__(self):
        self._key_stats: dict[int, tuple[float, float]] = {}
        self._global_mean_ms: float = 80.0
        self._global_std_ms: float = 30.0
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: KeyboardDataset) -> dict:
        """Train hold duration model from keystroke data."""
        logger.info("Training key hold model...")

        total_keys = 0

        for scan, entry in dataset.key_holds.items():
            arr = entry.durations_ms
            # Trim outliers (remove top/bottom 5%)
            q5, q95 = np.percentile(arr, [5, 95])
            trimmed = arr[(arr >= q5) & (arr <= q95)]
            if len(trimmed) >= 3:
                self._key_stats[scan] = (
                    float(np.mean(trimmed)),
                    max(float(np.std(trimmed)), 3.0),
                )
                total_keys += 1

        # Global fallback
        all_means = [m for m, s in self._key_stats.values()]
        if all_means:
            self._global_mean_ms = float(np.median(all_means))
            self._global_std_ms = max(float(np.std(all_means)), 5.0)

        self._trained = True

        logger.info(
            f"  Hold model trained: {total_keys} unique keys\n"
            f"  Global median hold: {self._global_mean_ms:.1f}ms"
        )

        return {
            "status": "trained",
            "unique_keys": total_keys,
            "global_mean_ms": self._global_mean_ms,
        }

    def sample_duration(
        self, scan_code: int,
        rng: np.random.Generator | None = None,
    ) -> float:
        """Sample hold duration for a key (milliseconds)."""
        if not self._trained:
            raise RuntimeError("Hold model not trained")

        if rng is None:
            rng = np.random.default_rng()

        if scan_code in self._key_stats:
            mean, std = self._key_stats[scan_code]
        else:
            mean, std = self._global_mean_ms, self._global_std_ms

        duration = rng.normal(mean, std)
        return max(duration, 10.0)

    def save(self, path: Path) -> None:
        data = {
            "key_stats": self._key_stats,
            "global_mean_ms": self._global_mean_ms,
            "global_std_ms": self._global_std_ms,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Hold model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "HoldModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._key_stats = data["key_stats"]
        model._global_mean_ms = data["global_mean_ms"]
        model._global_std_ms = data["global_std_ms"]
        model._trained = True
        return model

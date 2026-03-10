"""
Text typing digraph model.

Learns the user's inter-key timing for regular text typing.
Each scan-code pair (from_key → to_key) has its own timing
distribution, capturing the unique rhythm of this user's typing.

For unseen pairs (not enough data), falls back to a global
estimate adjusted by physical key distance.

This model handles typing_mode="text" and typing_mode="code".
"""

import logging
import pickle
from pathlib import Path

import numpy as np
from scipy.stats import norm

from ml.preprocessing.keyboard_data import KeyboardDataset, DigraphEntry

logger = logging.getLogger(__name__)

# Minimum observations for a pair to have its own distribution
_MIN_PAIR_OBSERVATIONS = 3

# Physical key distance approximation (scan code → row, col position)
# Used for fallback timing estimation on unseen pairs
_SCAN_TO_POSITION: dict[int, tuple[int, int]] = {
    # Number row (row 0)
    0x02: (0, 0), 0x03: (0, 1), 0x04: (0, 2), 0x05: (0, 3), 0x06: (0, 4),
    0x07: (0, 5), 0x08: (0, 6), 0x09: (0, 7), 0x0A: (0, 8), 0x0B: (0, 9),
    # Q row (row 1)
    0x10: (1, 0), 0x11: (1, 1), 0x12: (1, 2), 0x13: (1, 3), 0x14: (1, 4),
    0x15: (1, 5), 0x16: (1, 6), 0x17: (1, 7), 0x18: (1, 8), 0x19: (1, 9),
    # A row (row 2)
    0x1E: (2, 0), 0x1F: (2, 1), 0x20: (2, 2), 0x21: (2, 3), 0x22: (2, 4),
    0x23: (2, 5), 0x24: (2, 6), 0x25: (2, 7), 0x26: (2, 8),
    # Z row (row 3)
    0x2C: (3, 0), 0x2D: (3, 1), 0x2E: (3, 2), 0x2F: (3, 3), 0x30: (3, 4),
    0x31: (3, 5), 0x32: (3, 6),
    # Space (row 4)
    0x39: (4, 3),
}


class TextTypingModel:
    """
    Digraph timing model for text typing.

    Stores per-pair (from_scan, to_scan) timing distributions.
    At inference, samples from the learned distribution to produce
    realistic inter-key delays.
    """

    def __init__(self):
        # Per-pair statistics: (from_scan, to_scan) → (mean, std)
        self._pair_stats: dict[tuple[int, int], tuple[float, float]] = {}
        # Global fallback statistics
        self._global_mean_ms: float = 100.0
        self._global_std_ms: float = 50.0
        # Distance-adjusted fallback coefficients
        self._distance_coeff: float = 10.0  # ms per key-distance unit
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: KeyboardDataset) -> dict:
        """
        Train text typing model from digraph data.

        Combines text and code digraphs (same physical typing,
        just different character sets).
        """
        logger.info("Training text typing model...")

        # Merge text and code digraphs
        all_pairs: dict[tuple[int, int], list[float]] = {}

        for digraphs in [dataset.text_digraphs, dataset.code_digraphs]:
            for pair, entry in digraphs.items():
                if pair not in all_pairs:
                    all_pairs[pair] = []
                all_pairs[pair].extend(entry.delays_ms.tolist())

        # Compute per-pair statistics
        total_observations = 0
        for pair, delays in all_pairs.items():
            if len(delays) >= _MIN_PAIR_OBSERVATIONS:
                arr = np.array(delays)
                # Use trimmed statistics (remove outliers)
                q1, q3 = np.percentile(arr, [10, 90])
                trimmed = arr[(arr >= q1) & (arr <= q3)]
                if len(trimmed) >= _MIN_PAIR_OBSERVATIONS:
                    self._pair_stats[pair] = (
                        float(np.mean(trimmed)),
                        max(float(np.std(trimmed)), 5.0),  # Min 5ms std
                    )
                    total_observations += len(delays)

        # Compute global fallback from all data
        all_delays = []
        for delays in all_pairs.values():
            all_delays.extend(delays)

        if all_delays:
            all_arr = np.array(all_delays)
            self._global_mean_ms = float(np.median(all_arr))
            self._global_std_ms = max(float(np.std(all_arr)), 10.0)

        # Fit distance coefficient from known pairs
        self._fit_distance_coefficient()

        self._trained = True

        logger.info(
            f"  Text model trained: {len(self._pair_stats)} pairs, "
            f"{total_observations:,} observations\n"
            f"  Global median: {self._global_mean_ms:.1f}ms, "
            f"std: {self._global_std_ms:.1f}ms"
        )

        return {
            "status": "trained",
            "unique_pairs": len(self._pair_stats),
            "total_observations": total_observations,
            "global_mean_ms": self._global_mean_ms,
            "global_std_ms": self._global_std_ms,
        }

    def sample_delay(
        self, from_scan: int, to_scan: int,
        rng: np.random.Generator | None = None,
    ) -> float:
        """
        Sample an inter-key delay for the given scan code pair.

        Returns delay in milliseconds.
        """
        if not self._trained:
            raise RuntimeError("Text model not trained")

        if rng is None:
            rng = np.random.default_rng()

        pair = (from_scan, to_scan)

        if pair in self._pair_stats:
            mean, std = self._pair_stats[pair]
        else:
            # Fallback: adjust global mean by physical key distance
            mean, std = self._fallback_stats(from_scan, to_scan)

        # Sample from truncated normal (always positive)
        delay = rng.normal(mean, std)
        return max(delay, 10.0)  # Minimum 10ms

    def save(self, path: Path) -> None:
        data = {
            "pair_stats": self._pair_stats,
            "global_mean_ms": self._global_mean_ms,
            "global_std_ms": self._global_std_ms,
            "distance_coeff": self._distance_coeff,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Text model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "TextTypingModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._pair_stats = data["pair_stats"]
        model._global_mean_ms = data["global_mean_ms"]
        model._global_std_ms = data["global_std_ms"]
        model._distance_coeff = data["distance_coeff"]
        model._trained = True
        return model

    def _fallback_stats(
        self, from_scan: int, to_scan: int
    ) -> tuple[float, float]:
        """
        Estimate timing for an unseen pair based on physical key distance.
        """
        pos_from = _SCAN_TO_POSITION.get(from_scan)
        pos_to = _SCAN_TO_POSITION.get(to_scan)

        if pos_from and pos_to:
            # Euclidean distance in key units
            dist = np.sqrt(
                (pos_from[0] - pos_to[0]) ** 2 +
                (pos_from[1] - pos_to[1]) ** 2
            )
            adjusted_mean = self._global_mean_ms + self._distance_coeff * dist
        else:
            adjusted_mean = self._global_mean_ms * 1.2  # Unknown keys are slower

        return adjusted_mean, self._global_std_ms

    def _fit_distance_coefficient(self):
        """
        Fit the relationship between key distance and typing delay.

        Uses known pair statistics to estimate how much slower
        typing gets with physical key distance.
        """
        distances = []
        means = []

        for (from_scan, to_scan), (mean, _) in self._pair_stats.items():
            pos_from = _SCAN_TO_POSITION.get(from_scan)
            pos_to = _SCAN_TO_POSITION.get(to_scan)
            if pos_from and pos_to:
                dist = np.sqrt(
                    (pos_from[0] - pos_to[0]) ** 2 +
                    (pos_from[1] - pos_to[1]) ** 2
                )
                distances.append(dist)
                means.append(mean)

        if len(distances) >= 10:
            distances = np.array(distances)
            means = np.array(means)
            # Simple linear fit: mean ≈ global_mean + coeff * distance
            if distances.std() > 0:
                self._distance_coeff = float(
                    np.polyfit(distances, means, 1)[0]
                )
                self._distance_coeff = max(self._distance_coeff, 0)

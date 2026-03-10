"""
Number/numpad typing model.

Separate model for numpad typing — users have fundamentally
different patterns when typing numbers on the numpad vs regular text:
- Single hand (usually right)
- Compact key layout
- Often faster, more rhythmic
- Different finger movements

This model handles typing_mode="numpad" exclusively.
"""

import logging
import pickle
from pathlib import Path

import numpy as np

from ml.preprocessing.keyboard_data import KeyboardDataset

logger = logging.getLogger(__name__)

_MIN_PAIR_OBSERVATIONS = 3

# Numpad physical layout (scan code → row, col)
_NUMPAD_POSITION: dict[int, tuple[int, int]] = {
    0x45:   (0, 0),  # Num Lock
    0xE035: (0, 1),  # /
    0x37:   (0, 2),  # *
    0x4A:   (0, 3),  # -
    0x47:   (1, 0),  # 7
    0x48:   (1, 1),  # 8
    0x49:   (1, 2),  # 9
    0x4E:   (1, 3),  # +  (spans 2 rows visually, use top position)
    0x4B:   (2, 0),  # 4
    0x4C:   (2, 1),  # 5
    0x4D:   (2, 2),  # 6
    0x4F:   (3, 0),  # 1
    0x50:   (3, 1),  # 2
    0x51:   (3, 2),  # 3
    0xE01C: (3, 3),  # Numpad Enter
    0x52:   (4, 0),  # 0  (wide key, use left position)
    0x53:   (4, 2),  # .
}


class NumberTypingModel:
    """
    Digraph timing model for numpad/number typing.

    Same approach as TextTypingModel but trained exclusively on
    numpad transitions and using numpad-specific key positions.
    """

    def __init__(self):
        self._pair_stats: dict[tuple[int, int], tuple[float, float]] = {}
        self._global_mean_ms: float = 80.0  # Numpad is typically faster
        self._global_std_ms: float = 30.0
        self._distance_coeff: float = 8.0
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: KeyboardDataset) -> dict:
        """Train number typing model from numpad digraph data."""
        logger.info("Training number typing model...")

        if not dataset.numpad_digraphs:
            logger.info("  No numpad data available")
            return {"status": "skipped", "reason": "no numpad data"}

        total_observations = 0

        for pair, entry in dataset.numpad_digraphs.items():
            delays = entry.delays_ms
            if len(delays) >= _MIN_PAIR_OBSERVATIONS:
                arr = np.array(delays)
                q1, q3 = np.percentile(arr, [10, 90])
                trimmed = arr[(arr >= q1) & (arr <= q3)]
                if len(trimmed) >= _MIN_PAIR_OBSERVATIONS:
                    self._pair_stats[pair] = (
                        float(np.mean(trimmed)),
                        max(float(np.std(trimmed)), 3.0),
                    )
                    total_observations += len(delays)

        # Compute global stats from all numpad delays
        all_delays = []
        for entry in dataset.numpad_digraphs.values():
            all_delays.extend(entry.delays_ms.tolist())

        if all_delays:
            all_arr = np.array(all_delays)
            self._global_mean_ms = float(np.median(all_arr))
            self._global_std_ms = max(float(np.std(all_arr)), 5.0)

        self._fit_distance_coefficient()
        self._trained = True

        logger.info(
            f"  Number model trained: {len(self._pair_stats)} pairs, "
            f"{total_observations:,} observations\n"
            f"  Global median: {self._global_mean_ms:.1f}ms"
        )

        return {
            "status": "trained",
            "unique_pairs": len(self._pair_stats),
            "total_observations": total_observations,
            "global_mean_ms": self._global_mean_ms,
        }

    def sample_delay(
        self, from_scan: int, to_scan: int,
        rng: np.random.Generator | None = None,
    ) -> float:
        """Sample inter-key delay for numpad typing (milliseconds)."""
        if not self._trained:
            raise RuntimeError("Number model not trained")

        if rng is None:
            rng = np.random.default_rng()

        pair = (from_scan, to_scan)

        if pair in self._pair_stats:
            mean, std = self._pair_stats[pair]
        else:
            mean, std = self._fallback_stats(from_scan, to_scan)

        delay = rng.normal(mean, std)
        return max(delay, 5.0)

    def save(self, path: Path) -> None:
        data = {
            "pair_stats": self._pair_stats,
            "global_mean_ms": self._global_mean_ms,
            "global_std_ms": self._global_std_ms,
            "distance_coeff": self._distance_coeff,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Number model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "NumberTypingModel":
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
        """Estimate timing for unseen numpad pair based on key distance."""
        pos_from = _NUMPAD_POSITION.get(from_scan)
        pos_to = _NUMPAD_POSITION.get(to_scan)

        if pos_from and pos_to:
            dist = np.sqrt(
                (pos_from[0] - pos_to[0]) ** 2 +
                (pos_from[1] - pos_to[1]) ** 2
            )
            adjusted_mean = self._global_mean_ms + self._distance_coeff * dist
        else:
            adjusted_mean = self._global_mean_ms * 1.1

        return adjusted_mean, self._global_std_ms

    def _fit_distance_coefficient(self):
        """Fit distance→delay relationship for numpad keys."""
        distances = []
        means = []

        for (from_scan, to_scan), (mean, _) in self._pair_stats.items():
            pos_from = _NUMPAD_POSITION.get(from_scan)
            pos_to = _NUMPAD_POSITION.get(to_scan)
            if pos_from and pos_to:
                dist = np.sqrt(
                    (pos_from[0] - pos_to[0]) ** 2 +
                    (pos_from[1] - pos_to[1]) ** 2
                )
                distances.append(dist)
                means.append(mean)

        if len(distances) >= 5:
            distances = np.array(distances)
            means = np.array(means)
            if distances.std() > 0:
                self._distance_coeff = float(
                    np.polyfit(distances, means, 1)[0]
                )
                self._distance_coeff = max(self._distance_coeff, 0)

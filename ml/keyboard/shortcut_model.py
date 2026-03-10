"""
Keyboard shortcut timing model.

Learns the user's timing patterns for keyboard shortcuts:
- How quickly they press the main key after the modifier
- How long they hold the main key
- Whether they release the main key or modifier first
- Total shortcut duration

Template-based: each modifier+key combo has its own timing profile.
"""

import logging
import pickle
from pathlib import Path

import numpy as np

from ml.preprocessing.keyboard_data import KeyboardDataset

logger = logging.getLogger(__name__)


class ShortcutModel:
    """
    Per-shortcut timing profile model.

    Stores timing distributions for each modifier+key combination.
    Falls back to global averages for unseen shortcuts.
    """

    def __init__(self):
        # combo_key → (mod_to_main_mean, mod_to_main_std,
        #              main_hold_mean, main_hold_std,
        #              total_mean, total_std,
        #              main_first_probability)
        self._combo_stats: dict[str, dict] = {}
        self._global_mod_to_main_ms: float = 50.0
        self._global_main_hold_ms: float = 80.0
        self._global_total_ms: float = 200.0
        self._global_main_first_prob: float = 0.7
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: KeyboardDataset) -> dict:
        """Train shortcut timing model from recorded shortcuts."""
        logger.info("Training shortcut model...")

        if not dataset.shortcuts:
            logger.info("  No shortcut data available")
            return {"status": "skipped", "reason": "no shortcut data"}

        for combo_key, entry in dataset.shortcuts.items():
            mod_arr = entry.modifier_to_main_ms
            hold_arr = entry.main_hold_ms
            total_arr = entry.total_ms

            total_count = sum(entry.release_order_counts.values())
            main_first = entry.release_order_counts.get("main_first", 0)
            main_first_prob = main_first / total_count if total_count > 0 else 0.5

            self._combo_stats[combo_key] = {
                "mod_to_main_mean": float(np.mean(mod_arr)),
                "mod_to_main_std": max(float(np.std(mod_arr)), 5.0),
                "main_hold_mean": float(np.mean(hold_arr)),
                "main_hold_std": max(float(np.std(hold_arr)), 5.0),
                "total_mean": float(np.mean(total_arr)),
                "total_std": max(float(np.std(total_arr)), 10.0),
                "main_first_prob": main_first_prob,
                "count": entry.count,
            }

        # Global averages
        all_mod = []
        all_hold = []
        all_total = []
        all_mfp = []
        for stats in self._combo_stats.values():
            all_mod.append(stats["mod_to_main_mean"])
            all_hold.append(stats["main_hold_mean"])
            all_total.append(stats["total_mean"])
            all_mfp.append(stats["main_first_prob"])

        if all_mod:
            self._global_mod_to_main_ms = float(np.median(all_mod))
            self._global_main_hold_ms = float(np.median(all_hold))
            self._global_total_ms = float(np.median(all_total))
            self._global_main_first_prob = float(np.median(all_mfp))

        self._trained = True

        logger.info(
            f"  Shortcut model trained: {len(self._combo_stats)} combos\n"
            f"  Global mod→main: {self._global_mod_to_main_ms:.0f}ms, "
            f"hold: {self._global_main_hold_ms:.0f}ms"
        )

        return {
            "status": "trained",
            "unique_combos": len(self._combo_stats),
            "global_mod_to_main_ms": self._global_mod_to_main_ms,
            "global_main_hold_ms": self._global_main_hold_ms,
        }

    def sample_timing(
        self, combo_key: str,
        rng: np.random.Generator | None = None,
    ) -> dict:
        """
        Sample timing for a keyboard shortcut.

        Args:
            combo_key: "mod1,mod2+main_scan" format string

        Returns dict with:
            modifier_to_main_ms, main_hold_ms, total_ms, release_order
        """
        if not self._trained:
            raise RuntimeError("Shortcut model not trained")

        if rng is None:
            rng = np.random.default_rng()

        if combo_key in self._combo_stats:
            s = self._combo_stats[combo_key]
            mod_to_main = rng.normal(s["mod_to_main_mean"], s["mod_to_main_std"])
            main_hold = rng.normal(s["main_hold_mean"], s["main_hold_std"])
            total = rng.normal(s["total_mean"], s["total_std"])
            main_first_prob = s["main_first_prob"]
        else:
            mod_to_main = rng.normal(self._global_mod_to_main_ms, 15.0)
            main_hold = rng.normal(self._global_main_hold_ms, 20.0)
            total = rng.normal(self._global_total_ms, 30.0)
            main_first_prob = self._global_main_first_prob

        release_order = "main_first" if rng.random() < main_first_prob else "modifier_first"

        return {
            "modifier_to_main_ms": max(mod_to_main, 5.0),
            "main_hold_ms": max(main_hold, 10.0),
            "total_ms": max(total, 50.0),
            "release_order": release_order,
        }

    def save(self, path: Path) -> None:
        data = {
            "combo_stats": self._combo_stats,
            "global_mod_to_main_ms": self._global_mod_to_main_ms,
            "global_main_hold_ms": self._global_main_hold_ms,
            "global_total_ms": self._global_total_ms,
            "global_main_first_prob": self._global_main_first_prob,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Shortcut model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "ShortcutModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._combo_stats = data["combo_stats"]
        model._global_mod_to_main_ms = data["global_mod_to_main_ms"]
        model._global_main_hold_ms = data["global_main_hold_ms"]
        model._global_total_ms = data["global_total_ms"]
        model._global_main_first_prob = data["global_main_first_prob"]
        model._trained = True
        return model

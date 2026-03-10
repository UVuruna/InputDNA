"""
Mouse path generator — KNN-based with normalized path lookup.

Given start and end coordinates, generates a realistic mouse path
by finding similar recorded movements and adapting them.

Approach:
1. Normalize all recorded paths (translate to origin, scale to unit distance)
2. Store normalized paths indexed by (distance, angle) features
3. At inference: find K nearest movements, pick one weighted by similarity,
   denormalize to target start/end coordinates
4. Add variation by interpolating between similar paths

Why KNN over VAE for MVP:
- Works well with any amount of data (even 100 paths)
- Outputs are always realistic (they ARE real recorded paths)
- No training convergence issues
- VAE can be added later for infinite variation
"""

import logging
import pickle
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

from ml.preprocessing.mouse_data import MouseDataset, MovementData

logger = logging.getLogger(__name__)

# Number of neighbors to consider when generating a path
_K_NEIGHBORS = 10

# Maximum normalized path length to store (prevents memory bloat)
_MAX_NORMALIZED_POINTS = 500

# Minimum movements required to train
_MIN_MOVEMENTS = 50


class PathModel:
    """
    KNN-based mouse path generator.

    Stores normalized paths indexed by movement features.
    Generates new paths by finding similar recorded movements
    and denormalizing them to the target coordinates.
    """

    def __init__(self):
        self._tree: BallTree | None = None
        self._features: np.ndarray | None = None  # (N, 2) — distance, angle
        self._normalized_paths: list[np.ndarray] | None = None  # list of (M, 2) arrays
        self._durations_ms: np.ndarray | None = None
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: MouseDataset) -> dict:
        """
        Train the path model from recorded mouse movements.

        Returns dict with training metrics.
        """
        if dataset.total_movements < _MIN_MOVEMENTS:
            logger.warning(
                f"Only {dataset.total_movements} movements — "
                f"need at least {_MIN_MOVEMENTS} for path model"
            )
            return {
                "status": "skipped",
                "reason": f"insufficient data ({dataset.total_movements} < {_MIN_MOVEMENTS})",
            }

        logger.info(f"Training path model on {dataset.total_movements:,} movements...")

        # Normalize all paths
        normalized_paths = []
        valid_indices = []

        for i, movement in enumerate(dataset.movements):
            norm_path = self._normalize_path(movement)
            if norm_path is not None:
                normalized_paths.append(norm_path)
                valid_indices.append(i)

        if len(normalized_paths) < _MIN_MOVEMENTS:
            return {
                "status": "skipped",
                "reason": f"only {len(normalized_paths)} valid paths after normalization",
            }

        valid_indices = np.array(valid_indices)

        # Build feature matrix for KNN lookup
        # Features: (log_distance, angle) — log distance gives better scaling
        features = np.column_stack([
            np.log1p(dataset.distances[valid_indices]),
            dataset.angles[valid_indices],
        ])

        # Build BallTree for fast nearest-neighbor lookup
        self._tree = BallTree(features, metric="euclidean")
        self._features = features
        self._normalized_paths = normalized_paths
        self._durations_ms = dataset.durations_ms[valid_indices]
        self._trained = True

        logger.info(f"  Path model trained: {len(normalized_paths):,} paths indexed")

        return {
            "status": "trained",
            "paths_indexed": len(normalized_paths),
            "distance_range": (
                float(dataset.distances[valid_indices].min()),
                float(dataset.distances[valid_indices].max()),
            ),
        }

    def predict(
        self, start_x: int, start_y: int, end_x: int, end_y: int,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generate a mouse path from start to end.

        Returns:
            (path_x, path_y, dt_us) arrays — absolute coordinates + timing
        """
        if not self._trained:
            raise RuntimeError("Path model not trained")

        if rng is None:
            rng = np.random.default_rng()

        dx = end_x - start_x
        dy = end_y - start_y
        distance = np.sqrt(dx * dx + dy * dy)
        angle = np.arctan2(dy, dx)

        if distance < 1.0:
            # Target is at same position — return single point
            return (
                np.array([start_x], dtype=np.int32),
                np.array([start_y], dtype=np.int32),
                np.array([0], dtype=np.int64),
            )

        # Find K nearest recorded movements
        query = np.array([[np.log1p(distance), angle]])
        k = min(_K_NEIGHBORS, len(self._normalized_paths))
        dists, indices = self._tree.query(query, k=k)

        # Weight by inverse distance (closer = more likely to be selected)
        weights = 1.0 / (dists[0] + 1e-6)
        weights /= weights.sum()

        # Select a path weighted by similarity
        idx = rng.choice(indices[0], p=weights)
        norm_path = self._normalized_paths[idx]
        source_duration_ms = self._durations_ms[idx]

        # Denormalize: rotate and scale to target coordinates
        cos_a = dx / distance
        sin_a = dy / distance

        path_x_f = norm_path[:, 0] * distance
        path_y_f = norm_path[:, 1] * distance

        # Rotate to match target angle
        rotated_x = path_x_f * cos_a - path_y_f * sin_a + start_x
        rotated_y = path_x_f * sin_a + path_y_f * cos_a + start_y

        path_x = np.round(rotated_x).astype(np.int32)
        path_y = np.round(rotated_y).astype(np.int32)

        # Ensure exact start and end
        path_x[0] = start_x
        path_y[0] = start_y
        path_x[-1] = end_x
        path_y[-1] = end_y

        # Scale timing proportionally to distance ratio
        source_distance = np.exp(self._features[idx, 0]) - 1
        duration_ratio = distance / max(source_distance, 1.0)
        # Timing scales sub-linearly with distance (Fitts's law approximation)
        time_scale = np.sqrt(duration_ratio)
        total_duration_us = source_duration_ms * time_scale * 1000

        n_points = len(path_x)
        # Distribute time using the normalized path's implicit timing
        # (uniform for now — speed model adjusts this later)
        dt_us = np.full(n_points, total_duration_us / max(n_points - 1, 1), dtype=np.int64)
        dt_us[0] = 0

        return path_x, path_y, dt_us

    def save(self, path: Path) -> None:
        """Save trained model to disk."""
        data = {
            "tree": self._tree,
            "features": self._features,
            "normalized_paths": self._normalized_paths,
            "durations_ms": self._durations_ms,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Path model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "PathModel":
        """Load trained model from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._tree = data["tree"]
        model._features = data["features"]
        model._normalized_paths = data["normalized_paths"]
        model._durations_ms = data["durations_ms"]
        model._trained = True
        return model

    @staticmethod
    def _normalize_path(movement: MovementData) -> np.ndarray | None:
        """
        Normalize a path to unit distance along x-axis.

        Translates start to origin, scales so end is at (1, 0),
        and rotates so the movement goes along the x-axis.
        Returns (N, 2) array of normalized (x, y) points, or None if invalid.
        """
        dx = movement.end_x - movement.start_x
        dy = movement.end_y - movement.start_y
        distance = np.sqrt(dx * dx + dy * dy)

        if distance < 1.0:
            return None

        # Translate to origin
        px = movement.path_x.astype(np.float64) - movement.start_x
        py = movement.path_y.astype(np.float64) - movement.start_y

        # Rotate so movement direction aligns with x-axis
        angle = np.arctan2(dy, dx)
        cos_a = np.cos(-angle)
        sin_a = np.sin(-angle)
        rx = px * cos_a - py * sin_a
        ry = px * sin_a + py * cos_a

        # Scale to unit distance
        rx /= distance
        ry /= distance

        # Downsample if too many points
        n = len(rx)
        if n > _MAX_NORMALIZED_POINTS:
            indices = np.linspace(0, n - 1, _MAX_NORMALIZED_POINTS, dtype=int)
            rx = rx[indices]
            ry = ry[indices]

        return np.column_stack([rx, ry])

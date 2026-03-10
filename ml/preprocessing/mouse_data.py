"""
Extract and clean mouse data from SQLite for ML training.

Loads movements, path points, clicks, and scrolls from mouse.db.
Reconstructs full paths from delta-encoded path_points.
Computes features needed by mouse models (distance, angle, speed).
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Maximum movement duration to include (seconds).
# Longer movements are likely idle-triggered and not useful for path modeling.
_MAX_DURATION_S = 10.0

# Minimum path points for a movement to be useful for training.
_MIN_PATH_POINTS = 5


@dataclass
class MovementData:
    """A single mouse movement with reconstructed path."""
    movement_id: int
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    start_t_ns: int
    end_t_ns: int
    end_event: str
    # Reconstructed absolute path: arrays of (x, y, t_ns)
    path_x: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int32))
    path_y: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int32))
    path_t_ns: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))


@dataclass
class MouseDataset:
    """Complete mouse dataset ready for model training."""
    movements: list[MovementData]
    # Pre-computed feature arrays (aligned with movements list)
    distances: np.ndarray      # Euclidean distance start→end (px)
    angles: np.ndarray         # Angle of movement (radians, -π to π)
    durations_ms: np.ndarray   # Duration (milliseconds)
    # Click data for overshoot detection
    click_movement_ids: set[int]  # movement_ids that ended with a click
    # Summary stats
    total_movements: int
    total_path_points: int


def load_mouse_data(db_path: Path, progress_cb=None) -> MouseDataset:
    """
    Load and preprocess all mouse data from mouse.db.

    Args:
        db_path: Path to mouse.db
        progress_cb: Optional callback(percent, message) for progress updates.
                     Percent is 0-100 within this function's scope.
    """
    logger.info(f"Loading mouse data from {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ── Load movements ────────────────────────────────────────
    if progress_cb:
        progress_cb(0, "Loading movements...")

    cursor = conn.execute(
        "SELECT id, start_x, start_y, end_x, end_y, "
        "start_t_ns, end_t_ns, end_event FROM movements"
    )
    raw_movements = cursor.fetchall()
    logger.info(f"  Loaded {len(raw_movements):,} movements")

    # ── Load path points (delta-encoded) ──────────────────────
    if progress_cb:
        progress_cb(10, "Loading path points...")

    # Load all path points sorted by movement_id, seq for reconstruction
    cursor = conn.execute(
        "SELECT movement_id, seq, x, y, dt_us FROM path_points "
        "ORDER BY movement_id, seq"
    )
    all_points = cursor.fetchall()
    logger.info(f"  Loaded {len(all_points):,} path points")

    # Group path points by movement_id
    if progress_cb:
        progress_cb(20, "Reconstructing paths...")

    points_by_movement: dict[int, list] = {}
    for row in all_points:
        mid = row["movement_id"]
        if mid not in points_by_movement:
            points_by_movement[mid] = []
        points_by_movement[mid].append(row)

    del all_points  # Free memory

    # ── Load click sequences for overshoot detection ──────────
    if progress_cb:
        progress_cb(30, "Loading click data...")

    cursor = conn.execute(
        "SELECT movement_id FROM click_sequences WHERE movement_id IS NOT NULL"
    )
    click_movement_ids = {row["movement_id"] for row in cursor.fetchall()}
    logger.info(f"  {len(click_movement_ids):,} movements ended with clicks")

    conn.close()

    # ── Reconstruct paths and compute features ────────────────
    if progress_cb:
        progress_cb(40, "Processing movements...")

    movements: list[MovementData] = []
    skipped_short = 0
    skipped_long = 0
    skipped_no_points = 0
    total_points = 0

    for i, row in enumerate(raw_movements):
        mid = row["id"]
        duration_ns = row["end_t_ns"] - row["start_t_ns"]
        duration_s = duration_ns / 1_000_000_000

        # Skip movements that are too long (idle-triggered)
        if duration_s > _MAX_DURATION_S:
            skipped_long += 1
            continue

        # Get path points for this movement
        pts = points_by_movement.get(mid)
        if not pts:
            skipped_no_points += 1
            continue

        if len(pts) < _MIN_PATH_POINTS:
            skipped_short += 1
            continue

        # Reconstruct absolute coordinates from delta encoding
        # seq=0: absolute (x, y), dt_us=0
        # seq>0: delta (dx, dy), dt_us from previous point
        path_x = np.empty(len(pts), dtype=np.int32)
        path_y = np.empty(len(pts), dtype=np.int32)
        path_t_ns = np.empty(len(pts), dtype=np.int64)

        path_x[0] = pts[0]["x"]
        path_y[0] = pts[0]["y"]
        path_t_ns[0] = row["start_t_ns"]

        for j in range(1, len(pts)):
            path_x[j] = path_x[j - 1] + pts[j]["x"]
            path_y[j] = path_y[j - 1] + pts[j]["y"]
            path_t_ns[j] = path_t_ns[j - 1] + pts[j]["dt_us"] * 1000

        total_points += len(pts)

        movements.append(MovementData(
            movement_id=mid,
            start_x=row["start_x"],
            start_y=row["start_y"],
            end_x=row["end_x"],
            end_y=row["end_y"],
            start_t_ns=row["start_t_ns"],
            end_t_ns=row["end_t_ns"],
            end_event=row["end_event"],
            path_x=path_x,
            path_y=path_y,
            path_t_ns=path_t_ns,
        ))

        if progress_cb and i % 5000 == 0:
            pct = 40 + int(50 * i / len(raw_movements))
            progress_cb(pct, f"Processing movement {i:,}/{len(raw_movements):,}...")

    # ── Compute feature arrays ────────────────────────────────
    if progress_cb:
        progress_cb(90, "Computing features...")

    n = len(movements)
    distances = np.empty(n, dtype=np.float64)
    angles = np.empty(n, dtype=np.float64)
    durations_ms = np.empty(n, dtype=np.float64)

    for i, m in enumerate(movements):
        dx = m.end_x - m.start_x
        dy = m.end_y - m.start_y
        distances[i] = np.sqrt(dx * dx + dy * dy)
        angles[i] = np.arctan2(dy, dx)
        durations_ms[i] = (m.end_t_ns - m.start_t_ns) / 1_000_000

    logger.info(
        f"  Mouse dataset ready: {n:,} movements, {total_points:,} path points\n"
        f"  Skipped: {skipped_long} too long, {skipped_short} too short, "
        f"{skipped_no_points} no points"
    )

    if progress_cb:
        progress_cb(100, "Mouse data loaded.")

    return MouseDataset(
        movements=movements,
        distances=distances,
        angles=angles,
        durations_ms=durations_ms,
        click_movement_ids=click_movement_ids,
        total_movements=n,
        total_path_points=total_points,
    )

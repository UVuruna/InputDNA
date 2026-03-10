"""
ML training orchestrator.

Main entry point for training all models from recorded data.
Called from the GUI via the "Train Model" button.

Runs the full pipeline:
1. Preprocessing — load and clean data from SQLite
2. Mouse models — path, speed, overshoot, jitter, click
3. Keyboard models — text digraph, number digraph, hold, shortcut
4. Save all models to user's data folder

Reports progress via callback for the GUI progress bar.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from ml.preprocessing.mouse_data import load_mouse_data
from ml.preprocessing.keyboard_data import load_keyboard_data
from ml.mouse.path_model import PathModel
from ml.mouse.speed_model import SpeedModel
from ml.mouse.overshoot_model import OvershootModel
from ml.mouse.jitter_model import JitterModel
from ml.mouse.click_model import ClickModel
from ml.keyboard.text_model import TextTypingModel
from ml.keyboard.number_model import NumberTypingModel
from ml.keyboard.hold_model import HoldModel
from ml.keyboard.shortcut_model import ShortcutModel

logger = logging.getLogger(__name__)

# Progress callback type: (percent: int, message: str) -> None
ProgressCallback = Callable[[int, str], None]

# Model file names within the models/ directory
_MODEL_FILES = {
    "path": "path_generator.pkl",
    "speed": "speed_profile.pkl",
    "overshoot": "overshoot_model.pkl",
    "jitter": "jitter_params.pkl",
    "click": "click_model.pkl",
    "text_typing": "text_typing.pkl",
    "number_typing": "number_typing.pkl",
    "key_hold": "key_hold.pkl",
    "shortcuts": "shortcuts.pkl",
}


@dataclass
class TrainingResult:
    """Result of a full training run."""
    success: bool
    models_dir: str = ""
    duration_s: float = 0.0
    trained_at: str = ""
    model_metrics: dict = field(default_factory=dict)
    error: str = ""

    @property
    def summary(self) -> str:
        """Human-readable summary for the GUI."""
        if not self.success:
            return f"Training failed: {self.error}"

        trained = [k for k, v in self.model_metrics.items()
                   if v.get("status") == "trained"]
        skipped = [k for k, v in self.model_metrics.items()
                   if v.get("status") == "skipped"]
        defaults = [k for k, v in self.model_metrics.items()
                    if v.get("status") == "trained_defaults"]

        parts = [f"{len(trained)} models trained"]
        if defaults:
            parts.append(f"{len(defaults)} with defaults")
        if skipped:
            parts.append(f"{len(skipped)} skipped (insufficient data)")
        parts.append(f"in {self.duration_s:.1f}s")
        parts.append(f"\nSaved to: {self.models_dir}")

        return " — ".join(parts)


def train_all(
    user_folder: Path,
    progress_cb: ProgressCallback | None = None,
) -> TrainingResult:
    """
    Run the full training pipeline for a user.

    Args:
        user_folder: User's data directory containing mouse.db, keyboard.db
        progress_cb: Callback for progress updates (percent 0-100, message string)

    Returns:
        TrainingResult with metrics and status for all models.
    """
    start_time = time.time()

    def _progress(pct: int, msg: str):
        if progress_cb:
            progress_cb(pct, msg)
        logger.info(f"[{pct:3d}%] {msg}")

    _progress(0, "Starting training pipeline...")

    mouse_db = user_folder / "mouse.db"
    keyboard_db = user_folder / "keyboard.db"
    models_dir = user_folder / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    metrics: dict = {}

    # ══════════════════════════════════════════════════════════
    # PHASE 1: PREPROCESSING (0-20%)
    # ══════════════════════════════════════════════════════════
    _progress(1, "Loading mouse data...")

    mouse_data = None
    if mouse_db.exists():
        def _mouse_progress(pct, msg):
            # Map 0-100 to 1-10
            _progress(1 + int(pct * 0.09), msg)

        mouse_data = load_mouse_data(mouse_db, progress_cb=_mouse_progress)
        logger.info(
            f"Mouse data: {mouse_data.total_movements:,} movements, "
            f"{mouse_data.total_path_points:,} path points"
        )
    else:
        logger.warning(f"Mouse database not found: {mouse_db}")

    _progress(11, "Loading keyboard data...")

    keyboard_data = None
    if keyboard_db.exists():
        def _kb_progress(pct, msg):
            _progress(11 + int(pct * 0.09), msg)

        keyboard_data = load_keyboard_data(keyboard_db, progress_cb=_kb_progress)
        logger.info(
            f"Keyboard data: {keyboard_data.total_transitions:,} transitions, "
            f"{keyboard_data.total_keystrokes:,} keystrokes"
        )
    else:
        logger.warning(f"Keyboard database not found: {keyboard_db}")

    # ══════════════════════════════════════════════════════════
    # PHASE 2: MOUSE MODELS (20-60%)
    # ══════════════════════════════════════════════════════════
    if mouse_data:
        # Path Generator (20-35%)
        _progress(20, "Training path generator...")
        path_model = PathModel()
        metrics["path"] = path_model.train(mouse_data)
        if path_model.is_trained:
            path_model.save(models_dir / _MODEL_FILES["path"])

        # Speed Profile (35-45%)
        _progress(35, "Training speed profile...")
        speed_model = SpeedModel()
        metrics["speed"] = speed_model.train(mouse_data)
        if speed_model.is_trained:
            speed_model.save(models_dir / _MODEL_FILES["speed"])

        # Overshoot Predictor (45-55%)
        _progress(45, "Training overshoot predictor...")
        overshoot_model = OvershootModel()
        metrics["overshoot"] = overshoot_model.train(mouse_data)
        if overshoot_model.is_trained:
            overshoot_model.save(models_dir / _MODEL_FILES["overshoot"])

        # Jitter Parameters (50-55%)
        _progress(50, "Training jitter model...")
        jitter_model = JitterModel()
        metrics["jitter"] = jitter_model.train(mouse_data)
        if jitter_model.is_trained:
            jitter_model.save(models_dir / _MODEL_FILES["jitter"])

        # Click Behavior (55-60%)
        _progress(55, "Training click model...")
        click_model = ClickModel()
        metrics["click"] = click_model.train(mouse_db)
        if click_model.is_trained:
            click_model.save(models_dir / _MODEL_FILES["click"])
    else:
        _progress(20, "Skipping mouse models (no data)")
        for key in ["path", "speed", "overshoot", "jitter", "click"]:
            metrics[key] = {"status": "skipped", "reason": "no mouse database"}

    # ══════════════════════════════════════════════════════════
    # PHASE 3: KEYBOARD MODELS (60-90%)
    # ══════════════════════════════════════════════════════════
    if keyboard_data:
        # Text Typing (60-70%)
        _progress(60, "Training text typing model...")
        text_model = TextTypingModel()
        metrics["text_typing"] = text_model.train(keyboard_data)
        if text_model.is_trained:
            text_model.save(models_dir / _MODEL_FILES["text_typing"])

        # Number Typing (70-75%)
        _progress(70, "Training number typing model...")
        number_model = NumberTypingModel()
        metrics["number_typing"] = number_model.train(keyboard_data)
        if number_model.is_trained:
            number_model.save(models_dir / _MODEL_FILES["number_typing"])

        # Key Hold Duration (75-80%)
        _progress(75, "Training key hold model...")
        hold_model = HoldModel()
        metrics["key_hold"] = hold_model.train(keyboard_data)
        if hold_model.is_trained:
            hold_model.save(models_dir / _MODEL_FILES["key_hold"])

        # Shortcut Timing (80-90%)
        _progress(80, "Training shortcut model...")
        shortcut_model = ShortcutModel()
        metrics["shortcuts"] = shortcut_model.train(keyboard_data)
        if shortcut_model.is_trained:
            shortcut_model.save(models_dir / _MODEL_FILES["shortcuts"])
    else:
        _progress(60, "Skipping keyboard models (no data)")
        for key in ["text_typing", "number_typing", "key_hold", "shortcuts"]:
            metrics[key] = {"status": "skipped", "reason": "no keyboard database"}

    # ══════════════════════════════════════════════════════════
    # PHASE 4: SAVE METADATA (90-100%)
    # ══════════════════════════════════════════════════════════
    _progress(90, "Saving metadata...")

    duration_s = time.time() - start_time
    trained_at = datetime.now().isoformat(timespec="seconds")

    metadata = {
        "trained_at": trained_at,
        "duration_s": round(duration_s, 1),
        "models": {k: v.get("status", "unknown") for k, v in metrics.items()},
        "data_stats": {},
    }

    if mouse_data:
        metadata["data_stats"]["mouse"] = {
            "movements": mouse_data.total_movements,
            "path_points": mouse_data.total_path_points,
        }
    if keyboard_data:
        metadata["data_stats"]["keyboard"] = {
            "transitions": keyboard_data.total_transitions,
            "keystrokes": keyboard_data.total_keystrokes,
            "shortcuts": keyboard_data.total_shortcuts,
        }

    metadata_path = models_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    _progress(100, "Training complete!")

    result = TrainingResult(
        success=True,
        models_dir=str(models_dir),
        duration_s=duration_s,
        trained_at=trained_at,
        model_metrics=metrics,
    )

    logger.info(f"Training complete in {duration_s:.1f}s")
    logger.info(f"Models saved to: {models_dir}")

    return result

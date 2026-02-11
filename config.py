"""
Human Input Recorder — Configuration

All configurable values in one place. Adjust these based on your
hardware and preferences. No other file should contain magic numbers.
"""

import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# DATA DIRECTORIES
# ─────────────────────────────────────────────────────────────
# Installed (PyInstaller exe): AppData\Local\InputDNA\
# Development: local data/ folder next to source
if getattr(sys, 'frozen', False):
    DATA_DIR = Path(os.environ['LOCALAPPDATA']) / "InputDNA"
else:
    DATA_DIR = Path(__file__).parent / "data"

DB_DIR = DATA_DIR / "db"
LOG_DIR = DATA_DIR / "logs"

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────
# Default DB path for headless mode (no logged-in user).
# When a user is logged in, use get_user_db_path(user_id) instead.
DB_PATH = DB_DIR / "movements.db"

# Active DB path set at runtime by the Recorder after login.
_active_db_path: Path | None = None


def get_user_db_path(user_id: int) -> Path:
    """Per-user database path: data/db/user_{id}/movements.db"""
    return DB_DIR / f"user_{user_id}" / "movements.db"


def get_active_db_path() -> Path:
    """Return the currently active DB path (per-user or fallback)."""
    return _active_db_path or DB_PATH


def set_active_db_path(path: Path) -> None:
    """Set the active DB path (called by Recorder on start)."""
    global _active_db_path
    _active_db_path = path

# Rotate to a new DB file when the active DB exceeds this size.
# Check happens once at session start, not during recording.
# Old file is renamed with a timestamp suffix and VACUUMed in background.
# Set to 0 to disable rotation.
DB_ROTATION_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB

# ─────────────────────────────────────────────────────────────
# PATH POINT SAMPLING
# ─────────────────────────────────────────────────────────────
# Target sampling rate for path points stored in the database.
# If your mouse polls at a higher rate, intermediate points are
# skipped to reduce DB size. First and last points are always kept.
#
# Valid values: 125, 250, 500, 1000, 2000, 4000, 8000
# Set to 0 to disable downsampling (store every point).
#
# Example: mouse at 1000 Hz + DOWNSAMPLE_HZ=250 → store every 4th point
# DB size reduction: ~4x for path_points (the largest table).
DOWNSAMPLE_HZ = 0
_VALID_DOWNSAMPLE_RATES = {0, 125, 250, 500, 1000, 2000, 4000, 8000}

if DOWNSAMPLE_HZ not in _VALID_DOWNSAMPLE_RATES:
    raise ValueError(
        f"DOWNSAMPLE_HZ={DOWNSAMPLE_HZ} is not valid. "
        f"Must be one of: {sorted(_VALID_DOWNSAMPLE_RATES)}"
    )

# ─────────────────────────────────────────────────────────────
# MOUSE SESSION DETECTION
# ─────────────────────────────────────────────────────────────
# After this many ms with no mouse movement, the current movement
# session is considered ended (if no click/scroll ended it first).
SESSION_END_TIMEOUT_MS = 300

# Ignore micro-sessions where total euclidean distance is less
# than this. These are usually accidental bumps, not intentional
# movements. Set to 0 to capture everything.
MIN_SESSION_DISTANCE_PX = 3

# ─────────────────────────────────────────────────────────────
# CLICK DETECTION
# ─────────────────────────────────────────────────────────────
# Maximum gap between consecutive clicks to consider them part
# of the same click sequence (double-click, triple, spam).
# Windows default double-click speed is ~500ms.
CLICK_SEQUENCE_GAP_MS = 500

# ─────────────────────────────────────────────────────────────
# DRAG DETECTION
# ─────────────────────────────────────────────────────────────
# Minimum distance moved while mouse button is held down to
# count as a drag operation (vs a click with slight movement).
DRAG_MIN_DISTANCE_PX = 5

# ─────────────────────────────────────────────────────────────
# SCROLL GROUPING
# ─────────────────────────────────────────────────────────────
# Gap between scroll events to consider them separate sequences.
SCROLL_SEQUENCE_GAP_MS = 500

# ─────────────────────────────────────────────────────────────
# DATABASE WRITER
# ─────────────────────────────────────────────────────────────
# How many records to accumulate before flushing to disk.
BATCH_SIZE = 100

# Maximum seconds between flushes, even if batch isn't full.
FLUSH_INTERVAL_S = 2.0

# ─────────────────────────────────────────────────────────────
# SYSTEM MONITOR
# ─────────────────────────────────────────────────────────────
# How often to check for system state changes (mouse speed,
# acceleration, screen resolution, keyboard layout).
SYSTEM_MONITOR_INTERVAL_S = 10.0

# Number of mouse move events to sample for polling rate estimation.
POLLING_RATE_SAMPLE_COUNT = 500

# ─────────────────────────────────────────────────────────────
# HOTKEY
# ─────────────────────────────────────────────────────────────
# Global hotkey to pause/resume recording.
HOTKEY_TOGGLE = "<ctrl>+<alt>+r"

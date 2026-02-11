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
DB_PATH = DB_DIR / "movements.db"

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

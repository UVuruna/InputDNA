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
# Three databases per user: mouse.db, keyboard.db, session.db.
# Active user folder is set at login time via set_active_user().

# Active user folder set at runtime after login.
_active_user_folder: Path | None = None


def get_user_data_dir() -> Path:
    """Base directory for per-user data. Custom path if set, otherwise DB_DIR."""
    if CUSTOM_USER_DATA_DIR:
        return Path(CUSTOM_USER_DATA_DIR)
    return DB_DIR


def get_user_folder(username: str, surname: str, date_of_birth: str) -> Path:
    """
    Per-user data folder: data/db/Uros_Vuruna_1990-06-20/

    Folder name encodes identity: Username_Surname_YYYY-MM-DD.
    Uses CUSTOM_USER_DATA_DIR if set, otherwise DB_DIR.
    """
    folder_name = f"{username}_{surname}_{date_of_birth}"
    return get_user_data_dir() / folder_name


def set_active_user(username: str, surname: str, date_of_birth: str) -> None:
    """Set the active user folder (called on login)."""
    global _active_user_folder
    _active_user_folder = get_user_folder(username, surname, date_of_birth)


def clear_active_user() -> None:
    """Clear the active user folder (called on logout)."""
    global _active_user_folder
    _active_user_folder = None


def get_active_user_folder() -> Path:
    """Return the active user's data folder, or DB_DIR as fallback."""
    return _active_user_folder or DB_DIR


def get_active_mouse_db() -> Path:
    """Path to active user's mouse database."""
    return get_active_user_folder() / "mouse.db"


def get_active_keyboard_db() -> Path:
    """Path to active user's keyboard database."""
    return get_active_user_folder() / "keyboard.db"


def get_active_session_db() -> Path:
    """Path to active user's session database."""
    return get_active_user_folder() / "session.db"

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

# Rolling window size for polling rate estimation (number of filtered intervals).
# Larger window = more stable estimate; at 500 Hz ~0.6 s to fill initially.
POLLING_RATE_SAMPLE_COUNT = 300

# Seconds between periodic re-estimation after the first result.
# First estimate fires immediately when the window fills.
POLLING_RATE_UPDATE_INTERVAL_S = 60.0

# Hardware interval bounds for filtering (nanoseconds).
# Intervals outside this range are discarded before entering the window.
#   Min = 125 μs  →  fastest possible interval at 8000 Hz (burst artifact threshold)
#   Max = 20 ms   →  slower than 50 Hz; indicates idle gap, not a real poll interval
POLLING_RATE_MIN_INTERVAL_NS = 125_000      # 8000 Hz upper bound
POLLING_RATE_MAX_INTERVAL_NS = 20_000_000   # 50 Hz lower bound

# How often the main MouseListener logs its timing quality report.
# Report shows inter-move interval distribution (P10/P50/P90) and % clean intervals.
# Visible in logs — allows detecting timestamp jitter without reading the database.
TIMING_QUALITY_LOG_INTERVAL_S = 300.0       # every 5 minutes

# Estimated mouse polling rate (Hz). Set at runtime by the polling rate
# estimator after login. None means not yet measured.
# Used by settings screen to filter downsample options.
ESTIMATED_POLLING_HZ: int | None = None

# Standard polling rates (hardware). Used to snap estimated Hz to nearest.
_STANDARD_POLLING_RATES = [125, 250, 500, 1000, 2000, 4000, 8000]


def snap_polling_rate(raw_hz: int) -> int:
    """Snap a raw estimated Hz to the nearest standard polling rate."""
    return min(_STANDARD_POLLING_RATES, key=lambda r: abs(r - raw_hz))

# Seconds of no mouse/keyboard input before tray icon shows idle state.
# Purely cosmetic — recorder still runs, just visual feedback.
IDLE_ICON_TIMEOUT_S = 60

# ─────────────────────────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────────────────────────
# Time window for the "Last N min" stats view on the dashboard.
# Valid values: 10, 20, 30, 40, 50, 60. Per-user setting.
STATS_WINDOW_MINUTES = 30

# ─────────────────────────────────────────────────────────────
# CALIBRATION
# ─────────────────────────────────────────────────────────────
# Number of clicks required for click speed calibration.
CALIBRATION_CLICK_COUNT = 20

# ─────────────────────────────────────────────────────────────
# USER SETTINGS (GUI-configurable)
# ─────────────────────────────────────────────────────────────
# Mouse DPI — hardware-specific, entered manually or measured by user.
USER_DPI = 800

# Auto-start recording on Windows login.
START_WITH_WINDOWS = False

# Minimize to system tray on close (instead of exiting).
# When enabled, the X button hides the window — only tray Quit exits.
MINIMIZE_ON_CLOSE = False

# Default user for auto-login (username string, empty = disabled).
# Used with START_WITH_WINDOWS for unattended startup.
DEFAULT_USER = ""

# Custom base directory for per-user recording data.
# When set (non-empty), user folders are created here instead of DB_DIR.
# profiles.db always stays in DB_DIR (needed for login before this is applied).
# Set via Settings → Storage → Data location.
CUSTOM_USER_DATA_DIR = ""

# ─────────────────────────────────────────────────────────────
# PER-USER SETTINGS OVERRIDE
# ─────────────────────────────────────────────────────────────
# Mapping from user_settings DB keys to (config attribute, type converter).
# Used by apply_user_settings() to override defaults at runtime.
_SETTING_MAP: dict[str, tuple[str, type]] = {
    "recording.downsample_hz":          ("DOWNSAMPLE_HZ", int),
    "recording.session_end_timeout_ms": ("SESSION_END_TIMEOUT_MS", int),
    "recording.min_session_distance_px":("MIN_SESSION_DISTANCE_PX", int),
    "recording.db_rotation_max_bytes":  ("DB_ROTATION_MAX_BYTES", int),
    "recording.click_sequence_gap_ms":  ("CLICK_SEQUENCE_GAP_MS", int),
    "system.dpi":                       ("USER_DPI", int),
    "recording.stats_window_minutes":   ("STATS_WINDOW_MINUTES", int),
}

# Snapshot of default values — populated at module load, used by reset_to_defaults().
_DEFAULTS: dict[str, object] = {}


def _capture_defaults() -> None:
    """Snapshot all overridable config values at import time."""
    import sys
    module = sys.modules[__name__]
    for _key, (attr, _conv) in _SETTING_MAP.items():
        _DEFAULTS[attr] = getattr(module, attr)


def apply_user_settings(settings: dict[str, str]) -> None:
    """
    Override config module attributes with per-user settings.

    Called once at login time. All code reading config.* will see
    the overridden values. Thread-safe because this runs before
    recorder threads start.
    """
    import sys
    module = sys.modules[__name__]
    for key, value in settings.items():
        if key in _SETTING_MAP:
            attr, converter = _SETTING_MAP[key]
            setattr(module, attr, converter(value))


def reset_to_defaults() -> None:
    """Restore all config values to their original defaults (on logout)."""
    import sys
    module = sys.modules[__name__]
    for attr, default_value in _DEFAULTS.items():
        setattr(module, attr, default_value)


# Capture defaults at module load time.
_capture_defaults()

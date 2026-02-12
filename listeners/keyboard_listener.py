"""
Keyboard event listener.

Hooks into OS-level keyboard events via pynput and pushes raw events
to a shared queue. Runs in a dedicated daemon thread.

Key design: captures SCAN CODES (physical key position) which are
layout-independent. The same physical key always produces the same
scan code regardless of whether English, Serbian, or any other
layout is active.

On Windows, pynput gives us virtual key codes (vk). We convert
to scan codes using MapVirtualKeyW from the Windows API.
"""

import queue
import logging
import ctypes
from pynput import keyboard

from models.events import RawKeyPress, RawKeyRelease
from utils.timing import now_ns, ns_to_ms

logger = logging.getLogger(__name__)

# Windows API for vk → scan code conversion
_user32 = ctypes.windll.user32
_MAPVK_VK_TO_VSC_EX = 4  # Includes extended bit for keys like Right Ctrl

# Modifier keys we track (by scan code)
_MODIFIER_SCANS = {
    0x1D: "ctrl",     # Left Ctrl
    0xE01D: "ctrl",   # Right Ctrl
    0x38: "alt",      # Left Alt
    0xE038: "alt",    # Right Alt
    0x2A: "shift",    # Left Shift
    0x36: "shift",    # Right Shift
    0x5B: "win",      # Left Win
    0x5C: "win",      # Right Win
}


def _get_active_layout() -> str:
    """
    Get the active keyboard layout for the foreground window.
    Returns layout ID as hex string (e.g. "0x04090409" for US English).
    """
    hwnd = _user32.GetForegroundWindow()
    thread_id = _user32.GetWindowThreadProcessId(hwnd, None)
    layout_id = _user32.GetKeyboardLayout(thread_id)
    return hex(layout_id & 0xFFFFFFFF)


def _vk_to_scan(vk: int) -> int:
    """
    Convert virtual key code to scan code using Windows API.
    Returns extended scan code (e.g. 0xE01D for Right Ctrl).
    """
    scan = _user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC_EX)
    # MapVirtualKeyW with flag 4 returns extended scan code
    # with the extended bit in the upper byte
    return scan if scan else vk  # Fallback to vk if mapping fails


def _name_from_vk(vk: int) -> str:
    """Resolve human-readable key name from virtual key code.

    Used when key.char gives a control character (e.g. Ctrl+C → '\\x03').
    """
    if 0x41 <= vk <= 0x5A:  # A-Z
        return chr(vk).lower()
    if 0x30 <= vk <= 0x39:  # 0-9
        return chr(vk)

    # Other keys: ask Windows for the name via scan code
    scan = _user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    if scan:
        buf = ctypes.create_unicode_buffer(64)
        if _user32.GetKeyNameTextW(scan << 16, buf, 64):
            return buf.value.lower()
    return f"vk_{vk}"


def _get_key_info(key) -> tuple[int, int, str]:
    """
    Extract (vk, scan_code, key_name) from a pynput key event.
    Handles both regular keys and special keys.
    """
    if hasattr(key, 'vk') and key.vk is not None:
        vk = key.vk
        scan = _vk_to_scan(vk)
        try:
            char = key.char
            # Control characters (Ctrl+C → '\x03') are not readable names
            if char and ord(char) >= 0x20:
                name = char
            else:
                name = _name_from_vk(vk)
        except AttributeError:
            name = _name_from_vk(vk)
    elif hasattr(key, 'value') and hasattr(key.value, 'vk'):
        # Special keys (Key.ctrl_l, Key.shift, etc.)
        vk = key.value.vk
        scan = _vk_to_scan(vk)
        name = key.name if hasattr(key, 'name') else str(key)
    else:
        # Fallback
        vk = getattr(key, 'vk', 0) or 0
        scan = _vk_to_scan(vk) if vk else 0
        name = str(key)

    # Clean up name: remove "Key." prefix if present
    if name.startswith("Key."):
        name = name[4:]

    return vk, scan, name


class KeyboardListener:
    """
    Captures keyboard events and pushes them to a shared queue.

    Tracks modifier state internally and calculates press duration
    on key release.

    Usage:
        q = queue.Queue()
        kl = KeyboardListener(q)
        kl.start()
        ...
        kl.stop()
    """

    def __init__(self, event_queue: queue.Queue):
        self._queue = event_queue
        self._listener: keyboard.Listener | None = None
        self._paused = False

        # Modifier state tracking
        self._modifier_state = {
            "ctrl": False,
            "alt": False,
            "shift": False,
            "win": False,
        }

        # Track press timestamps for duration calculation
        # Key: scan_code, Value: t_ns of press
        self._press_times: dict[int, int] = {}

    def start(self):
        """Start listening for keyboard events in a background thread."""
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Keyboard listener started")

    def stop(self):
        """Stop listening."""
        if self._listener is not None:
            self._listener.stop()
            logger.info("Keyboard listener stopped")

    def pause(self):
        """Pause event capture."""
        self._paused = True
        self._press_times.clear()
        self._modifier_state = {k: False for k in self._modifier_state}
        logger.info("Keyboard listener paused")

    def resume(self):
        """Resume event capture."""
        self._paused = False
        logger.info("Keyboard listener resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def modifier_state(self) -> dict:
        """Current modifier key state (read-only copy)."""
        return self._modifier_state.copy()

    def _on_press(self, key):
        if self._paused:
            return

        t = now_ns()
        vk, scan, name = _get_key_info(key)

        if scan == 0:
            return  # Unknown key, skip

        # Update modifier state
        mod = _MODIFIER_SCANS.get(scan)
        if mod:
            self._modifier_state[mod] = True

        # Track press time (only first press, ignore key repeat)
        if scan not in self._press_times:
            self._press_times[scan] = t

        self._queue.put(RawKeyPress(
            scan_code=scan,
            vkey=vk,
            key_name=name,
            t_ns=t,
            modifier_state=self._modifier_state.copy(),
            active_layout=_get_active_layout(),
        ))

    def _on_release(self, key):
        if self._paused:
            return

        t = now_ns()
        vk, scan, name = _get_key_info(key)

        if scan == 0:
            return

        # Update modifier state
        mod = _MODIFIER_SCANS.get(scan)
        if mod:
            self._modifier_state[mod] = False

        # Calculate press duration
        press_t = self._press_times.pop(scan, None)
        duration_ms = ns_to_ms(t - press_t) if press_t is not None else 0.0

        self._queue.put(RawKeyRelease(
            scan_code=scan,
            key_name=name,
            t_ns=t,
            press_duration_ms=duration_ms,
        ))

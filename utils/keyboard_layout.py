"""
Physical keyboard layout based on scan codes.

Scan codes represent PHYSICAL key positions on the keyboard.
They are completely independent of the active language layout.
The same physical key always has the same scan code whether
you're typing in English, Serbian Latin, Serbian Cyrillic, etc.

This module maps scan codes to (hand, finger, row, col) for
ergonomic analysis — which hand/finger is used affects typing
speed and transition delays.

Standard HID scan codes for a full-size keyboard.
Row 0 = number row, Row 1 = QWERTY row, Row 2 = home row, Row 3 = bottom row.
Col increases left to right.
"""

import math
from typing import Tuple, Optional

# (hand, finger, row, col)
# Finger: pinky=0, ring=1, middle=2, index=3, thumb=4
# Used for physical distance calculations

_FINGER_NAMES = {0: "pinky", 1: "ring", 2: "middle", 3: "index", 4: "thumb"}
_HAND_NAMES = {0: "left", 1: "right"}

# scan_code → (hand_id, finger_id, row, col)
# Hand: 0=left, 1=right
PHYSICAL_MAP: dict[int, Tuple[int, int, int, int]] = {
    # ── Number row (row 0) ──────────────────────────────────
    0x29: (0, 0, 0, 0),   # ` ~
    0x02: (0, 0, 0, 1),   # 1 !
    0x03: (0, 1, 0, 2),   # 2 @
    0x04: (0, 2, 0, 3),   # 3 #
    0x05: (0, 3, 0, 4),   # 4 $
    0x06: (0, 3, 0, 5),   # 5 %
    0x07: (1, 3, 0, 6),   # 6 ^
    0x08: (1, 3, 0, 7),   # 7 &
    0x09: (1, 2, 0, 8),   # 8 *
    0x0A: (1, 1, 0, 9),   # 9 (
    0x0B: (1, 0, 0, 10),  # 0 )
    0x0C: (1, 0, 0, 11),  # - _
    0x0D: (1, 0, 0, 12),  # = +
    0x0E: (1, 0, 0, 13),  # Backspace

    # ── QWERTY row (row 1) ─────────────────────────────────
    0x0F: (0, 0, 1, 0),   # Tab
    0x10: (0, 0, 1, 1),   # Q
    0x11: (0, 1, 1, 2),   # W
    0x12: (0, 2, 1, 3),   # E
    0x13: (0, 3, 1, 4),   # R
    0x14: (0, 3, 1, 5),   # T
    0x15: (1, 3, 1, 6),   # Y
    0x16: (1, 3, 1, 7),   # U
    0x17: (1, 2, 1, 8),   # I
    0x18: (1, 1, 1, 9),   # O
    0x19: (1, 0, 1, 10),  # P
    0x1A: (1, 0, 1, 11),  # [ {
    0x1B: (1, 0, 1, 12),  # ] }
    0x2B: (1, 0, 1, 13),  # \ |

    # ── Home row (row 2) ───────────────────────────────────
    0x3A: (0, 0, 2, 0),   # Caps Lock
    0x1E: (0, 0, 2, 1),   # A
    0x1F: (0, 1, 2, 2),   # S
    0x20: (0, 2, 2, 3),   # D
    0x21: (0, 3, 2, 4),   # F
    0x22: (0, 3, 2, 5),   # G
    0x23: (1, 3, 2, 6),   # H
    0x24: (1, 3, 2, 7),   # J
    0x25: (1, 2, 2, 8),   # K
    0x26: (1, 1, 2, 9),   # L
    0x27: (1, 0, 2, 10),  # ; :
    0x28: (1, 0, 2, 11),  # ' "
    0x1C: (1, 0, 2, 12),  # Enter

    # ── Bottom row (row 3) ─────────────────────────────────
    0x2A: (0, 0, 3, 0),   # Left Shift
    0x2C: (0, 0, 3, 1),   # Z
    0x2D: (0, 1, 3, 2),   # X
    0x2E: (0, 2, 3, 3),   # C
    0x2F: (0, 3, 3, 4),   # V
    0x30: (0, 3, 3, 5),   # B
    0x31: (1, 3, 3, 6),   # N
    0x32: (1, 3, 3, 7),   # M
    0x33: (1, 2, 3, 8),   # , <
    0x34: (1, 1, 3, 9),   # . >
    0x35: (1, 0, 3, 10),  # / ?
    0x36: (1, 0, 3, 11),  # Right Shift

    # ── Space row (row 4) ──────────────────────────────────
    0x1D: (0, 0, 4, 0),   # Left Ctrl
    0x5B: (0, 0, 4, 1),   # Left Win
    0x38: (0, 4, 4, 2),   # Left Alt
    0x39: (0, 4, 4, 5),   # Space (center, left thumb by convention)
    0xE038: (1, 4, 4, 8), # Right Alt (AltGr) — extended scan code
    0x5C: (1, 0, 4, 9),   # Right Win
    0x5D: (1, 0, 4, 10),  # Menu
    0xE01D: (1, 0, 4, 11),# Right Ctrl — extended scan code

    # ── Function keys (row -1, above number row) ──────────
    0x01: (0, 0, -1, 0),  # Escape
    0x3B: (0, 0, -1, 1),  # F1
    0x3C: (0, 1, -1, 2),  # F2
    0x3D: (0, 2, -1, 3),  # F3
    0x3E: (0, 3, -1, 4),  # F4
    0x3F: (0, 3, -1, 5),  # F5
    0x40: (1, 3, -1, 6),  # F6
    0x41: (1, 3, -1, 7),  # F7
    0x42: (1, 2, -1, 8),  # F8
    0x43: (1, 1, -1, 9),  # F9
    0x44: (1, 0, -1, 10), # F10
    0x57: (1, 0, -1, 11), # F11
    0x58: (1, 0, -1, 12), # F12

    # ── Navigation cluster ─────────────────────────────────
    0xE052: (1, 2, -1, 14),  # Insert
    0xE047: (1, 2, -1, 15),  # Home
    0xE049: (1, 2, -1, 16),  # Page Up
    0xE053: (1, 2, 0, 14),   # Delete
    0xE04F: (1, 2, 0, 15),   # End
    0xE051: (1, 2, 0, 16),   # Page Down

    # ── Arrow keys ─────────────────────────────────────────
    0xE048: (1, 2, 2, 15),   # Up
    0xE04B: (1, 1, 3, 14),   # Left
    0xE050: (1, 2, 3, 15),   # Down
    0xE04D: (1, 2, 3, 16),   # Right

    # ── Numpad ─────────────────────────────────────────────
    0x45: (1, 2, 0, 18),  # Num Lock
    0xE035: (1, 1, 0, 19),# Numpad /
    0x37: (1, 2, 0, 20),  # Numpad *
    0x4A: (1, 0, 0, 21),  # Numpad -
    0x47: (1, 3, 1, 18),  # Numpad 7
    0x48: (1, 2, 1, 19),  # Numpad 8
    0x49: (1, 1, 1, 20),  # Numpad 9
    0x4E: (1, 0, 1, 21),  # Numpad +
    0x4B: (1, 3, 2, 18),  # Numpad 4
    0x4C: (1, 2, 2, 19),  # Numpad 5
    0x4D: (1, 1, 2, 20),  # Numpad 6
    0x4F: (1, 3, 3, 18),  # Numpad 1
    0x50: (1, 2, 3, 19),  # Numpad 2
    0x51: (1, 1, 3, 20),  # Numpad 3
    0xE01C: (1, 0, 3, 21),# Numpad Enter
    0x52: (1, 3, 4, 18),  # Numpad 0 (wide key)
    0x53: (1, 2, 4, 20),  # Numpad .
}

# Approximate physical key spacing in millimeters
_KEY_WIDTH_MM = 19.05  # Standard key pitch


def _get_info(scan_code: int) -> Optional[Tuple[int, int, int, int]]:
    """Get (hand, finger, row, col) for a scan code, or None."""
    return PHYSICAL_MAP.get(scan_code)


def infer_hand(scan_code: int) -> str:
    """Which hand presses this key. Returns 'left', 'right', or 'unknown'."""
    info = _get_info(scan_code)
    if info is None:
        return "unknown"
    return _HAND_NAMES[info[0]]


def infer_finger(scan_code: int) -> str:
    """Which finger presses this key. Returns finger name or 'unknown'."""
    info = _get_info(scan_code)
    if info is None:
        return "unknown"
    return _FINGER_NAMES[info[1]]


def same_hand(sc1: int, sc2: int) -> Optional[bool]:
    """True if both keys are pressed by the same hand. None if unknown."""
    i1, i2 = _get_info(sc1), _get_info(sc2)
    if i1 is None or i2 is None:
        return None
    return i1[0] == i2[0]


def same_finger(sc1: int, sc2: int) -> Optional[bool]:
    """True if both keys are pressed by the same finger. None if unknown."""
    i1, i2 = _get_info(sc1), _get_info(sc2)
    if i1 is None or i2 is None:
        return None
    return i1[0] == i2[0] and i1[1] == i2[1]


def physical_distance(sc1: int, sc2: int) -> Optional[float]:
    """
    Approximate physical distance between two keys in millimeters.
    Based on standard key grid positions.
    Returns None if either key is unknown.
    """
    i1, i2 = _get_info(sc1), _get_info(sc2)
    if i1 is None or i2 is None:
        return None
    row_diff = abs(i1[2] - i2[2])
    col_diff = abs(i1[3] - i2[3])
    return math.sqrt(row_diff**2 + col_diff**2) * _KEY_WIDTH_MM


def get_position(scan_code: int) -> Optional[Tuple[int, int]]:
    """Get (row, col) grid position for a scan code."""
    info = _get_info(scan_code)
    if info is None:
        return None
    return (info[2], info[3])

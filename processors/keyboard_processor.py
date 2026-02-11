"""
Keyboard event processor.

Produces three types of records:
1. KeystrokeRecord — individual key presses with scan code + duration
2. KeyTransitionRecord — delay between consecutive keys (scan code pairs)
3. ShortcutRecord — modifier+key combos with full timing profile

All tracking is based on SCAN CODES (physical key position), making
it layout-independent. The delay between two physical positions is
the same whether you're typing in English or Serbian.
"""

import json
import logging
from typing import Optional, Callable

from models.events import RawKeyPress, RawKeyRelease
from models.sessions import KeystrokeRecord, KeyTransitionRecord, ShortcutRecord
from utils.timing import ns_to_ms, interval_ms, wall_clock_iso
from utils.keyboard_layout import infer_hand, infer_finger

logger = logging.getLogger(__name__)

# Modifier scan codes (to detect shortcuts and exclude from transitions)
_MODIFIER_SCANS = {
    0x1D, 0xE01D,  # Left/Right Ctrl
    0x38, 0xE038,  # Left/Right Alt
    0x2A, 0x36,    # Left/Right Shift
    0x5B, 0x5C,    # Left/Right Win
}

# Numpad scan codes
_NUMPAD_SCANS = {
    0x45,   # Num Lock
    0xE035, # Numpad /
    0x37,   # Numpad *
    0x4A,   # Numpad -
    0x4E,   # Numpad +
    0x47, 0x48, 0x49,  # 7, 8, 9
    0x4B, 0x4C, 0x4D,  # 4, 5, 6
    0x4F, 0x50, 0x51,  # 1, 2, 3
    0x52, 0x53,         # 0, .
    0xE01C,             # Numpad Enter
}

# Common programming scan codes (brackets, operators, etc.)
_CODE_SCANS = {
    0x1A, 0x1B,  # [ ]
    0x27, 0x28,  # ; '
    0x2B,        # backslash
    0x0C, 0x0D,  # - =
    0x29,        # ` ~
}


def _detect_typing_mode(scan: int, modifier_state: dict) -> str:
    """Classify current typing context."""
    if any(modifier_state.get(m) for m in ("ctrl", "alt", "win")):
        return "shortcut"
    if scan in _NUMPAD_SCANS:
        return "numpad"
    if scan in _CODE_SCANS:
        return "code"
    return "text"


class KeyboardProcessor:
    """
    Processes keyboard events into structured records.

    Call process_press() and process_release() as events arrive.
    Completed records are emitted via callbacks.
    """

    def __init__(self,
                 on_keystroke: Callable[[KeystrokeRecord], None],
                 on_transition: Callable[[KeyTransitionRecord], None],
                 on_shortcut: Callable[[ShortcutRecord], None]):
        self._on_keystroke = on_keystroke
        self._on_transition = on_transition
        self._on_shortcut = on_shortcut

        # Last non-modifier key press for transition tracking
        self._last_scan: Optional[int] = None
        self._last_key_name: Optional[str] = None
        self._last_press_t_ns: Optional[int] = None

        # Shortcut tracking
        self._active_modifiers: dict[int, int] = {}  # scan → press t_ns
        self._shortcut_main_scan: Optional[int] = None
        self._shortcut_main_t_ns: int = 0
        self._shortcut_main_name: str = ""

    def process_press(self, event: RawKeyPress):
        """Process a key press event."""
        scan = event.scan_code
        is_mod = scan in _MODIFIER_SCANS

        if is_mod:
            # Track modifier press time for shortcut timing
            self._active_modifiers[scan] = event.t_ns
        else:
            # Check if this is a shortcut (modifier held + regular key)
            if self._active_modifiers:
                self._shortcut_main_scan = scan
                self._shortcut_main_t_ns = event.t_ns
                self._shortcut_main_name = event.key_name

            # Track transition (delay between consecutive non-modifier keys)
            if self._last_scan is not None and self._last_press_t_ns is not None:
                delay = ns_to_ms(event.t_ns - self._last_press_t_ns)
                mode = _detect_typing_mode(scan, event.modifier_state)

                self._on_transition(KeyTransitionRecord(
                    from_scan=self._last_scan,
                    to_scan=scan,
                    from_key_name=self._last_key_name or "",
                    to_key_name=event.key_name,
                    delay_ms=delay,
                    typing_mode=mode,
                    t_ns=event.t_ns,
                ))

            self._last_scan = scan
            self._last_key_name = event.key_name
            self._last_press_t_ns = event.t_ns

    def process_release(self, event: RawKeyRelease):
        """Process a key release event."""
        scan = event.scan_code
        is_mod = scan in _MODIFIER_SCANS

        # Emit keystroke record for every key release
        self._on_keystroke(KeystrokeRecord(
            scan_code=scan,
            key_name=event.key_name,
            press_duration_ms=event.press_duration_ms,
            modifier_state="{}",  # Could be enriched if needed
            hand=infer_hand(scan),
            finger=infer_finger(scan),
            t_ns=event.t_ns,
            timestamp=wall_clock_iso(),
        ))

        # Shortcut detection: if a modifier is released and we had a main key
        if is_mod and self._shortcut_main_scan is not None:
            self._try_emit_shortcut(event)

        if is_mod:
            self._active_modifiers.pop(scan, None)

        # If main key of shortcut is released, record its timing
        if scan == self._shortcut_main_scan:
            # Main key released before modifier — note this for release order
            pass  # Release order determined in _try_emit_shortcut

    def _try_emit_shortcut(self, modifier_release: RawKeyRelease):
        """Try to emit a shortcut record when a modifier is released."""
        if not self._active_modifiers and self._shortcut_main_scan is None:
            return

        mod_scan = modifier_release.scan_code
        mod_press_t = self._active_modifiers.get(mod_scan)
        if mod_press_t is None:
            return

        main_scan = self._shortcut_main_scan
        main_press_t = self._shortcut_main_t_ns
        main_name = self._shortcut_main_name

        # Build shortcut name
        mod_names = []
        for ms in sorted(self._active_modifiers.keys()):
            if ms in (0x1D, 0xE01D):
                mod_names.append("Ctrl")
            elif ms in (0x38, 0xE038):
                mod_names.append("Alt")
            elif ms in (0x2A, 0x36):
                mod_names.append("Shift")
            elif ms in (0x5B, 0x5C):
                mod_names.append("Win")
        mod_names = list(dict.fromkeys(mod_names))  # Deduplicate

        # Earliest modifier press
        earliest_mod_t = min(self._active_modifiers.values())

        shortcut_name = "+".join(mod_names + [main_name])
        mod_to_main = ns_to_ms(main_press_t - earliest_mod_t)
        total = ns_to_ms(modifier_release.t_ns - earliest_mod_t)

        # We don't have main key release time here precisely,
        # so overlap is approximate
        overlap = ns_to_ms(modifier_release.t_ns - main_press_t)

        self._on_shortcut(ShortcutRecord(
            shortcut_name=shortcut_name,
            modifier_scans=json.dumps(list(self._active_modifiers.keys())),
            main_scan=main_scan,
            main_key_name=main_name,
            modifier_to_main_ms=max(0, mod_to_main),
            main_hold_ms=0,  # Filled more precisely in post-processing
            overlap_ms=max(0, overlap),
            total_ms=max(0, total),
            release_order="modifier_first",  # Since modifier triggered this
            t_ns=int(earliest_mod_t),
            timestamp=wall_clock_iso(),
        ))

        # Reset shortcut tracking
        self._shortcut_main_scan = None
        self._shortcut_main_t_ns = 0
        self._shortcut_main_name = ""

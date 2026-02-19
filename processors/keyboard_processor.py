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

# ── Scan code sets ────────────────────────────────────────────
# Used internally for typing mode detection and imported by
# EventProcessor for keystroke classification (dashboard stats).

MODIFIER_SCANS = frozenset({
    0x1D, 0xE01D,  # Left/Right Ctrl
    0x38, 0xE038,  # Left/Right Alt
    0x2A, 0x36,    # Left/Right Shift
    0x5B, 0x5C,    # Left/Right Win
})

NUMPAD_SCANS = frozenset({
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
})

CODE_SCANS = frozenset({
    0x1A, 0x1B,  # [ ]
    0x27, 0x28,  # ; '
    0x2B,        # backslash
    0x0C, 0x0D,  # - =
    0x29,        # ` ~
})

LETTER_SCANS = frozenset({
    0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,  # Q-P
    0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,        # A-L
    0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32,                    # Z-M
})

NUMBER_ROW_SCANS = frozenset({
    0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,  # 1-0
})

WHITESPACE_SCANS = frozenset({
    0x39,   # Space
    0x0F,   # Tab
    0x1C,   # Enter
    0xE01C, # Numpad Enter
})

CAPSLOCK_SCAN = 0x3A


def _detect_typing_mode(scan: int, modifier_state: dict) -> str:
    """Classify current typing context."""
    if any(modifier_state.get(m) for m in ("ctrl", "alt", "win")):
        return "shortcut"
    if scan in NUMPAD_SCANS:
        return "numpad"
    if scan in CODE_SCANS:
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

        # Press context: stores (vkey, active_layout, modifier_state_json)
        # from press events, keyed by scan code, used on release
        self._press_context: dict[int, tuple[int, str, str]] = {}

        # Shortcut tracking
        self._active_modifiers: dict[int, int] = {}  # scan → press t_ns
        self._shortcut_main_scan: Optional[int] = None
        self._shortcut_main_t_ns: int = 0
        self._shortcut_main_name: str = ""
        self._shortcut_main_release_t_ns: Optional[int] = None

    def process_press(self, event: RawKeyPress):
        """Process a key press event."""
        scan = event.scan_code
        is_mod = scan in MODIFIER_SCANS

        # Store press context for use on release
        self._press_context[scan] = (
            event.vkey,
            event.active_layout,
            json.dumps(event.modifier_state),
        )

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
        is_mod = scan in MODIFIER_SCANS

        # Retrieve press context (vkey, layout, modifiers stored on press)
        vkey, active_layout, modifier_json = self._press_context.pop(scan, (0, "", "{}"))

        # Emit keystroke record for every key release
        self._on_keystroke(KeystrokeRecord(
            scan_code=scan,
            vkey=vkey,
            key_name=event.key_name,
            press_duration_ms=event.press_duration_ms,
            modifier_state=modifier_json,
            active_layout=active_layout,
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

        # Track main key release for shortcut timing
        if scan == self._shortcut_main_scan:
            self._shortcut_main_release_t_ns = event.t_ns

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

        # Determine release order and timing from tracked release events
        main_release_t = self._shortcut_main_release_t_ns
        mod_release_t = modifier_release.t_ns

        if main_release_t is not None:
            # Main key was released before modifier
            release_order = "main_first"
            main_hold = ns_to_ms(main_release_t - main_press_t)
            overlap = ns_to_ms(main_release_t - main_press_t)
            total = ns_to_ms(mod_release_t - earliest_mod_t)
        else:
            # Modifier released while main key still held
            release_order = "modifier_first"
            main_hold = ns_to_ms(mod_release_t - main_press_t)
            overlap = ns_to_ms(mod_release_t - main_press_t)
            total = ns_to_ms(mod_release_t - earliest_mod_t)

        self._on_shortcut(ShortcutRecord(
            shortcut_name=shortcut_name,
            modifier_scans=json.dumps(list(self._active_modifiers.keys())),
            main_scan=main_scan,
            main_key_name=main_name,
            modifier_to_main_ms=max(0, mod_to_main),
            main_hold_ms=max(0, main_hold),
            overlap_ms=max(0, overlap),
            total_ms=max(0, total),
            release_order=release_order,
            t_ns=int(earliest_mod_t),
            timestamp=wall_clock_iso(),
        ))

        # Reset shortcut tracking
        self._shortcut_main_scan = None
        self._shortcut_main_t_ns = 0
        self._shortcut_main_name = ""
        self._shortcut_main_release_t_ns = None

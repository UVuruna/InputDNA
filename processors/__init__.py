"""
Event processor — central dispatcher.

Runs in a dedicated thread. Consumes raw events from the shared
event queue and routes them to the appropriate sub-processor.
Completed records are pushed to the database writer queue.

Also maintains in-memory stats counters (total + time-windowed)
for the dashboard display. No database reads — all stats from RAM.
"""

import ctypes
import json
import queue
import threading
import logging

from models.events import (
    RawMouseMove, RawMouseClick, RawMouseScroll,
    RawKeyPress, RawKeyRelease,
)
from models.sessions import (
    MovementSession, ClickSequence, DragRecord, ScrollEvent,
    KeystrokeRecord, KeyTransitionRecord, ShortcutRecord,
)
from processors.mouse_session import MouseSessionDetector
from processors.click_processor import ClickProcessor
from processors.drag_detector import DragDetector
from processors.keyboard_processor import (
    KeyboardProcessor,
    MODIFIER_SCANS, NUMPAD_SCANS, CODE_SCANS,
    LETTER_SCANS, NUMBER_ROW_SCANS, WHITESPACE_SCANS, CAPSLOCK_SCAN,
)
from database.writer import DatabaseWriter
from utils.timing import now_ns, wall_clock_iso
from utils.stats_tracker import StatsTracker

logger = logging.getLogger(__name__)

# All tracked counter names
_COUNTER_NAMES = [
    # Mouse
    "movements", "clicks",
    "left_clicks", "right_clicks", "middle_clicks",
    "double_clicks", "triple_clicks", "spam_clicks",
    "drags", "scrolls",
    # Keyboard
    "keystrokes",
    "upper_keys", "lower_keys", "code_keys",
    "number_keys", "numpad_keys", "other_keys",
    "shortcuts", "words",
]


class EventProcessor:
    """
    Central event dispatcher. Consumes raw events and produces DB records.

    Usage:
        proc = EventProcessor(event_queue, db_writer, session_id)
        proc.start()
        ...
        proc.stop()
    """

    def __init__(self, event_queue: queue.Queue, db_writer: DatabaseWriter,
                 recording_session_id: int = 0):
        self._event_queue = event_queue
        self._db = db_writer
        self._running = False
        self._thread: threading.Thread | None = None

        # Sub-processors
        self._mouse_session = MouseSessionDetector(
            on_session_complete=self._on_movement,
            recording_session_id=recording_session_id,
        )
        self._click_proc = ClickProcessor(
            on_sequence_complete=self._on_click_sequence,
        )
        self._drag_det = DragDetector(
            on_drag_complete=self._on_drag,
        )
        self._kb_proc = KeyboardProcessor(
            on_keystroke=self._on_keystroke,
            on_transition=self._on_transition,
            on_shortcut=self._on_shortcut,
        )

        # Stats tracker (total + windowed counters)
        self.stats = StatsTracker(_COUNTER_NAMES)

        # CapsLock state for upper/lower classification.
        # Query OS for initial state (called from main thread before start).
        try:
            self._caps_lock: bool = bool(
                ctypes.windll.user32.GetKeyState(0x14) & 1
            )
        except (AttributeError, OSError):
            self._caps_lock = False

        # Word counting state: True when last non-modifier keystroke was text
        self._last_was_text: bool = False

        # Last event timestamp for idle detection (cosmetic tray icon)
        self._last_event_ns: int = 0

    def start(self):
        """Start processor thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, name="processor", daemon=True)
        self._thread.start()
        logger.info("Event processor started")

    def stop(self):
        """Stop processor, flush pending sessions."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        # Flush any in-progress sessions
        self._mouse_session.flush()
        self._click_proc.flush()
        t = self.stats.get_totals()
        logger.info(
            f"Event processor stopped. "
            f"Movements: {t['movements']}, "
            f"Clicks: {t['clicks']}, "
            f"Keystrokes: {t['keystrokes']}"
        )

    def _run(self):
        """Main processing loop."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.05)
                self._dispatch(event)
            except queue.Empty:
                pass

            # Check timeouts
            t = now_ns()
            self._mouse_session.check_idle_timeout(t)
            self._click_proc.check_sequence_timeout(t)

    @property
    def last_event_ns(self) -> int:
        """Timestamp of the most recent event (for idle detection)."""
        return self._last_event_ns

    def _dispatch(self, event):
        """Route raw event to appropriate sub-processor."""
        self._last_event_ns = event.t_ns

        if isinstance(event, RawMouseMove):
            # Check drag first — if dragging, don't feed to session detector
            was_dragging = self._drag_det.is_dragging
            if self._drag_det.process_move(event):
                if not was_dragging:
                    # Drag just confirmed — end any active movement session
                    self._mouse_session.end_for_drag()
                return  # Move consumed by drag
            self._mouse_session.process_move(event)

        elif isinstance(event, RawMouseClick):
            self._drag_det.process_click(event)
            if not self._drag_det.is_dragging:
                self._mouse_session.process_click(event)
                self._click_proc.process_click(event)

        elif isinstance(event, RawMouseScroll):
            self._mouse_session.process_scroll(event)
            self.stats.increment("scrolls")
            # Also record individual scroll event
            direction = "up" if event.dy > 0 else "down" if event.dy < 0 else \
                        "right" if event.dx > 0 else "left"
            self._db.put(ScrollEvent(
                movement_id=self._mouse_session.last_completed_movement_id,
                direction=direction,
                delta=event.dy if event.dy != 0 else event.dx,
                x=event.x,
                y=event.y,
                t_ns=event.t_ns,
                timestamp=wall_clock_iso(),
            ))

        elif isinstance(event, RawKeyPress):
            self._kb_proc.process_press(event)

        elif isinstance(event, RawKeyRelease):
            self._kb_proc.process_release(event)

    # ── Callbacks from sub-processors ──────────────────────

    def _on_movement(self, session: MovementSession):
        self.stats.increment("movements")
        self._db.put(session)

    def _on_click_sequence(self, seq: ClickSequence):
        s = self.stats
        s.increment("clicks", seq.click_count)

        # Button breakdown
        button_key = f"{seq.button}_clicks"
        if button_key in s._totals:
            s.increment(button_key, seq.click_count)

        # Sequence type breakdown
        if seq.click_count == 2:
            s.increment("double_clicks")
        elif seq.click_count == 3:
            s.increment("triple_clicks")
        elif seq.click_count > 3:
            s.increment("spam_clicks")

        seq.movement_id = self._mouse_session.last_completed_movement_id
        self._db.put(seq)

    def _on_drag(self, drag: DragRecord):
        self.stats.increment("drags")
        self._db.put(drag)

    def _on_keystroke(self, rec: KeystrokeRecord):
        scan = rec.scan_code

        # Skip modifier keys from keystroke count and classification
        if scan in MODIFIER_SCANS:
            self._db.put(rec)
            return

        self.stats.increment("keystrokes")

        # Classify keystroke
        category = self._classify_keystroke(rec)
        self.stats.increment(category)

        # Word counting: text → whitespace = word completed
        is_whitespace = scan in WHITESPACE_SCANS
        if is_whitespace and self._last_was_text:
            self.stats.increment("words")
        self._last_was_text = not is_whitespace

        # Track CapsLock toggle
        if scan == CAPSLOCK_SCAN:
            self._caps_lock = not self._caps_lock

        self._db.put(rec)

    def _classify_keystroke(self, rec: KeystrokeRecord) -> str:
        """Classify a non-modifier keystroke into a stats category."""
        scan = rec.scan_code
        modifier_state = json.loads(rec.modifier_state)

        # Shortcut: Ctrl/Alt/Win held
        if any(modifier_state.get(m) for m in ("ctrl", "alt", "win")):
            return "other_keys"  # Shortcut keystrokes go to Other

        # Numpad
        if scan in NUMPAD_SCANS:
            return "numpad_keys"

        # Number row
        if scan in NUMBER_ROW_SCANS:
            return "number_keys"

        # Letter keys — upper vs lower
        if scan in LETTER_SCANS:
            shift_held = modifier_state.get("shift", False)
            is_upper = shift_held ^ self._caps_lock
            return "upper_keys" if is_upper else "lower_keys"

        # Code punctuation
        if scan in CODE_SCANS:
            return "code_keys"

        # Everything else (space, enter, backspace, arrows, F-keys, etc.)
        return "other_keys"

    def _on_transition(self, rec: KeyTransitionRecord):
        self._db.put(rec)

    def _on_shortcut(self, rec: ShortcutRecord):
        self.stats.increment("shortcuts")
        self._db.put(rec)

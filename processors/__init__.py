"""
Event processor — central dispatcher.

Runs in a dedicated thread. Consumes raw events from the shared
event queue and routes them to the appropriate sub-processor.
Completed records are pushed to the database writer queue.
"""

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
from processors.keyboard_processor import KeyboardProcessor
from database.writer import DatabaseWriter
from utils.timing import now_ns, wall_clock_iso

logger = logging.getLogger(__name__)


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

        # Counters
        self.movement_count = 0
        self.click_count = 0
        self.keystroke_count = 0

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
        logger.info(
            f"Event processor stopped. "
            f"Movements: {self.movement_count}, "
            f"Clicks: {self.click_count}, "
            f"Keystrokes: {self.keystroke_count}"
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
        self.movement_count += 1
        self._db.put(session)

    def _on_click_sequence(self, seq: ClickSequence):
        self.click_count += seq.click_count
        seq.movement_id = self._mouse_session.last_completed_movement_id
        self._db.put(seq)

    def _on_drag(self, drag: DragRecord):
        self._db.put(drag)

    def _on_keystroke(self, rec: KeystrokeRecord):
        self.keystroke_count += 1
        self._db.put(rec)

    def _on_transition(self, rec: KeyTransitionRecord):
        self._db.put(rec)

    def _on_shortcut(self, rec: ShortcutRecord):
        self._db.put(rec)

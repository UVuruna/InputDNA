"""
Mouse event listener.

Hooks into OS-level mouse events via pynput and pushes raw events
to a shared queue. Runs in a dedicated daemon thread.

Captures: move, click (press/release), scroll.
All timestamps: perf_counter_ns (sub-microsecond, monotonic).
"""

import queue
import logging
from pynput import mouse

from models.events import RawMouseMove, RawMouseClick, RawMouseScroll
from utils.timing import now_ns

logger = logging.getLogger(__name__)

# Map pynput button enum to string
_BUTTON_MAP = {
    mouse.Button.left: "left",
    mouse.Button.right: "right",
    mouse.Button.middle: "middle",
}


class MouseListener:
    """
    Captures mouse events and pushes them to a shared queue.

    Usage:
        q = queue.Queue()
        ml = MouseListener(q)
        ml.start()
        ...
        ml.stop()
    """

    def __init__(self, event_queue: queue.Queue):
        self._queue = event_queue
        self._listener: mouse.Listener | None = None

    def start(self):
        """Start listening for mouse events in a background thread."""
        self._listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Mouse listener started")

    def stop(self):
        """Stop listening."""
        if self._listener is not None:
            self._listener.stop()
            logger.info("Mouse listener stopped")

    def _on_move(self, x: int, y: int):
        self._queue.put(RawMouseMove(x=int(x), y=int(y), t_ns=now_ns()))

    def _on_click(self, x: int, y: int, button, pressed: bool):
        btn = _BUTTON_MAP.get(button)
        if btn is None:
            return  # Unknown button (e.g. side buttons), skip
        self._queue.put(RawMouseClick(
            x=int(x), y=int(y), button=btn, pressed=pressed, t_ns=now_ns()
        ))

    def _on_scroll(self, x: int, y: int, dx: int, dy: int):
        self._queue.put(RawMouseScroll(
            x=int(x), y=int(y), dx=dx, dy=dy, t_ns=now_ns()
        ))

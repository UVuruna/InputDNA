"""
Drag operation detector.

Detects click-hold-move-release patterns. If the mouse moves more
than DRAG_MIN_DISTANCE_PX while a button is held, it's a drag
(not a click).

When a drag is detected, path points are captured separately from
regular movement sessions.
"""

import math
import logging
from typing import Optional, Callable

from models.events import RawMouseMove, RawMouseClick
from models.sessions import DragRecord, PathPoint
from utils.timing import ns_to_ms, wall_clock_iso
import config

logger = logging.getLogger(__name__)


class DragDetector:
    """
    Detects and records drag operations.

    Call process_click() on mouse down/up and process_move() on moves.
    When a drag completes, calls on_drag_complete callback.
    """

    def __init__(self, on_drag_complete: Callable[[DragRecord], None]):
        self._on_complete = on_drag_complete

        # State
        self._button_down: Optional[str] = None
        self._down_x: int = 0
        self._down_y: int = 0
        self._down_t_ns: int = 0
        self._is_dragging = False
        self._drag_points: list[PathPoint] = []

    @property
    def is_dragging(self) -> bool:
        """Whether a drag operation is currently in progress."""
        return self._is_dragging

    @property
    def button_held(self) -> Optional[str]:
        """Which button is currently held, if any."""
        return self._button_down

    def process_click(self, event: RawMouseClick):
        """Process mouse down/up for drag detection."""
        if event.pressed:
            self._button_down = event.button
            self._down_x = event.x
            self._down_y = event.y
            self._down_t_ns = event.t_ns
            self._is_dragging = False
            self._drag_points = [PathPoint(event.x, event.y, event.t_ns)]
        else:
            if self._is_dragging and event.button == self._button_down:
                self._end_drag(event)
            self._button_down = None
            self._is_dragging = False
            self._drag_points = []

    def process_move(self, event: RawMouseMove) -> bool:
        """
        Process mouse move during potential drag.

        Returns True if this move is part of a drag (so the session
        detector should NOT include it in a regular movement session).
        """
        if self._button_down is None:
            return False

        self._drag_points.append(PathPoint(event.x, event.y, event.t_ns))

        if not self._is_dragging:
            # Check if we've moved far enough to confirm drag
            dx = event.x - self._down_x
            dy = event.y - self._down_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist >= config.DRAG_MIN_DISTANCE_PX:
                self._is_dragging = True
                logger.debug(f"Drag detected: {self._button_down} button")

        return self._is_dragging

    def _end_drag(self, release_event: RawMouseClick):
        """Finalize drag and emit record."""
        if len(self._drag_points) < 2:
            return

        points = self._drag_points
        start = points[0]
        end = points[-1]
        duration = ns_to_ms(release_event.t_ns - self._down_t_ns)

        record = DragRecord(
            button=self._button_down,
            start_x=start.x,
            start_y=start.y,
            end_x=end.x,
            end_y=end.y,
            duration_ms=duration,
            path_points=points,
            timestamp=wall_clock_iso(),
        )

        self._on_complete(record)

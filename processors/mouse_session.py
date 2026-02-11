"""
Mouse movement session detector.

Groups consecutive mouse moves into sessions. A session starts when
the mouse first moves after idle, and ends on click, scroll, or
idle timeout.

State machine:
    IDLE → (mouse move) → MOVING
    MOVING → (mouse move) → MOVING (add point)
    MOVING → (click/scroll) → end session, → IDLE
    MOVING → (idle timeout) → end session, → IDLE
"""

import math
import logging
from typing import Optional, Callable
from datetime import datetime

from models.events import RawMouseMove, RawMouseClick, RawMouseScroll
from models.sessions import MovementSession, PathPoint
from utils.timing import ns_to_ms, interval_ms
import config

logger = logging.getLogger(__name__)


class MouseSessionDetector:
    """
    Detects and builds mouse movement sessions from raw events.

    Call process_move/process_click/process_scroll as events arrive.
    When a session completes, calls on_session_complete callback.
    """

    def __init__(self, on_session_complete: Callable[[MovementSession], None],
                 recording_session_id: int = 0):
        self._on_complete = on_session_complete
        self._recording_session_id = recording_session_id

        # Current session state
        self._points: list[PathPoint] = []
        self._active = False
        self._last_move_t_ns: int = 0
        self._last_completed_movement_id: Optional[int] = None

    @property
    def is_active(self) -> bool:
        """Whether a movement session is currently in progress."""
        return self._active

    @property
    def last_move_t_ns(self) -> int:
        """Timestamp of last mouse move (for idle timeout checking)."""
        return self._last_move_t_ns

    def process_move(self, event: RawMouseMove):
        """Process a mouse move event."""
        if not self._active:
            # Start new session
            self._active = True
            self._points = [PathPoint(event.x, event.y, event.t_ns)]
        else:
            self._points.append(PathPoint(event.x, event.y, event.t_ns))

        self._last_move_t_ns = event.t_ns

    def process_click(self, event: RawMouseClick):
        """
        A click occurred. If we're in a session, end it.
        Only triggers on mouse-down (pressed=True).
        """
        if not event.pressed:
            return  # We only care about mouse-down for ending sessions

        if self._active and self._points:
            end_event = f"{event.button}_click"
            self._end_session(end_event)

    def process_scroll(self, event: RawMouseScroll):
        """A scroll occurred. If we're in a session, end it."""
        if self._active and self._points:
            direction = "up" if event.dy > 0 else "down" if event.dy < 0 else \
                        "right" if event.dx > 0 else "left"
            self._end_session(f"scroll_{direction}")

    def check_idle_timeout(self, current_t_ns: int):
        """
        Check if the current session should end due to idle timeout.
        Call this periodically from the processor loop.
        """
        if not self._active or not self._points:
            return

        elapsed = interval_ms(self._last_move_t_ns, current_t_ns)
        if elapsed >= config.SESSION_END_TIMEOUT_MS:
            self._end_session("idle")

    def flush(self):
        """Force-end current session (e.g., on shutdown)."""
        if self._active and self._points:
            self._end_session("flush")

    def _end_session(self, end_event: str):
        """Finalize current session and emit it."""
        points = self._points
        self._points = []
        self._active = False

        if len(points) < 2:
            return  # Need at least 2 points for a session

        start = points[0]
        end = points[-1]

        # Euclidean distance
        dx = end.x - start.x
        dy = end.y - start.y
        distance = math.sqrt(dx * dx + dy * dy)

        # Filter micro-sessions
        if distance < config.MIN_SESSION_DISTANCE_PX:
            return

        # Path length (sum of segments)
        path_len = 0.0
        for i in range(1, len(points)):
            sdx = points[i].x - points[i - 1].x
            sdy = points[i].y - points[i - 1].y
            path_len += math.sqrt(sdx * sdx + sdy * sdy)

        duration = ns_to_ms(end.t_ns - start.t_ns)
        now = datetime.now()

        session = MovementSession(
            start_x=start.x,
            start_y=start.y,
            end_x=end.x,
            end_y=end.y,
            end_event=end_event,
            duration_ms=duration,
            distance_px=distance,
            path_length_px=path_len,
            point_count=len(points),
            path_points=points,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            recording_session_id=self._recording_session_id,
            timestamp=now.isoformat(),
        )

        self._on_complete(session)

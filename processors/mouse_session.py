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

from models.events import RawMouseMove, RawMouseClick, RawMouseScroll
from models.sessions import MovementSession, PathPoint
from utils.timing import interval_ms
import config

logger = logging.getLogger(__name__)


class MouseSessionDetector:
    """
    Detects and builds mouse movement sessions from raw events.

    Call process_move/process_click/process_scroll as events arrive.
    When a session completes, calls on_session_complete callback.

    Movement IDs are app-generated: session_num * 1_000_000 + seq.
    """

    def __init__(self, on_session_complete: Callable[[MovementSession], None],
                 recording_session_id: int = 0):
        self._on_complete = on_session_complete
        self._recording_session_id = recording_session_id

        # Movement ID generation: session * 1_000_000 + seq
        self._session_num = recording_session_id
        self._movement_seq = 0

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

    @property
    def last_completed_movement_id(self) -> Optional[int]:
        """ID of the most recently completed movement session."""
        return self._last_completed_movement_id

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

    def end_for_drag(self):
        """End current session because a drag operation began."""
        if self._active and self._points:
            self._end_session("drag")

    def flush(self):
        """Force-end current session (e.g., on shutdown)."""
        if self._active and self._points:
            self._end_session("recording_stopped")

    def _end_session(self, end_event: str):
        """Finalize current session and emit it."""
        points = self._points
        self._points = []
        self._active = False

        if len(points) < 2:
            return  # Need at least 2 points for a session

        start = points[0]
        end = points[-1]

        # Euclidean distance — used only for minimum distance filter
        dx = end.x - start.x
        dy = end.y - start.y
        distance = math.sqrt(dx * dx + dy * dy)

        # Filter micro-sessions
        if distance < config.MIN_SESSION_DISTANCE_PX:
            return

        # Downsample path points if configured
        stored_points = self._downsample(points)

        # Generate app-controlled movement ID: session * 1_000_000 + seq
        self._movement_seq += 1
        movement_id = self._session_num * 1_000_000 + self._movement_seq

        session = MovementSession(
            movement_id=movement_id,
            start_x=start.x,
            start_y=start.y,
            end_x=end.x,
            end_y=end.y,
            end_event=end_event,
            start_t_ns=start.t_ns,
            end_t_ns=end.t_ns,
            path_points=stored_points,
        )

        self._last_completed_movement_id = movement_id
        self._on_complete(session)

    @staticmethod
    def _downsample(points: list[PathPoint]) -> list[PathPoint]:
        """
        Reduce path points to target sampling rate.

        Keeps first and last point always. Intermediate points are kept
        only if enough time has passed since the last kept point.
        Returns original list if downsampling is disabled (DOWNSAMPLE_HZ=0).
        """
        if config.DOWNSAMPLE_HZ == 0 or len(points) <= 2:
            return points

        # Minimum nanoseconds between stored points
        min_interval_ns = 1_000_000_000 // config.DOWNSAMPLE_HZ

        sampled = [points[0]]
        last_kept_t = points[0].t_ns

        for p in points[1:-1]:
            if p.t_ns - last_kept_t >= min_interval_ns:
                sampled.append(p)
                last_kept_t = p.t_ns

        sampled.append(points[-1])
        return sampled

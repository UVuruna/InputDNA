"""
Click sequence processor.

Groups clicks into sequences: single (1), double (2), or spam (3+).
Clicks on the same button within CLICK_SEQUENCE_GAP_MS of each other
are part of the same sequence.

Tracks:
- Press duration per click (down → up)
- Inter-click delay within sequence
- Total sequence duration
"""

import logging
from typing import Optional, Callable

from models.events import RawMouseClick
from models.sessions import ClickSequence, SingleClick
from utils.timing import ns_to_ms, interval_ms, wall_clock_iso
import config

logger = logging.getLogger(__name__)


class ClickProcessor:
    """
    Builds click sequences from raw mouse click events.

    Call process_click() for every RawMouseClick (both press and release).
    When a sequence is finalized, calls on_sequence_complete callback.
    """

    def __init__(self, on_sequence_complete: Callable[[ClickSequence], None]):
        self._on_complete = on_sequence_complete

        # Current pending sequence
        self._pending_clicks: list[SingleClick] = []
        self._pending_button: Optional[str] = None
        self._last_click_up_t_ns: int = 0

        # Current click being built (down → up)
        self._current_down_t_ns: int = 0
        self._current_down_x: int = 0
        self._current_down_y: int = 0
        self._current_button: Optional[str] = None

    def process_click(self, event: RawMouseClick):
        """
        Process a mouse click event (press or release).

        Press: starts timing a click.
        Release: completes the click, adds to pending sequence.
        """
        if event.pressed:
            self._handle_down(event)
        else:
            self._handle_up(event)

    def check_sequence_timeout(self, current_t_ns: int):
        """
        Check if pending sequence should be finalized due to timeout.
        Call periodically from processor loop.
        """
        if not self._pending_clicks:
            return

        elapsed = interval_ms(self._last_click_up_t_ns, current_t_ns)
        if elapsed >= config.CLICK_SEQUENCE_GAP_MS:
            self._finalize_sequence()

    def flush(self):
        """Force-finalize any pending sequence (e.g., on shutdown)."""
        if self._pending_clicks:
            self._finalize_sequence()

    def _handle_down(self, event: RawMouseClick):
        """Mouse button pressed."""
        # If this is a different button than pending sequence, finalize first
        if self._pending_clicks and event.button != self._pending_button:
            self._finalize_sequence()

        self._current_down_t_ns = event.t_ns
        self._current_down_x = event.x
        self._current_down_y = event.y
        self._current_button = event.button

    def _handle_up(self, event: RawMouseClick):
        """Mouse button released — complete one click."""
        if self._current_button is None or self._current_button != event.button:
            return  # Orphaned release, skip

        press_duration = ns_to_ms(event.t_ns - self._current_down_t_ns)

        # Calculate delay since previous click in sequence
        delay = 0.0
        if self._pending_clicks and self._last_click_up_t_ns > 0:
            gap = interval_ms(self._last_click_up_t_ns, self._current_down_t_ns)
            if gap > config.CLICK_SEQUENCE_GAP_MS:
                # Too long since last click — finalize old sequence first
                self._finalize_sequence()
                delay = 0.0
            else:
                delay = gap

        click = SingleClick(
            x=self._current_down_x,
            y=self._current_down_y,
            press_duration_ms=press_duration,
            delay_since_prev_ms=delay,
            t_ns=self._current_down_t_ns,
        )

        self._pending_clicks.append(click)
        self._pending_button = event.button
        self._last_click_up_t_ns = event.t_ns
        self._current_button = None

    def _finalize_sequence(self):
        """Emit the pending click sequence."""
        if not self._pending_clicks:
            return

        clicks = self._pending_clicks
        first = clicks[0]
        last = clicks[-1]

        total_dur = ns_to_ms(last.t_ns - first.t_ns) + last.press_duration_ms

        seq = ClickSequence(
            button=self._pending_button,
            click_count=len(clicks),
            clicks=clicks,
            total_duration_ms=total_dur,
            movement_id=None,  # Set by processor if linked to a movement
            timestamp=wall_clock_iso(),
        )

        self._pending_clicks = []
        self._pending_button = None

        self._on_complete(seq)

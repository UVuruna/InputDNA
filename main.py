"""
Human Input Recorder — Entry Point

Orchestrates all components:
1. Init database
2. Start DB writer thread
3. Start mouse listener thread
4. Start keyboard listener thread
5. Start event processor thread
6. Register hotkey (Ctrl+Alt+R to pause/resume)
7. Run system tray icon (blocks main thread)
8. Graceful shutdown on quit

Thread architecture:
    Main thread ──── tray icon (blocks until quit)
    Thread 1: mouse listener (pynput hook)
    Thread 2: keyboard listener (pynput hook)
    Thread 3: event processor (dispatches events)
    Thread 4: database writer (batched inserts)
"""

import sys
import queue
import logging
from pathlib import Path

import config
from database.schema import init_db
from database.rotation import check_and_rotate
from database.writer import DatabaseWriter
from listeners.mouse_listener import MouseListener
from listeners.keyboard_listener import KeyboardListener
from processors import EventProcessor
from models.sessions import RecordingSessionRecord
from utils.timing import now_ns, wall_clock_iso
from utils.hotkeys import register_toggle_hotkey
from ui.tray_icon import TrayIcon

# ── Logging setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-18s] %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


class Recorder:
    """Main recorder application."""

    def __init__(self):
        self._event_queue: queue.Queue = queue.Queue()
        self._db_writer: DatabaseWriter | None = None
        self._mouse_listener: MouseListener | None = None
        self._kb_listener: KeyboardListener | None = None
        self._processor: EventProcessor | None = None
        self._recording_session: RecordingSessionRecord | None = None
        self._tray: TrayIcon | None = None
        self._session_id: int = 0
        self._paused = False

    def start(self):
        """Initialize and start all components."""
        logger.info("=" * 50)
        logger.info("Human Input Recorder starting...")
        logger.info("=" * 50)

        # 1. Init database (rotate if over size threshold)
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        check_and_rotate(config.DB_PATH)
        logger.info(f"Database: {config.DB_PATH}")
        conn = init_db(config.DB_PATH)

        # Create recording session
        self._recording_session = RecordingSessionRecord(
            started_at=wall_clock_iso(),
            perf_counter_start_ns=now_ns(),
        )
        self._session_id = self._recording_session.write_start(conn)
        conn.commit()
        conn.close()
        logger.info(f"Recording session #{self._session_id} started")

        # 2. Start DB writer
        self._db_writer = DatabaseWriter(config.DB_PATH)
        self._db_writer.start()

        # 3. Start listeners
        self._mouse_listener = MouseListener(self._event_queue)
        self._mouse_listener.start()

        self._kb_listener = KeyboardListener(self._event_queue)
        self._kb_listener.start()

        # 4. Start processor
        self._processor = EventProcessor(
            self._event_queue, self._db_writer,
            recording_session_id=self._session_id,
        )
        self._processor.start()

        # 5. Register hotkey
        register_toggle_hotkey(self._toggle_pause)

        logger.info("All components running. Press Ctrl+Alt+R to pause/resume.")
        logger.info("Press Ctrl+C to stop recording.\n")

    def run_blocking(self):
        """
        Block main thread with system tray icon.
        Tray icon provides Pause/Resume, Stats, and Quit controls.
        """
        self._tray = TrayIcon(
            on_toggle_pause=self._toggle_pause,
            on_quit=self.stop,
            get_stats=self._get_stats_text,
        )
        try:
            self._tray.run()  # Blocks until Quit
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self):
        """Graceful shutdown of all components."""
        logger.info("\nShutting down...")

        # Stop in reverse order
        if self._processor:
            self._processor.stop()

        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kb_listener:
            self._kb_listener.stop()

        if self._db_writer:
            self._db_writer.stop()

        # Update recording session with final counts
        if self._recording_session and self._processor:
            self._recording_session.ended_at = wall_clock_iso()
            self._recording_session.total_movements = self._processor.movement_count
            self._recording_session.total_clicks = self._processor.click_count
            self._recording_session.total_keystrokes = self._processor.keystroke_count

            import sqlite3
            conn = sqlite3.connect(str(config.DB_PATH))
            self._recording_session.write_end(conn)
            conn.commit()
            conn.close()

        logger.info("Recording session ended.")
        if self._processor:
            logger.info(
                f"  Movements: {self._processor.movement_count}\n"
                f"  Clicks:    {self._processor.click_count}\n"
                f"  Keystrokes:{self._processor.keystroke_count}\n"
                f"  DB writes: {self._db_writer.total_written if self._db_writer else 0}"
            )
        logger.info("Goodbye!")
        sys.exit(0)

    def _toggle_pause(self):
        """Toggle pause/resume for all listeners."""
        self._paused = not self._paused
        if self._paused:
            logger.info("⏸  Recording PAUSED (Ctrl+Alt+R to resume)")
            if self._mouse_listener:
                self._mouse_listener.pause()
            if self._kb_listener:
                self._kb_listener.pause()
        else:
            logger.info("▶  Recording RESUMED")
            if self._mouse_listener:
                self._mouse_listener.resume()
            if self._kb_listener:
                self._kb_listener.resume()
        # Update tray icon
        if self._tray:
            self._tray.set_paused(self._paused)

    def _get_stats_text(self) -> str:
        """Get current recording stats as text for tray notification."""
        if not self._processor:
            return "Not running"
        pending = self._db_writer.pending if self._db_writer else 0
        return (
            f"Movements: {self._processor.movement_count}\n"
            f"Clicks: {self._processor.click_count}\n"
            f"Keystrokes: {self._processor.keystroke_count}\n"
            f"DB queue: {pending}"
        )


def main():
    recorder = Recorder()
    recorder.start()
    recorder.run_blocking()


if __name__ == "__main__":
    main()

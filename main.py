"""
Human Input Recorder — Entry Point

GUI application flow:
1. Login / Register screen
2. Main Dashboard (Start Recording, Train, Validate, Settings, Export)
3. Recording runs in background threads while GUI stays responsive

Thread architecture (during recording):
    Main thread ──── Qt event loop (GUI)
    Thread 1: mouse listener (pynput hook)
    Thread 2: keyboard listener (pynput hook)
    Thread 3: event processor (dispatches events)
    Thread 4: database writer (batched inserts)
    Thread 5: tray icon (pystray, optional visual feedback)
"""

import sys
import queue
import logging
import threading

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon

import config
from database.schema import init_mouse_db, init_keyboard_db, init_session_db
from database.rotation import check_and_rotate
from database.writer import DatabaseWriter
from listeners.mouse_listener import MouseListener
from listeners.keyboard_listener import KeyboardListener
from processors import EventProcessor
from models.sessions import RecordingSessionRecord
from utils.timing import now_ns, wall_clock_iso
from utils.hotkeys import register_toggle_hotkey
from utils.system_monitor import SystemMonitor, PollingRateEstimator
from ui.tray_icon import TrayIcon
from gui.login_screen import LoginScreen
from gui.main_dashboard import MainDashboard
from gui.settings_screen import SettingsScreen
from gui.validation_screen import ValidationScreen
from gui.calibration_dialog import ClickCalibrationDialog
from gui.dpi_dialog import DpiMeasurementDialog
from gui.styles import DARK_STYLE
from gui.user_db import UserProfile
from gui.user_settings import load_settings
from gui.global_settings import load_globals

# ── Logging setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-18s] %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


class Recorder:
    """Background recording engine (no GUI, just threads)."""

    def __init__(self, profile: UserProfile):
        self._profile = profile
        self._user_folder = config.get_user_folder(
            profile.username, profile.surname, profile.date_of_birth,
        )
        self._mouse_db = self._user_folder / "mouse.db"
        self._keyboard_db = self._user_folder / "keyboard.db"
        self._session_db = self._user_folder / "session.db"
        self._event_queue: queue.Queue = queue.Queue()
        self._db_writer: DatabaseWriter | None = None
        self._mouse_listener: MouseListener | None = None
        self._kb_listener: KeyboardListener | None = None
        self._processor: EventProcessor | None = None
        self._recording_session: RecordingSessionRecord | None = None
        self._session_id: int = 0
        self._paused = False
        self._polling_estimator = PollingRateEstimator()

    def start(self):
        """Start all recording threads. Returns immediately."""
        logger.info("=" * 50)
        logger.info("Recording starting...")
        logger.info("=" * 50)

        # Ensure user folder exists
        self._user_folder.mkdir(parents=True, exist_ok=True)

        # Check rotation for all DBs
        check_and_rotate(self._mouse_db)
        check_and_rotate(self._keyboard_db)
        check_and_rotate(self._session_db)

        # Init all three databases
        logger.info(f"User folder: {self._user_folder}")
        init_mouse_db(self._mouse_db).close()
        init_keyboard_db(self._keyboard_db).close()
        session_conn = init_session_db(self._session_db)

        # Create recording session (in session.db)
        self._recording_session = RecordingSessionRecord(
            started_at=wall_clock_iso(),
            perf_counter_start_ns=now_ns(),
        )
        self._session_id = self._recording_session.write_start(session_conn)
        session_conn.commit()
        session_conn.close()
        logger.info(f"Recording session #{self._session_id} started")

        # Start DB writer (routes to 3 databases)
        self._db_writer = DatabaseWriter(
            self._mouse_db, self._keyboard_db, self._session_db,
        )
        self._db_writer.start()

        # Start listeners
        self._mouse_listener = MouseListener(self._event_queue)
        self._mouse_listener.start()

        self._kb_listener = KeyboardListener(self._event_queue)
        self._kb_listener.start()

        # Start processor
        self._processor = EventProcessor(
            self._event_queue, self._db_writer,
            recording_session_id=self._session_id,
            polling_estimator=self._polling_estimator,
        )
        self._processor.start()

        # Register hotkey
        register_toggle_hotkey(self.toggle_pause)

        logger.info("All recording threads running.")

    def stop(self):
        """Stop all recording threads. Returns after cleanup."""
        logger.info("Stopping recording...")

        if self._processor:
            self._processor.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kb_listener:
            self._kb_listener.stop()
        if self._db_writer:
            self._db_writer.stop()

        # Finalize recording session (in session.db)
        if self._recording_session and self._processor:
            self._recording_session.ended_at = wall_clock_iso()
            self._recording_session.total_movements = self._processor.movement_count
            self._recording_session.total_clicks = self._processor.click_count
            self._recording_session.total_keystrokes = self._processor.keystroke_count

            import sqlite3
            conn = sqlite3.connect(str(self._session_db))
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

    def toggle_pause(self):
        """Toggle pause/resume for all listeners."""
        self._paused = not self._paused
        if self._paused:
            logger.info("Recording PAUSED")
            if self._mouse_listener:
                self._mouse_listener.pause()
            if self._kb_listener:
                self._kb_listener.pause()
        else:
            logger.info("Recording RESUMED")
            if self._mouse_listener:
                self._mouse_listener.resume()
            if self._kb_listener:
                self._kb_listener.resume()

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def movement_count(self) -> int:
        return self._processor.movement_count if self._processor else 0

    @property
    def click_count(self) -> int:
        return self._processor.click_count if self._processor else 0

    @property
    def keystroke_count(self) -> int:
        return self._processor.keystroke_count if self._processor else 0

    @property
    def pending_writes(self) -> int:
        return self._db_writer.pending if self._db_writer else 0

    @property
    def estimated_polling_hz(self) -> int | None:
        return self._polling_estimator.estimated_hz


class MainWindow(QMainWindow):
    """Main application window — manages screen transitions and recorder."""

    # Screen indices in the stacked widget
    _LOGIN = 0
    _DASHBOARD = 1
    _SETTINGS = 2
    _VALIDATION = 3

    def __init__(self):
        super().__init__()
        self.setWindowTitle("InputDNA — Human Input Recorder")
        self.resize(900, 700)

        self._user: UserProfile | None = None
        self._recorder: Recorder | None = None
        self._tray: TrayIcon | None = None
        self._tray_thread: threading.Thread | None = None
        self._system_monitor: SystemMonitor | None = None

        # ── Stacked widget for screen navigation ──────────────
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Screen 0: Login
        self._login_screen = LoginScreen()
        self._login_screen.login_success.connect(self._on_login)
        self._stack.addWidget(self._login_screen)

        # Screens 1-3 are created after login (need user_id)
        self._dashboard: MainDashboard | None = None
        self._settings: SettingsScreen | None = None
        self._validation: ValidationScreen | None = None

        # Stats update timer (runs during recording)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)

        # Start on login screen
        self._stack.setCurrentIndex(self._LOGIN)

    # ── Login / Logout ─────────────────────────────────────────

    def _on_login(self, profile: UserProfile):
        """Called when user successfully logs in."""
        self._user = profile
        logger.info(f"User logged in: {profile.username} (id={profile.id})")

        # Apply per-user settings (DPI, downsampling, etc.)
        user_settings = load_settings(profile.id)
        if user_settings:
            config.apply_user_settings(user_settings)

        # Set active user folder in config (uses CUSTOM_USER_DATA_DIR if set)
        config.set_active_user(profile.username, profile.surname, profile.date_of_birth)

        # Create screens that need user context
        self._create_user_screens(profile)

        self._stack.setCurrentIndex(self._DASHBOARD)

    def _create_user_screens(self, profile: UserProfile):
        """Create/replace dashboard, settings, validation screens."""
        # Remove old screens if they exist (re-login after logout)
        while self._stack.count() > 1:
            w = self._stack.widget(1)
            self._stack.removeWidget(w)
            w.deleteLater()

        # Screen 1: Dashboard
        self._dashboard = MainDashboard(profile)
        self._dashboard.start_recording_signal.connect(self._start_recording)
        self._dashboard.stop_recording_signal.connect(self._stop_recording)
        self._dashboard.settings_signal.connect(self._show_settings)
        self._dashboard.validate_model_signal.connect(self._show_validation)
        self._dashboard.logout_signal.connect(self._on_logout)
        self._stack.addWidget(self._dashboard)

        # Screen 2: Settings
        self._settings = SettingsScreen(profile.id)
        self._settings.back_signal.connect(self._show_dashboard)
        self._settings.calibrate_click_signal.connect(self._open_click_calibration)
        self._settings.calibrate_dpi_signal.connect(self._open_dpi_calibration)
        self._stack.addWidget(self._settings)

        # Screen 3: Validation
        self._validation = ValidationScreen()
        self._validation.back_signal.connect(self._show_dashboard)
        self._stack.addWidget(self._validation)

    def _on_logout(self):
        """Stop recording if active, reset config, go back to login."""
        if self._recorder:
            self._stop_recording()

        config.reset_to_defaults()
        config.clear_active_user()
        self._user = None
        logger.info("User logged out")

        self._stack.setCurrentIndex(self._LOGIN)

    # ── Screen navigation ──────────────────────────────────────

    def _show_dashboard(self):
        self._stack.setCurrentIndex(self._DASHBOARD)

    def _show_settings(self):
        self._stack.setCurrentIndex(self._SETTINGS)

    def _show_validation(self):
        self._stack.setCurrentIndex(self._VALIDATION)

    # ── Recording control ──────────────────────────────────────

    def _start_recording(self):
        """Create recorder for current user and start background threads."""
        if self._recorder or not self._user:
            return

        self._recorder = Recorder(self._user)
        self._recorder.start()

        # Start tray icon in background thread
        self._start_tray()

        # Start stats update timer
        self._stats_timer.start(1000)

        # Start system monitor
        self._start_system_monitor()

        logger.info("Recording started from dashboard")

    def _stop_recording(self):
        """Stop recorder and tray icon."""
        if not self._recorder:
            return

        self._stats_timer.stop()
        self._stop_system_monitor()
        self._stop_tray()

        self._recorder.stop()
        self._recorder = None

        logger.info("Recording stopped from dashboard")

    def _update_stats(self):
        """Update dashboard stats and system info from recorder (runs on timer)."""
        if self._recorder and self._dashboard:
            self._dashboard.update_stats(
                self._recorder.movement_count,
                self._recorder.click_count,
                self._recorder.keystroke_count,
            )
            # Update system info periodically
            if self._system_monitor:
                self._dashboard.update_system_info(
                    self._system_monitor.current_state,
                    self._recorder.estimated_polling_hz,
                )

    # ── Tray icon ──────────────────────────────────────────────

    def _start_tray(self):
        """Start system tray icon in a background thread."""
        self._tray = TrayIcon(
            on_toggle_pause=self._tray_toggle_pause,
            on_quit=self._tray_quit,
            get_stats=self._get_stats_text,
        )
        self._tray_thread = threading.Thread(
            target=self._tray.run,
            name="tray-icon",
            daemon=True,
        )
        self._tray_thread.start()

    def _stop_tray(self):
        """Stop the tray icon."""
        if self._tray:
            self._tray.stop()
            self._tray = None
            self._tray_thread = None

    def _tray_toggle_pause(self):
        """Called from tray icon thread — toggle recording pause."""
        if self._recorder:
            self._recorder.toggle_pause()
            if self._tray:
                self._tray.set_paused(self._recorder.paused)

    def _tray_quit(self):
        """Called from tray icon thread — stop recording via tray."""
        # Schedule stop on the main Qt thread
        QTimer.singleShot(0, self._stop_recording_from_tray)

    def _stop_recording_from_tray(self):
        """Stop recording and update dashboard (runs on Qt thread)."""
        if self._recorder and self._dashboard:
            self._dashboard.stop_recording_signal.emit()

    def _get_stats_text(self) -> str:
        if not self._recorder:
            return "Not recording"
        return (
            f"Movements: {self._recorder.movement_count}\n"
            f"Clicks: {self._recorder.click_count}\n"
            f"Keystrokes: {self._recorder.keystroke_count}\n"
            f"DB queue: {self._recorder.pending_writes}"
        )

    # ── System monitor ─────────────────────────────────────────

    def _start_system_monitor(self):
        """Start monitoring system state (mouse speed, resolution, etc.)."""
        if not self._recorder or not self._recorder._db_writer:
            return
        self._system_monitor = SystemMonitor(
            on_event=self._recorder._db_writer.put,
        )
        self._system_monitor.start()

        # Update dashboard with initial state
        if self._dashboard:
            self._dashboard.update_system_info(self._system_monitor.current_state)

    def _stop_system_monitor(self):
        if self._system_monitor:
            self._system_monitor.stop()
            self._system_monitor = None

    # ── Calibration dialogs ────────────────────────────────────

    def _open_click_calibration(self):
        if not self._user:
            return
        dialog = ClickCalibrationDialog(self._user.id, self)
        if dialog.exec():
            gap_ms = dialog.result_ms
            if gap_ms and self._settings:
                self._settings.set_click_gap_value(gap_ms)

    def _open_dpi_calibration(self):
        if not self._user:
            return
        dialog = DpiMeasurementDialog(self._user.id, self)
        if dialog.exec():
            dpi = dialog.result_dpi
            if dpi and self._settings:
                self._settings.set_dpi_value(dpi)

    # ── Window close ───────────────────────────────────────────

    def closeEvent(self, event):
        """Smart close: navigate back on secondary screens, exit on login/dashboard."""
        current = self._stack.currentIndex()
        if current in (self._SETTINGS, self._VALIDATION):
            self._show_dashboard()
            event.ignore()
            return

        if self._recorder:
            self._stop_recording()
        event.accept()


def _apply_global_settings():
    """Load global settings from profiles.db and apply to config module."""
    settings = load_globals()
    data_dir = settings.get("storage.data_dir", "")
    config.CUSTOM_USER_DATA_DIR = data_dir
    config.START_WITH_WINDOWS = settings.get(
        "system.start_with_windows", ""
    ).lower() == "true"


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    # Load global settings (data location, autostart) before anything else
    _apply_global_settings()

    # Set application icon (title bar + taskbar)
    icon_path = Path(__file__).parent / "setup" / "InputDNA.ico"
    if getattr(sys, 'frozen', False):
        icon_path = Path(sys._MEIPASS) / "InputDNA.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

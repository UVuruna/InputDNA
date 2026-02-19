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
    Thread 5: tray icon (pystray, always visible while app runs)

Autostart mode (--autostart flag):
    When launched with Windows startup and a default user is configured,
    the app auto-logs in, starts recording, and stays in the system tray
    without showing the GUI window.
"""

import ctypes
import ctypes.wintypes
import sys
import queue
import logging
import threading

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtCore import QTimer, Signal
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
from utils.system_monitor import (
    SystemMonitor, get_all_state, start_polling_estimation,
)
from ui.tray_icon import TrayIcon, detect_windows_theme
from gui.login_screen import LoginScreen
from gui.main_dashboard import MainDashboard
from gui.settings_screen import SettingsScreen
from gui.validation_screen import ValidationScreen
from gui.readme_viewer import open_docs
from gui.calibration_dialog import ClickCalibrationDialog
from gui.dpi_dialog import DpiMeasurementDialog
from gui.styles import get_stylesheet
from gui.user_db import UserProfile, login as db_login
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
        )
        self._processor.start()

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
            t = self._processor.stats.get_totals()
            self._recording_session.ended_at = wall_clock_iso()
            self._recording_session.total_movements = t["movements"]
            self._recording_session.total_clicks = t["clicks"]
            self._recording_session.total_keystrokes = t["keystrokes"]

            import sqlite3
            conn = sqlite3.connect(str(self._session_db))
            self._recording_session.write_end(conn)
            conn.commit()
            conn.close()

        logger.info("Recording session ended.")
        if self._processor:
            t = self._processor.stats.get_totals()
            logger.info(
                f"  Movements: {t['movements']}\n"
                f"  Clicks:    {t['clicks']}\n"
                f"  Keystrokes:{t['keystrokes']}\n"
                f"  DB writes: {self._db_writer.total_written if self._db_writer else 0}"
            )

    @property
    def stats(self):
        """Access the processor's StatsTracker (or None if not recording)."""
        return self._processor.stats if self._processor else None

    @property
    def pending_writes(self) -> int:
        return self._db_writer.pending if self._db_writer else 0

    @property
    def last_event_ns(self) -> int:
        return self._processor.last_event_ns if self._processor else 0


class MainWindow(QMainWindow):
    """Main application window — manages screen transitions and recorder."""

    # Cross-thread signals (pystray and stop-worker run in their own threads)
    _sig_show_gui = Signal()
    _sig_stop_recording = Signal()
    _sig_force_close = Signal()
    _sig_recording_stopped = Signal()

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
        self._force_quit = False  # True when Quit from tray — bypass minimize
        self._system_shutting_down = False  # True on WM_QUERYENDSESSION

        # Connect cross-thread signals (pystray and stop-worker threads)
        self._sig_show_gui.connect(self._show_window)
        self._sig_stop_recording.connect(self._stop_recording_from_tray)
        self._sig_force_close.connect(self._force_close)
        self._sig_recording_stopped.connect(self._on_recording_stopped)

        # ── Stacked widget for screen navigation ──────────────
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Screen 0: Login
        self._login_screen = LoginScreen()
        self._login_screen.login_success.connect(self._on_login)
        self._login_screen.back_to_dashboard.connect(self._show_dashboard)
        self._login_screen.readme_signal.connect(self._show_readme)
        self._stack.addWidget(self._login_screen)

        # Screens 1-3 are created after login (need user_id)
        self._dashboard: MainDashboard | None = None
        self._settings: SettingsScreen | None = None
        self._validation: ValidationScreen | None = None

        # Stats update timer (runs during recording)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)

        # Polling rate check timer (runs after login until estimation completes)
        self._polling_check_timer = QTimer(self)
        self._polling_check_timer.timeout.connect(self._check_polling_rate)

        # Start tray icon immediately (always visible while app runs)
        self._start_tray()

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

        # Start polling rate estimation immediately (temporary mouse listener)
        self._polling_estimator = start_polling_estimation(
            on_done=self._on_polling_rate_estimated,
        )
        self._polling_check_timer.start(500)

        # Create screens that need user context
        self._create_user_screens(profile)

        # Populate system info immediately (before recording starts)
        self._dashboard.update_system_info(get_all_state())

        # Mark active user on login screen (for Home navigation)
        self._login_screen.set_active_user(profile)

        self._stack.setCurrentIndex(self._DASHBOARD)

    def _create_user_screens(self, profile: UserProfile):
        """Create/replace dashboard, settings, validation screens."""
        # Remove old screens if they exist (re-login after logout)
        # Keep login (0) — it's permanent
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
        self._dashboard.home_signal.connect(self._show_login)
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

    def _on_polling_rate_estimated(self, hz: int):
        """Called from estimator thread when polling rate is determined."""
        # Update dashboard from Qt thread
        QTimer.singleShot(0, lambda: self._apply_polling_rate(hz))

    def _apply_polling_rate(self, hz: int):
        """Apply estimated polling rate to dashboard (runs on Qt thread)."""
        self._polling_check_timer.stop()
        if self._dashboard:
            self._dashboard.update_system_info(get_all_state(), hz)

    def _check_polling_rate(self):
        """Periodic check until polling rate is estimated (before recording)."""
        hz = config.ESTIMATED_POLLING_HZ
        if hz is not None:
            self._polling_check_timer.stop()
            if self._dashboard:
                self._dashboard.update_system_info(get_all_state(), hz)

    def _on_logout(self):
        """Stop recording if active, reset tray to default, go back to login."""
        if self._recorder:
            self._stop_recording_sync()

        self._polling_check_timer.stop()

        # Reset tray to default icon (tray stays alive)
        if self._tray:
            self._tray.set_default()

        config.reset_to_defaults()
        config.ESTIMATED_POLLING_HZ = None
        config.clear_active_user()
        self._user = None
        logger.info("User logged out")

        # Clear login screen active user state
        self._login_screen.clear_active_user()
        self._login_screen._refresh_user_list()

        self._stack.setCurrentIndex(self._LOGIN)

    # ── Screen navigation ──────────────────────────────────────

    def _show_login(self):
        """Navigate to login screen (from Home button). Recording continues."""
        self._stack.setCurrentIndex(self._LOGIN)

    def _show_readme(self):
        """Open project documentation in the default browser."""
        open_docs(Path(__file__).parent)

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

        # Update tray icon to recording state
        if self._tray:
            self._tray.set_recording()

        # Start stats update timer
        self._stats_timer.start(1000)

        # Start system monitor
        self._start_system_monitor()

        logger.info("Recording started from dashboard")

    def _stop_recording(self):
        """Stop recording asynchronously — UI stays responsive."""
        if not self._recorder:
            return

        self._stats_timer.stop()

        # Capture references for background thread
        recorder = self._recorder
        monitor = self._system_monitor
        self._recorder = None
        self._system_monitor = None

        def _do_stop():
            if monitor:
                monitor.stop()
            recorder.stop()
            self._sig_recording_stopped.emit()

        threading.Thread(target=_do_stop, name="stop-worker", daemon=True).start()

    def _on_recording_stopped(self):
        """Called on Qt thread after async stop completes."""
        if self._tray:
            self._tray.set_stopped()
        if self._dashboard:
            self._dashboard.on_recording_stopped()
        self._login_screen.update_recording_status(False, False)
        logger.info("Recording stopped")

    def _stop_recording_sync(self):
        """Stop recording synchronously — for close/quit/logout paths."""
        if not self._recorder:
            return

        self._stats_timer.stop()
        if self._system_monitor:
            self._system_monitor.stop()
            self._system_monitor = None

        self._recorder.stop()
        self._recorder = None
        logger.info("Recording stopped (sync)")

    def _update_stats(self):
        """Update dashboard stats, system info, and tray/login idle state (runs on timer)."""
        if self._recorder and self._dashboard:
            stats = self._recorder.stats
            if stats:
                self._dashboard.update_stats(
                    stats.get_totals(),
                    stats.get_windowed(config.STATS_WINDOW_MINUTES),
                )
            # Update system info periodically
            if self._system_monitor:
                self._dashboard.update_system_info(
                    self._system_monitor.current_state,
                    config.ESTIMATED_POLLING_HZ,
                )

            # Idle detection — cosmetic tray icon + login screen status
            last_ns = self._recorder.last_event_ns
            idle_ns = config.IDLE_ICON_TIMEOUT_S * 1_000_000_000
            is_idle = bool(last_ns and (now_ns() - last_ns) > idle_ns)

            if self._tray:
                if is_idle:
                    self._tray.set_idle()
                else:
                    self._tray.set_recording()

            # Update login screen status (visible when user navigated Home)
            self._login_screen.update_recording_status(True, is_idle)

    # ── Tray icon ──────────────────────────────────────────────

    def _start_tray(self):
        """Start system tray icon in a background thread (always visible)."""
        if self._tray:
            return
        self._tray = TrayIcon(
            on_stop_recording=self._tray_stop_recording,
            on_quit=self._tray_quit_app,
            get_stats=self._get_stats_text,
            on_show_gui=self._tray_show_gui,
        )
        self._tray_thread = threading.Thread(
            target=self._tray.run,
            name="tray-icon",
            daemon=True,
        )
        self._tray_thread.start()

    def _stop_tray(self):
        """Remove the tray icon (only on actual app exit)."""
        if self._tray:
            self._tray.stop()
            self._tray = None
            self._tray_thread = None

    def _tray_show_gui(self):
        """Called from tray thread — emit signal to Qt thread."""
        self._sig_show_gui.emit()

    def _show_window(self):
        """Show and raise the window (runs on Qt thread)."""
        self.show()
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_stop_recording(self):
        """Called from tray thread — emit signal to Qt thread."""
        self._sig_stop_recording.emit()

    def _tray_quit_app(self):
        """Called from tray thread — emit signal to Qt thread."""
        self._sig_force_close.emit()

    def _force_close(self):
        """Force-close the app (from tray Quit), bypassing minimize-on-close."""
        self._force_quit = True
        self.close()

    def _stop_recording_from_tray(self):
        """Stop recording from tray — triggers dashboard UI update + async stop."""
        if self._recorder and self._dashboard:
            self._dashboard._stop_recording()

    def _get_stats_text(self) -> str:
        """Tray icon stats — basic summary only."""
        stats = self._recorder.stats if self._recorder else None
        if not stats:
            return "Not recording"
        t = stats.get_totals()
        return (
            f"Movements: {t['movements']}\n"
            f"Clicks: {t['clicks']}\n"
            f"Keystrokes: {t['keystrokes']}\n"
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

    def nativeEvent(self, eventType, message):
        """Detect Windows shutdown/logoff via WM_QUERYENDSESSION."""
        if eventType == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0011:  # WM_QUERYENDSESSION
                self._system_shutting_down = True
                logger.info("System shutdown detected (WM_QUERYENDSESSION)")
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event):
        """Close behavior: minimize-on-close hides to tray, otherwise exits."""
        # Tray Quit or system shutdown → always exit
        if self._force_quit or self._system_shutting_down:
            self._cleanup_and_quit(event)
            return

        # Minimize on close → hide window to tray
        if config.MINIMIZE_ON_CLOSE:
            self.hide()
            event.ignore()
            return

        # Default: navigate back from sub-screens, exit from login/dashboard
        current = self._stack.currentIndex()
        if current in (self._SETTINGS, self._VALIDATION):
            self._show_dashboard()
            event.ignore()
            return

        self._cleanup_and_quit(event)

    def _cleanup_and_quit(self, event):
        """Synchronous cleanup: stop recording, remove tray, exit app."""
        if self._recorder:
            self._stop_recording_sync()
        self._stop_tray()
        event.accept()
        # Explicit quit — needed when window was already hidden
        # (minimize-on-close), otherwise QApplication.exec() won't return
        QApplication.instance().quit()


def _apply_global_settings():
    """Load global settings from profiles.db and apply to config module."""
    settings = load_globals()
    config.CUSTOM_USER_DATA_DIR = settings.get("storage.data_dir", "")
    config.DEFAULT_USER = settings.get("startup.default_user", "")
    config.START_WITH_WINDOWS = settings.get(
        "system.start_with_windows", ""
    ).lower() == "true"
    config.MINIMIZE_ON_CLOSE = settings.get(
        "system.minimize_on_close", ""
    ).lower() == "true"

    # Apply theme
    theme = settings.get("appearance.theme", "dark")
    QApplication.instance().setStyleSheet(get_stylesheet(theme))


def main():
    app = QApplication(sys.argv)

    # Load global settings (theme, data location, autostart) before anything else
    _apply_global_settings()

    # Set application icon (title bar + taskbar) — theme-aware SVG
    theme = detect_windows_theme()
    if getattr(sys, 'frozen', False):
        svg_path = Path(sys._MEIPASS) / "logo" / theme / "UV-InputDNA.svg"
    else:
        svg_path = Path(__file__).parent / "support" / "logo" / theme / "UV-InputDNA.svg"
    if svg_path.exists():
        app.setWindowIcon(QIcon(str(svg_path)))
    else:
        # Fallback to ICO (e.g. SVG not bundled)
        ico_path = Path(__file__).parent / "setup" / "InputDNA.ico"
        if getattr(sys, 'frozen', False):
            ico_path = Path(sys._MEIPASS) / "InputDNA.ico"
        if ico_path.exists():
            app.setWindowIcon(QIcon(str(ico_path)))

    window = MainWindow()

    # Autostart mode: --autostart flag + default user configured
    autostart = "--autostart" in sys.argv and config.DEFAULT_USER
    if autostart:
        profile = db_login(config.DEFAULT_USER)
        if profile:
            logger.info(f"Autostart: logging in as {profile.username}")
            window._on_login(profile)
            # Trigger recording through dashboard (updates UI + starts recorder)
            window._dashboard._start_recording()
            # Stay in tray — don't show GUI window
        else:
            logger.warning(
                f"Autostart: default user '{config.DEFAULT_USER}' not found, "
                "showing login screen"
            )
            window.show()
    else:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

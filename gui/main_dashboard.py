"""
Main dashboard — shown after login.

Three primary actions:
1. Start/Stop Recording — toggles mouse+keyboard capture
2. Train Model — trains ML model from recorded data
3. Validate Model — tests model accuracy against real input

Shows current user info, recording stats, and model status.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QMessageBox, QProgressBar, QFileDialog,
)
from PySide6.QtCore import Signal, Qt, QTimer

import config
from gui.user_db import UserProfile
from gui.export_utils import export_all_user_data, get_user_db_files


class MainDashboard(QWidget):
    """Main control panel after login."""

    # Signals for main.py to connect recorder/trainer/validator
    start_recording_signal = Signal()
    stop_recording_signal = Signal()
    train_model_signal = Signal()
    validate_model_signal = Signal()
    settings_signal = Signal()
    logout_signal = Signal()
    home_signal = Signal()

    def __init__(self, user: UserProfile, parent=None):
        super().__init__(parent)
        self._user = user
        self._recording = False
        self._build_ui()

        # Stats update timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats_display)
        self._stats_timer.start(1000)  # Update every second

        # Stats data (updated externally via update_stats)
        self._totals: dict[str, int] = {}
        self._windowed: dict[str, int] = {}

        # Stats view mode: "total" or "windowed"
        self._stats_mode: str = "total"

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        # ── Header ─────────────────────────────────────────
        header = QHBoxLayout()

        home_btn = QPushButton("Home")
        home_btn.setToolTip("Go to login screen (recording continues)")
        home_btn.clicked.connect(self.home_signal.emit)
        header.addWidget(home_btn)

        title = QLabel("Human Input Simulator")
        title.setObjectName("title")
        header.addWidget(title)

        header.addStretch()

        user_label = QLabel(f"User: {self._user.username} ({self._user.surname})")
        user_label.setObjectName("subtitle")
        header.addWidget(user_label)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.settings_signal.emit)
        header.addWidget(settings_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.clicked.connect(self.logout_signal.emit)
        header.addWidget(logout_btn)

        layout.addLayout(header)

        # ── Status bar ────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setObjectName("status-bar")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(0)

        self._status_label = QLabel("Idle")
        self._status_label.setObjectName("status-text")
        status_layout.addWidget(self._status_label)

        status_layout.addStretch()

        self._started_label = QLabel("")
        self._started_label.setObjectName("status-detail")
        status_layout.addWidget(self._started_label)

        self._uptime_label = QLabel("")
        self._uptime_label.setObjectName("status-detail")
        self._uptime_label.setContentsMargins(20, 0, 0, 0)
        status_layout.addWidget(self._uptime_label)

        layout.addWidget(status_bar)

        # Recording start time (for uptime calculation)
        self._recording_started: datetime | None = None

        # ── Actions ────────────────────────────────────────
        actions_group = QGroupBox("Actions")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setSpacing(15)

        # Record button
        self._record_btn = QPushButton("Start Recording")
        self._record_btn.setObjectName("success")
        self._record_btn.setMinimumHeight(60)
        self._record_btn.clicked.connect(self._toggle_recording)
        actions_layout.addWidget(self._record_btn)

        # Train button
        self._train_btn = QPushButton("Train Model")
        self._train_btn.setObjectName("primary")
        self._train_btn.setMinimumHeight(60)
        self._train_btn.clicked.connect(self._on_train)
        actions_layout.addWidget(self._train_btn)

        # Validate button
        self._validate_btn = QPushButton("Validate Model")
        self._validate_btn.setMinimumHeight(60)
        self._validate_btn.clicked.connect(self._on_validate)
        actions_layout.addWidget(self._validate_btn)

        # Export button
        self._export_btn = QPushButton("Export Data")
        self._export_btn.setMinimumHeight(60)
        self._export_btn.clicked.connect(self._on_export)
        actions_layout.addWidget(self._export_btn)

        layout.addWidget(actions_group)

        # ── Stats Navigation (shared toggle) ──────────────
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)

        nav_layout.addStretch()

        self._nav_left_btn = QPushButton("\u25C0")
        self._nav_left_btn.setObjectName("stat-arrow")
        self._nav_left_btn.clicked.connect(self._toggle_stats_mode)
        nav_layout.addWidget(self._nav_left_btn)

        self._nav_label = QLabel("Total")
        self._nav_label.setObjectName("stat-nav")
        self._nav_label.setAlignment(Qt.AlignCenter)
        self._nav_label.setMinimumWidth(120)
        nav_layout.addWidget(self._nav_label)

        self._nav_right_btn = QPushButton("\u25B6")
        self._nav_right_btn.setObjectName("stat-arrow")
        self._nav_right_btn.clicked.connect(self._toggle_stats_mode)
        nav_layout.addWidget(self._nav_right_btn)

        nav_layout.addStretch()

        layout.addLayout(nav_layout)

        # ── Recording Stats (Mouse + Keyboard side by side) ──
        stats_row = QHBoxLayout()
        stats_row.setSpacing(15)

        # ── Mouse group ───────────────────────────────────
        mouse_group = QGroupBox("Mouse")
        mouse_layout = QGridLayout(mouse_group)
        mouse_layout.setSpacing(6)
        mouse_layout.setContentsMargins(12, 20, 12, 12)

        row = 0
        # Movements
        mouse_layout.addWidget(QLabel("Movements"), row, 0)
        self._movements_val = QLabel("0")
        self._movements_val.setObjectName("stat-value")
        self._movements_val.setAlignment(Qt.AlignRight)
        mouse_layout.addWidget(self._movements_val, row, 1, 1, 3)

        # Clicks
        row += 1
        mouse_layout.addWidget(QLabel("Clicks"), row, 0)
        self._clicks_val = QLabel("0")
        self._clicks_val.setObjectName("stat-value")
        self._clicks_val.setAlignment(Qt.AlignRight)
        mouse_layout.addWidget(self._clicks_val, row, 1, 1, 3)

        # Click breakdown: Left / Right / Middle
        row += 1
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(20, 0, 0, 0)
        for label, attr in [
            ("Left", "_left_clicks_val"),
            ("Right", "_right_clicks_val"),
            ("Middle", "_middle_clicks_val"),
        ]:
            sub = QVBoxLayout()
            sub.setSpacing(1)
            lbl = QLabel(label)
            lbl.setObjectName("stat-sub-label")
            lbl.setAlignment(Qt.AlignCenter)
            sub.addWidget(lbl)
            val = QLabel("0")
            val.setObjectName("stat-sub-value")
            val.setAlignment(Qt.AlignCenter)
            setattr(self, attr, val)
            sub.addWidget(val)
            sub_row.addLayout(sub)
        mouse_layout.addLayout(sub_row, row, 0, 1, 4)

        # Click sequences: Double / Triple / Spam
        row += 1
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(20, 0, 0, 0)
        for label, attr in [
            ("Double", "_double_clicks_val"),
            ("Triple", "_triple_clicks_val"),
            ("Spam", "_spam_clicks_val"),
        ]:
            sub = QVBoxLayout()
            sub.setSpacing(1)
            lbl = QLabel(label)
            lbl.setObjectName("stat-sub-label")
            lbl.setAlignment(Qt.AlignCenter)
            sub.addWidget(lbl)
            val = QLabel("0")
            val.setObjectName("stat-sub-value")
            val.setAlignment(Qt.AlignCenter)
            setattr(self, attr, val)
            sub.addWidget(val)
            sub_row.addLayout(sub)
        mouse_layout.addLayout(sub_row, row, 0, 1, 4)

        # Drags
        row += 1
        mouse_layout.addWidget(QLabel("Drags"), row, 0)
        self._drags_val = QLabel("0")
        self._drags_val.setObjectName("stat-value")
        self._drags_val.setAlignment(Qt.AlignRight)
        mouse_layout.addWidget(self._drags_val, row, 1, 1, 3)

        # Scrolls
        row += 1
        mouse_layout.addWidget(QLabel("Scrolls"), row, 0)
        self._scrolls_val = QLabel("0")
        self._scrolls_val.setObjectName("stat-value")
        self._scrolls_val.setAlignment(Qt.AlignRight)
        mouse_layout.addWidget(self._scrolls_val, row, 1, 1, 3)

        # Stretch first column, let sub-stat columns share remaining space
        mouse_layout.setColumnStretch(0, 2)
        mouse_layout.setColumnStretch(1, 1)
        mouse_layout.setColumnStretch(2, 1)
        mouse_layout.setColumnStretch(3, 1)

        stats_row.addWidget(mouse_group)

        # ── Keyboard group ────────────────────────────────
        kb_group = QGroupBox("Keyboard")
        kb_layout = QGridLayout(kb_group)
        kb_layout.setSpacing(6)
        kb_layout.setContentsMargins(12, 20, 12, 12)

        row = 0
        # Keystrokes
        kb_layout.addWidget(QLabel("Keystrokes"), row, 0)
        self._keystrokes_val = QLabel("0")
        self._keystrokes_val.setObjectName("stat-value")
        self._keystrokes_val.setAlignment(Qt.AlignRight)
        kb_layout.addWidget(self._keystrokes_val, row, 1, 1, 3)

        # Keystroke breakdown row 1: Upper / Lower / Code
        row += 1
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(20, 0, 0, 0)
        for label, attr in [
            ("Upper", "_upper_keys_val"),
            ("Lower", "_lower_keys_val"),
            ("Code", "_code_keys_val"),
        ]:
            sub = QVBoxLayout()
            sub.setSpacing(1)
            lbl = QLabel(label)
            lbl.setObjectName("stat-sub-label")
            lbl.setAlignment(Qt.AlignCenter)
            sub.addWidget(lbl)
            val = QLabel("0")
            val.setObjectName("stat-sub-value")
            val.setAlignment(Qt.AlignCenter)
            setattr(self, attr, val)
            sub.addWidget(val)
            sub_row.addLayout(sub)
        kb_layout.addLayout(sub_row, row, 0, 1, 4)

        # Keystroke breakdown row 2: Number / Numpad / Other
        row += 1
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(20, 0, 0, 0)
        for label, attr in [
            ("Number", "_number_keys_val"),
            ("Numpad", "_numpad_keys_val"),
            ("Other", "_other_keys_val"),
        ]:
            sub = QVBoxLayout()
            sub.setSpacing(1)
            lbl = QLabel(label)
            lbl.setObjectName("stat-sub-label")
            lbl.setAlignment(Qt.AlignCenter)
            sub.addWidget(lbl)
            val = QLabel("0")
            val.setObjectName("stat-sub-value")
            val.setAlignment(Qt.AlignCenter)
            setattr(self, attr, val)
            sub.addWidget(val)
            sub_row.addLayout(sub)
        kb_layout.addLayout(sub_row, row, 0, 1, 4)

        # Shortcuts
        row += 1
        kb_layout.addWidget(QLabel("Shortcuts"), row, 0)
        self._shortcuts_val = QLabel("0")
        self._shortcuts_val.setObjectName("stat-value")
        self._shortcuts_val.setAlignment(Qt.AlignRight)
        kb_layout.addWidget(self._shortcuts_val, row, 1, 1, 3)

        # Words
        row += 1
        kb_layout.addWidget(QLabel("Words"), row, 0)
        self._words_val = QLabel("0")
        self._words_val.setObjectName("stat-value")
        self._words_val.setAlignment(Qt.AlignRight)
        kb_layout.addWidget(self._words_val, row, 1, 1, 3)

        # Stretch first column
        kb_layout.setColumnStretch(0, 2)
        kb_layout.setColumnStretch(1, 1)
        kb_layout.setColumnStretch(2, 1)
        kb_layout.setColumnStretch(3, 1)

        stats_row.addWidget(kb_group)

        layout.addLayout(stats_row)

        # ── System Info ──────────────────────────────────────
        sys_group = QGroupBox("System Info")
        sys_layout = QGridLayout(sys_group)
        sys_layout.setSpacing(10)

        sys_layout.addWidget(QLabel("Keyboard Layout:"), 0, 0)
        self._layout_label = QLabel("\u2014")
        self._layout_label.setObjectName("info-value")
        sys_layout.addWidget(self._layout_label, 0, 1)

        sys_layout.addWidget(QLabel("Polling Rate:"), 0, 2)
        self._polling_label = QLabel("\u2014")
        self._polling_label.setObjectName("info-value")
        sys_layout.addWidget(self._polling_label, 0, 3)

        sys_layout.addWidget(QLabel("Mouse Speed:"), 1, 0)
        self._mouse_speed_label = QLabel("\u2014")
        self._mouse_speed_label.setObjectName("info-value")
        sys_layout.addWidget(self._mouse_speed_label, 1, 1)

        sys_layout.addWidget(QLabel("Acceleration:"), 1, 2)
        self._accel_label = QLabel("\u2014")
        self._accel_label.setObjectName("info-value")
        sys_layout.addWidget(self._accel_label, 1, 3)

        sys_layout.addWidget(QLabel("Resolution:"), 2, 0)
        self._resolution_label = QLabel("\u2014")
        self._resolution_label.setObjectName("info-value")
        sys_layout.addWidget(self._resolution_label, 2, 1)

        layout.addWidget(sys_group)

        # ── Model Status ───────────────────────────────────
        model_group = QGroupBox("Model Status")
        model_layout = QVBoxLayout(model_group)

        self._model_status_label = QLabel("No model trained yet")
        self._model_status_label.setObjectName("status")
        model_layout.addWidget(self._model_status_label)

        self._train_progress = QProgressBar()
        self._train_progress.setVisible(False)
        model_layout.addWidget(self._train_progress)

        layout.addWidget(model_group)

        layout.addStretch()

    # ── Stats navigation ──────────────────────────────────

    def _toggle_stats_mode(self):
        """Toggle between total and windowed stats display."""
        if self._stats_mode == "total":
            self._stats_mode = "windowed"
            self._nav_label.setText(f"Last {config.STATS_WINDOW_MINUTES} min")
        else:
            self._stats_mode = "total"
            self._nav_label.setText("Total")
        self._update_stats_display()

    # ── Recording toggle ──────────────────────────────────

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self._recording = True
        self._record_btn.setText("Stop Recording")
        self._record_btn.setObjectName("danger")
        self._record_btn.setStyleSheet("")  # Force style refresh
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)
        self._record_btn.clearFocus()

        self._status_label.setText("Recording")
        self._status_label.setObjectName("status-recording")
        self._status_label.setStyleSheet("")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        self._recording_started = datetime.now()
        self._started_label.setText(
            f"Started: {self._recording_started.strftime('%H:%M:%S')}"
        )
        self._uptime_label.setText("Uptime: 0:00")

        # Disable train/validate during recording
        self._train_btn.setEnabled(False)
        self._validate_btn.setEnabled(False)

        self.start_recording_signal.emit()

    def _stop_recording(self):
        """Show 'Stopping...' state and signal main to stop asynchronously."""
        self._recording = False
        self._record_btn.setText("Stopping...")
        self._record_btn.setEnabled(False)
        self._record_btn.clearFocus()

        self._status_label.setText("Stopping")

        self.stop_recording_signal.emit()

    def on_recording_stopped(self):
        """Called by main.py after async stop completes — finalize UI."""
        self._record_btn.setText("Start Recording")
        self._record_btn.setEnabled(True)
        self._record_btn.setObjectName("success")
        self._record_btn.setStyleSheet("")
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)

        self._status_label.setText("Idle")
        self._status_label.setObjectName("status-text")
        self._status_label.setStyleSheet("")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        self._recording_started = None
        self._started_label.setText("")
        self._uptime_label.setText("")

        self._train_btn.setEnabled(True)
        self._validate_btn.setEnabled(True)

    def _on_train(self):
        reply = QMessageBox.question(
            self, "Train Model",
            "This will train the ML model using all recorded data.\n"
            "This may take a while. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._train_btn.setEnabled(False)
            self._record_btn.setEnabled(False)
            self._train_progress.setVisible(True)
            self._train_progress.setRange(0, 100)
            self._train_progress.setValue(0)
            self._model_status_label.setText("Training in progress...")
            self.train_model_signal.emit()

    def _on_validate(self):
        self.validate_model_signal.emit()

    def _update_stats_display(self):
        """Refresh all stat labels from cached totals/windowed data."""
        # Update uptime if recording
        if self._recording_started:
            delta = datetime.now() - self._recording_started
            total_minutes = int(delta.total_seconds()) // 60
            hours = total_minutes // 60
            minutes = total_minutes % 60
            self._uptime_label.setText(f"Uptime: {hours}:{minutes:02d}")

        data = self._totals if self._stats_mode == "total" else self._windowed

        # Mouse stats
        self._movements_val.setText(self._fmt(data.get("movements", 0)))
        self._clicks_val.setText(self._fmt(data.get("clicks", 0)))
        self._left_clicks_val.setText(self._fmt(data.get("left_clicks", 0)))
        self._right_clicks_val.setText(self._fmt(data.get("right_clicks", 0)))
        self._middle_clicks_val.setText(self._fmt(data.get("middle_clicks", 0)))
        self._double_clicks_val.setText(self._fmt(data.get("double_clicks", 0)))
        self._triple_clicks_val.setText(self._fmt(data.get("triple_clicks", 0)))
        self._spam_clicks_val.setText(self._fmt(data.get("spam_clicks", 0)))
        self._drags_val.setText(self._fmt(data.get("drags", 0)))
        self._scrolls_val.setText(self._fmt(data.get("scrolls", 0)))

        # Keyboard stats
        self._keystrokes_val.setText(self._fmt(data.get("keystrokes", 0)))
        self._upper_keys_val.setText(self._fmt(data.get("upper_keys", 0)))
        self._lower_keys_val.setText(self._fmt(data.get("lower_keys", 0)))
        self._code_keys_val.setText(self._fmt(data.get("code_keys", 0)))
        self._number_keys_val.setText(self._fmt(data.get("number_keys", 0)))
        self._numpad_keys_val.setText(self._fmt(data.get("numpad_keys", 0)))
        self._other_keys_val.setText(self._fmt(data.get("other_keys", 0)))
        self._shortcuts_val.setText(self._fmt(data.get("shortcuts", 0)))
        self._words_val.setText(self._fmt(data.get("words", 0)))

    @staticmethod
    def _fmt(n: int) -> str:
        """Format number with thousand separators."""
        return f"{n:,}"

    # ── Public methods called from main.py ──────────────────

    def on_training_progress(self, percent: int, message: str):
        """Called during training to update progress bar."""
        self._train_progress.setValue(percent)
        self._model_status_label.setText(message)

    def on_training_complete(self, success: bool, message: str):
        """Called when training finishes."""
        self._train_btn.setEnabled(True)
        if not self._recording:
            self._record_btn.setEnabled(True)
        self._train_progress.setVisible(False)
        if success:
            self._model_status_label.setText(f"Model trained: {message}")
            QMessageBox.information(self, "Training Complete", message)
        else:
            self._model_status_label.setText(f"Training failed: {message}")
            QMessageBox.warning(self, "Training Failed", message)

    def update_stats(self, totals: dict[str, int], windowed: dict[str, int]):
        """Update stat data (called from main thread timer)."""
        self._totals = totals
        self._windowed = windowed

    def _on_export(self):
        """Export user's recording database files."""
        files = get_user_db_files(self._user.username, self._user.surname, self._user.date_of_birth)
        if not files:
            QMessageBox.information(
                self, "Export Data",
                "No recording data found yet.\nStart recording first."
            )
            return

        total_size_mb = sum(f.stat().st_size for f in files) / 1024 / 1024
        dest = QFileDialog.getExistingDirectory(
            self, "Choose Export Destination",
            "",
            QFileDialog.ShowDirsOnly,
        )
        if not dest:
            return

        from pathlib import Path
        success, total = export_all_user_data(
            self._user.username, self._user.surname, self._user.date_of_birth, Path(dest),
        )
        if success == total:
            QMessageBox.information(
                self, "Export Complete",
                f"Exported {success} file(s) ({total_size_mb:.1f} MB) to:\n{dest}"
            )
        else:
            QMessageBox.warning(
                self, "Export Partial",
                f"Exported {success}/{total} files.\nCheck logs for details."
            )

    def update_system_info(self, state: dict[str, str], polling_hz: int | None = None):
        """
        Update system info panel.
        state: dict from SystemMonitor.current_state
        polling_hz: estimated mouse polling rate (None if not yet estimated)
        """
        self._layout_label.setText(state.get("keyboard_layout", "\u2014"))
        speed = state.get("mouse_speed", "\u2014")
        self._mouse_speed_label.setText(f"{speed} / 20" if speed != "\u2014" else "\u2014")
        accel = state.get("mouse_acceleration", "\u2014")
        self._accel_label.setText("On" if accel == "True" else "Off" if accel == "False" else accel)
        self._resolution_label.setText(state.get("screen_resolution", "\u2014"))
        self._polling_label.setText(f"~{polling_hz} Hz" if polling_hz else "Estimating...")

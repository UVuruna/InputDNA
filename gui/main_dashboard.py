"""
Main dashboard — shown after login.

Three primary actions:
1. Start/Stop Recording — toggles mouse+keyboard capture
2. Train Model — trains ML model from recorded data
3. Validate Model — tests model accuracy against real input

Shows current user info, recording stats, and model status.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QMessageBox, QProgressBar, QFileDialog,
)
from PySide6.QtCore import Signal, Qt, QTimer

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

    def __init__(self, user: UserProfile, parent=None):
        super().__init__(parent)
        self._user = user
        self._recording = False
        self._build_ui()

        # Stats update timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats_display)
        self._stats_timer.start(1000)  # Update every second

        # Counters (updated externally)
        self.movement_count = 0
        self.click_count = 0
        self.keystroke_count = 0

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        # ── Header ─────────────────────────────────────────
        header = QHBoxLayout()

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

        # ── Status ─────────────────────────────────────────
        self._status_label = QLabel("Status: Idle")
        self._status_label.setObjectName("status")
        layout.addWidget(self._status_label)

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

        # ── Recording Stats ────────────────────────────────
        stats_group = QGroupBox("Recording Statistics")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setSpacing(10)

        stats_layout.addWidget(QLabel("Movements:"), 0, 0)
        self._movements_label = QLabel("0")
        self._movements_label.setObjectName("stat-value")
        stats_layout.addWidget(self._movements_label, 0, 1)

        stats_layout.addWidget(QLabel("Clicks:"), 0, 2)
        self._clicks_label = QLabel("0")
        self._clicks_label.setObjectName("stat-value")
        stats_layout.addWidget(self._clicks_label, 0, 3)

        stats_layout.addWidget(QLabel("Keystrokes:"), 0, 4)
        self._keystrokes_label = QLabel("0")
        self._keystrokes_label.setObjectName("stat-value")
        stats_layout.addWidget(self._keystrokes_label, 0, 5)

        layout.addWidget(stats_group)

        # ── System Info ──────────────────────────────────────
        sys_group = QGroupBox("System Info")
        sys_layout = QGridLayout(sys_group)
        sys_layout.setSpacing(10)

        sys_layout.addWidget(QLabel("Keyboard Layout:"), 0, 0)
        self._layout_label = QLabel("—")
        self._layout_label.setObjectName("info-value")
        sys_layout.addWidget(self._layout_label, 0, 1)

        sys_layout.addWidget(QLabel("Polling Rate:"), 0, 2)
        self._polling_label = QLabel("—")
        self._polling_label.setObjectName("info-value")
        sys_layout.addWidget(self._polling_label, 0, 3)

        sys_layout.addWidget(QLabel("Mouse Speed:"), 1, 0)
        self._mouse_speed_label = QLabel("—")
        self._mouse_speed_label.setObjectName("info-value")
        sys_layout.addWidget(self._mouse_speed_label, 1, 1)

        sys_layout.addWidget(QLabel("Acceleration:"), 1, 2)
        self._accel_label = QLabel("—")
        self._accel_label.setObjectName("info-value")
        sys_layout.addWidget(self._accel_label, 1, 3)

        sys_layout.addWidget(QLabel("Resolution:"), 2, 0)
        self._resolution_label = QLabel("—")
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
        self._status_label.setText("Status: Recording...")
        self._status_label.setObjectName("status-recording")
        self._status_label.setStyleSheet("")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        # Disable train/validate during recording
        self._train_btn.setEnabled(False)
        self._validate_btn.setEnabled(False)

        self.start_recording_signal.emit()

    def _stop_recording(self):
        self._recording = False
        self._record_btn.setText("Start Recording")
        self._record_btn.setObjectName("success")
        self._record_btn.setStyleSheet("")
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)
        self._record_btn.clearFocus()
        self._status_label.setText("Status: Idle")
        self._status_label.setObjectName("status")
        self._status_label.setStyleSheet("")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        self._train_btn.setEnabled(True)
        self._validate_btn.setEnabled(True)

        self.stop_recording_signal.emit()

    def _on_train(self):
        reply = QMessageBox.question(
            self, "Train Model",
            "This will train the ML model using all recorded data.\n"
            "This may take a while. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._train_btn.setEnabled(False)
            self._train_progress.setVisible(True)
            self._train_progress.setRange(0, 0)  # Indeterminate
            self._model_status_label.setText("Training in progress...")
            self.train_model_signal.emit()

    def _on_validate(self):
        self.validate_model_signal.emit()

    def _update_stats_display(self):
        self._movements_label.setText(str(self.movement_count))
        self._clicks_label.setText(str(self.click_count))
        self._keystrokes_label.setText(str(self.keystroke_count))

    # ── Public methods called from app.py ──────────────────

    def on_training_complete(self, success: bool, message: str):
        """Called when training finishes."""
        self._train_btn.setEnabled(True)
        self._train_progress.setVisible(False)
        if success:
            self._model_status_label.setText(f"Model trained: {message}")
            QMessageBox.information(self, "Training Complete", message)
        else:
            self._model_status_label.setText(f"Training failed: {message}")
            QMessageBox.warning(self, "Training Failed", message)

    def update_stats(self, movements: int, clicks: int, keystrokes: int):
        """Update stat counters (called from recorder thread)."""
        self.movement_count = movements
        self.click_count = clicks
        self.keystroke_count = keystrokes

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
        self._layout_label.setText(state.get("keyboard_layout", "—"))
        speed = state.get("mouse_speed", "—")
        self._mouse_speed_label.setText(f"{speed} / 20" if speed != "—" else "—")
        accel = state.get("mouse_acceleration", "—")
        self._accel_label.setText("On" if accel == "True" else "Off" if accel == "False" else accel)
        self._resolution_label.setText(state.get("screen_resolution", "—"))
        self._polling_label.setText(f"~{polling_hz} Hz" if polling_hz else "Estimating...")

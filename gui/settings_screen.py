"""
Settings screen — user-configurable recording and system options.

Accessible from the main dashboard via the Settings button.
All settings are stored per-user in profiles.db and override
the defaults in config.py when the user is logged in.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QComboBox, QSlider, QSpinBox,
    QMessageBox, QScrollArea,
)
from PySide6.QtCore import Signal, Qt

import config
from gui.user_settings import save_settings, load_settings, delete_settings

logger = logging.getLogger(__name__)


class SettingsScreen(QWidget):
    """Settings page with recording, system, and calibration options."""

    back_signal = Signal()
    settings_changed_signal = Signal(dict)

    # Calibration buttons emit these so the app layer can open dialogs
    calibrate_click_signal = Signal()
    calibrate_dpi_signal = Signal()

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._build_ui()
        self._load_current_values()

    def showEvent(self, event):
        """Refresh downsample options each time settings screen is shown."""
        super().showEvent(event)
        current = self._downsample_combo.currentData()
        self._populate_downsample_combo()
        idx = self._downsample_combo.findData(current)
        if idx >= 0:
            self._downsample_combo.setCurrentIndex(idx)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 20, 30, 20)
        outer.setSpacing(15)

        # ── Header ────────────────────────────────────────────
        header = QHBoxLayout()

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self.back_signal.emit)
        header.addWidget(back_btn)

        title = QLabel("Settings")
        title.setObjectName("title")
        header.addWidget(title)

        header.addStretch()
        outer.addLayout(header)

        # ── Scrollable content ────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(15)

        # ── Recording Settings ────────────────────────────────
        rec_group = QGroupBox("Recording")
        rec_layout = QGridLayout(rec_group)
        rec_layout.setSpacing(10)
        row = 0

        # Downsampling Hz
        rec_layout.addWidget(QLabel("Downsampling:"), row, 0)
        self._downsample_combo = QComboBox()
        self._populate_downsample_combo()
        rec_layout.addWidget(self._downsample_combo, row, 1)
        row += 1

        # Session timeout
        rec_layout.addWidget(QLabel("Session timeout:"), row, 0)
        timeout_row = QHBoxLayout()
        self._timeout_slider = QSlider(Qt.Horizontal)
        self._timeout_slider.setRange(100, 1000)
        self._timeout_slider.setSingleStep(50)
        self._timeout_label = QLabel("300 ms")
        self._timeout_label.setMinimumWidth(60)
        self._timeout_slider.valueChanged.connect(
            lambda v: self._timeout_label.setText(f"{v} ms")
        )
        timeout_row.addWidget(self._timeout_slider)
        timeout_row.addWidget(self._timeout_label)
        rec_layout.addLayout(timeout_row, row, 1)
        row += 1

        # Min session distance
        rec_layout.addWidget(QLabel("Min distance:"), row, 0)
        dist_row = QHBoxLayout()
        self._distance_slider = QSlider(Qt.Horizontal)
        self._distance_slider.setRange(0, 20)
        self._distance_label = QLabel("3 px")
        self._distance_label.setMinimumWidth(60)
        self._distance_slider.valueChanged.connect(
            lambda v: self._distance_label.setText(f"{v} px")
        )
        dist_row.addWidget(self._distance_slider)
        dist_row.addWidget(self._distance_label)
        rec_layout.addLayout(dist_row, row, 1)
        row += 1

        # DB max size
        rec_layout.addWidget(QLabel("DB max size:"), row, 0)
        self._db_size_combo = QComboBox()
        for gb in range(1, 11):
            self._db_size_combo.addItem(f"{gb} GB", gb * 1024 * 1024 * 1024)
        rec_layout.addWidget(self._db_size_combo, row, 1)
        row += 1

        layout.addWidget(rec_group)

        # ── System Settings ───────────────────────────────────
        sys_group = QGroupBox("System")
        sys_layout = QGridLayout(sys_group)
        sys_layout.setSpacing(10)
        row = 0

        # DPI
        sys_layout.addWidget(QLabel("Mouse DPI:"), row, 0)
        dpi_row = QHBoxLayout()
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(100, 16000)
        self._dpi_spin.setSingleStep(100)
        dpi_row.addWidget(self._dpi_spin)
        self._measure_dpi_btn = QPushButton("Measure")
        self._measure_dpi_btn.clicked.connect(self.calibrate_dpi_signal.emit)
        dpi_row.addWidget(self._measure_dpi_btn)
        sys_layout.addLayout(dpi_row, row, 1)
        row += 1

        layout.addWidget(sys_group)

        # ── Calibration ──────────────────────────────────────
        cal_group = QGroupBox("Calibration")
        cal_layout = QGridLayout(cal_group)
        cal_layout.setSpacing(10)

        cal_layout.addWidget(QLabel("Click speed:"), 0, 0)
        click_row = QHBoxLayout()
        self._click_gap_label = QLabel("500 ms (default)")
        click_row.addWidget(self._click_gap_label)
        cal_btn = QPushButton("Calibrate")
        cal_btn.clicked.connect(self.calibrate_click_signal.emit)
        click_row.addWidget(cal_btn)
        cal_layout.addLayout(click_row, 0, 1)

        layout.addWidget(cal_group)

        # ── Buttons ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
        btn_row.addWidget(reset_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _populate_downsample_combo(self):
        """Populate downsample combo with rates below the detected polling rate."""
        self._downsample_combo.clear()
        self._downsample_combo.addItem("Off (store all)", 0)

        polling = config.ESTIMATED_POLLING_HZ
        all_rates = [125, 250, 500, 1000, 2000, 4000, 8000]

        if polling is not None:
            rates = [hz for hz in all_rates if hz < polling]
        else:
            # Polling rate not yet estimated — show all options
            rates = all_rates

        for hz in rates:
            self._downsample_combo.addItem(f"{hz} Hz", hz)

    def _load_current_values(self):
        """Load current values from config (which may already have user overrides)."""
        # Refresh downsample options (polling rate may have been estimated since build)
        self._populate_downsample_combo()

        # Downsampling
        idx = self._downsample_combo.findData(config.DOWNSAMPLE_HZ)
        if idx >= 0:
            self._downsample_combo.setCurrentIndex(idx)

        # Session timeout
        self._timeout_slider.setValue(config.SESSION_END_TIMEOUT_MS)

        # Min distance
        self._distance_slider.setValue(config.MIN_SESSION_DISTANCE_PX)

        # DB max size
        idx = self._db_size_combo.findData(config.DB_ROTATION_MAX_BYTES)
        if idx >= 0:
            self._db_size_combo.setCurrentIndex(idx)
        else:
            # Find closest GB value
            gb = max(1, min(10, config.DB_ROTATION_MAX_BYTES // (1024**3)))
            idx = self._db_size_combo.findData(gb * 1024**3)
            if idx >= 0:
                self._db_size_combo.setCurrentIndex(idx)

        # DPI
        self._dpi_spin.setValue(config.USER_DPI)

        # Click gap
        self._update_click_gap_display()

    def _update_click_gap_display(self):
        """Update the click gap label with current value."""
        gap = config.CLICK_SEQUENCE_GAP_MS
        # Check if it's been calibrated (different from default 500)
        source = "calibrated" if gap != 500 else "default"
        self._click_gap_label.setText(f"{gap} ms ({source})")

    def _save_settings(self):
        """Collect all settings and save to DB + apply to config."""
        settings = {}

        # Recording settings
        settings["recording.downsample_hz"] = str(
            self._downsample_combo.currentData()
        )
        settings["recording.session_end_timeout_ms"] = str(
            self._timeout_slider.value()
        )
        settings["recording.min_session_distance_px"] = str(
            self._distance_slider.value()
        )
        settings["recording.db_rotation_max_bytes"] = str(
            self._db_size_combo.currentData()
        )

        # System settings
        settings["system.dpi"] = str(self._dpi_spin.value())

        # Persist to DB
        save_settings(self._user_id, settings)

        # Apply to config module
        config.apply_user_settings(settings)

        self.settings_changed_signal.emit(settings)
        QMessageBox.information(self, "Settings", "Settings saved successfully.")

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self, "Reset Settings",
            "Reset all settings to defaults?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            delete_settings(self._user_id)
            config.reset_to_defaults()
            self._load_current_values()
            QMessageBox.information(self, "Settings", "Settings reset to defaults.")

    def set_dpi_value(self, dpi: int):
        """Called externally after DPI measurement dialog."""
        self._dpi_spin.setValue(dpi)

    def set_click_gap_value(self, gap_ms: int):
        """Called externally after click calibration dialog."""
        config.CLICK_SEQUENCE_GAP_MS = gap_ms
        self._update_click_gap_display()

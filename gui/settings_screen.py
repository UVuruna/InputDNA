"""
Settings screen — user-configurable recording and system options.

Accessible from the main dashboard via the Settings button.
All settings are stored per-user in profiles.db and override
the defaults in config.py when the user is logged in.
"""

import ctypes
import logging
import winreg

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QComboBox, QSlider, QSpinBox,
    QCheckBox, QKeySequenceEdit, QMessageBox, QScrollArea,
)
from PySide6.QtCore import Signal, Qt

import config
from gui.user_settings import save_settings, load_settings, delete_settings

logger = logging.getLogger(__name__)

# Registry key for Windows autostart
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "InputDNA"


def _get_exe_path() -> str:
    """Get the executable path for autostart registry entry."""
    import sys
    if getattr(sys, 'frozen', False):
        return sys.executable
    return f'"{sys.executable}" "{__file__}"'


def _is_autostart_enabled() -> bool:
    """Check if InputDNA is set to start with Windows."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _set_autostart(enabled: bool) -> None:
    """Enable or disable Windows autostart for InputDNA."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, _get_exe_path())
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        logger.error(f"Failed to set autostart: {e}")


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
        self._downsample_combo.addItem("Off (store all)", 0)
        for hz in [125, 250, 500, 1000, 2000, 4000, 8000]:
            self._downsample_combo.addItem(f"{hz} Hz", hz)
        rec_layout.addWidget(self._downsample_combo, row, 1)
        row += 1

        # Session timeout
        rec_layout.addWidget(QLabel("Session timeout:"), row, 0)
        timeout_row = QHBoxLayout()
        self._timeout_slider = QSlider(Qt.Horizontal)
        self._timeout_slider.setRange(100, 1000)
        self._timeout_slider.setSingleStep(50)
        self._timeout_label = QLabel("300 ms")
        self._timeout_label.setFixedWidth(60)
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
        self._distance_label.setFixedWidth(60)
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

        # Hotkey
        rec_layout.addWidget(QLabel("Pause hotkey:"), row, 0)
        self._hotkey_edit = QKeySequenceEdit()
        rec_layout.addWidget(self._hotkey_edit, row, 1)
        row += 1

        layout.addWidget(rec_group)

        # ── System Settings ───────────────────────────────────
        sys_group = QGroupBox("System")
        sys_layout = QGridLayout(sys_group)
        sys_layout.setSpacing(10)
        row = 0

        # Start with Windows
        self._autostart_check = QCheckBox("Start with Windows")
        sys_layout.addWidget(self._autostart_check, row, 0, 1, 2)
        row += 1

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

    def _load_current_values(self):
        """Load current values from config (which may already have user overrides)."""
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

        # Hotkey — display current value as label (QKeySequenceEdit can't parse pynput format)
        self._hotkey_edit.setToolTip(f"Current: {config.HOTKEY_TOGGLE}")

        # Autostart
        self._autostart_check.setChecked(_is_autostart_enabled())

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

        # Hotkey — only save if user entered something
        seq = self._hotkey_edit.keySequence()
        if not seq.isEmpty():
            hotkey_str = _qt_keysequence_to_pynput(seq.toString())
            if hotkey_str:
                settings["recording.hotkey_toggle"] = hotkey_str

        # System settings
        settings["system.dpi"] = str(self._dpi_spin.value())
        settings["system.start_with_windows"] = str(
            self._autostart_check.isChecked()
        )

        # Persist to DB
        save_settings(self._user_id, settings)

        # Apply to config module
        config.apply_user_settings(settings)

        # Handle autostart registry
        _set_autostart(self._autostart_check.isChecked())

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


def _qt_keysequence_to_pynput(qt_str: str) -> str:
    """
    Convert Qt key sequence string to pynput hotkey format.

    Qt: "Ctrl+Alt+R"  →  pynput: "<ctrl>+<alt>+r"
    """
    if not qt_str:
        return ""

    parts = qt_str.split("+")
    result = []
    for part in parts:
        part = part.strip().lower()
        if part in ("ctrl", "control"):
            result.append("<ctrl>")
        elif part in ("alt",):
            result.append("<alt>")
        elif part in ("shift",):
            result.append("<shift>")
        elif part in ("meta", "win"):
            result.append("<cmd>")
        else:
            result.append(part)
    return "+".join(result)

"""
Global settings dialog — application-wide settings accessible from login screen.

Contains settings that are NOT per-user:
- Data storage location
- Start with Windows
"""

import logging
import winreg

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QCheckBox, QLineEdit, QFileDialog,
)
from PySide6.QtCore import Qt

import config
from gui.global_settings import save_globals, load_globals

logger = logging.getLogger(__name__)

# Registry key for Windows autostart
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "InputDNA"


def _is_autostart_enabled() -> bool:
    """Check if InputDNA is set to start with Windows."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, OSError):
        return False


def _set_autostart(enabled: bool) -> None:
    """Enable or disable Windows autostart for InputDNA."""
    import sys
    exe_path = sys.executable if getattr(sys, 'frozen', False) else f'"{sys.executable}" "{__file__}"'
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        logger.error(f"Failed to set autostart: {e}")


class GlobalSettingsDialog(QDialog):
    """Dialog for application-wide settings (data location, autostart)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Settings")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_current_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── Storage ─────────────────────────────────────────
        storage_group = QGroupBox("Storage")
        storage_layout = QGridLayout(storage_group)
        storage_layout.setSpacing(10)

        storage_layout.addWidget(QLabel("Data location:"), 0, 0)
        path_row = QHBoxLayout()
        self._data_dir_edit = QLineEdit()
        self._data_dir_edit.setPlaceholderText(f"Default ({config.DB_DIR})")
        self._data_dir_edit.setReadOnly(True)
        path_row.addWidget(self._data_dir_edit)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_data_dir)
        path_row.addWidget(browse_btn)

        clear_btn = QPushButton("Reset")
        clear_btn.setToolTip("Use default location")
        clear_btn.clicked.connect(lambda: self._data_dir_edit.clear())
        path_row.addWidget(clear_btn)

        storage_layout.addLayout(path_row, 0, 1)
        layout.addWidget(storage_group)

        # ── System ──────────────────────────────────────────
        sys_group = QGroupBox("System")
        sys_layout = QGridLayout(sys_group)
        sys_layout.setSpacing(10)

        self._autostart_check = QCheckBox("Start with Windows")
        sys_layout.addWidget(self._autostart_check, 0, 0, 1, 2)

        layout.addWidget(sys_group)

        # ── Buttons ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _load_current_values(self):
        """Load current global settings."""
        if config.CUSTOM_USER_DATA_DIR:
            self._data_dir_edit.setText(config.CUSTOM_USER_DATA_DIR)
        self._autostart_check.setChecked(_is_autostart_enabled())

    def _browse_data_dir(self):
        """Open folder picker for custom data location."""
        current = self._data_dir_edit.text() or str(config.DB_DIR)
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Data Location", current,
            QFileDialog.ShowDirsOnly,
        )
        if folder:
            self._data_dir_edit.setText(folder)

    def _save(self):
        """Save global settings to DB and apply."""
        settings = {
            "storage.data_dir": self._data_dir_edit.text(),
            "system.start_with_windows": str(self._autostart_check.isChecked()),
        }

        # Persist to profiles.db
        save_globals(settings)

        # Apply to config
        config.CUSTOM_USER_DATA_DIR = settings["storage.data_dir"]
        config.START_WITH_WINDOWS = self._autostart_check.isChecked()

        # Handle autostart registry
        _set_autostart(self._autostart_check.isChecked())

        self.accept()

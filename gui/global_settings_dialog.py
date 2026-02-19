"""
Global settings dialog — application-wide settings accessible from login screen.

Contains settings that are NOT per-user:
- Appearance theme (dark / light / auto)
- Data storage location
- Default user for auto-login
- Start with Windows (auto-login + auto-record)
- Minimize on close (X → tray instead of exit)
"""

import logging
import winreg

from PySide6.QtWidgets import (
    QApplication,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QCheckBox, QLineEdit, QFileDialog,
    QComboBox,
)
from PySide6.QtCore import Qt

import config
from gui.global_settings import save_globals, load_globals
from gui.user_db import get_all_profiles
from gui.styles import get_stylesheet

logger = logging.getLogger(__name__)

# Registry key for Windows autostart
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "InputDNA"


def _is_autostart_enabled() -> bool:
    """Check if InputDNA is set to start with Windows.

    Checks both the Run key (command exists) and StartupApproved key
    (not disabled by Task Manager / Windows Settings).
    """
    # Check Run key exists
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
    except (FileNotFoundError, OSError):
        return False

    # Check StartupApproved — if entry exists and first byte is 0x03, it's disabled
    _STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_KEY, 0, winreg.KEY_READ,
        )
        value, _ = winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
        if value[0] == 3:  # 0x03 = disabled by user via Task Manager
            return False
    except (FileNotFoundError, OSError):
        pass  # No approved entry — treat as enabled (will be created on save)

    return True


def _set_autostart(enabled: bool) -> None:
    """Enable or disable Windows autostart for InputDNA.

    Writes to both registry keys:
    - HKCU\\...\\Run — the command to execute
    - HKCU\\...\\StartupApproved\\Run — enabled/disabled flag (required by Windows 11)

    Adds --autostart flag so the app knows it was launched at boot
    (auto-login default user, auto-record, stay in tray).
    """
    import struct
    import sys
    if getattr(sys, 'frozen', False):
        exe_path = f'"{sys.executable}" --autostart'
    else:
        # Dev mode — not used for real autostart, user installs the app
        exe_path = f'"{sys.executable}" "{__file__}"'
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
        logger.error(f"Failed to set autostart in Run key: {e}")
        return

    # Windows 11 requires StartupApproved\\Run entry to actually launch the app
    _STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_KEY, 0, winreg.KEY_SET_VALUE,
        )
        if enabled:
            # 0x02 = enabled, followed by 8 zero bytes (timestamp not needed for user entries)
            approved_value = struct.pack("<3I", 2, 0, 0)
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_BINARY, approved_value)
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        logger.error(f"Failed to set StartupApproved: {e}")


class GlobalSettingsDialog(QDialog):
    """Dialog for application-wide settings (data location, autostart)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Settings")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_current_values()

    # Theme combo items: (display text, DB value)
    _THEME_OPTIONS = [
        ("Dark", "dark"),
        ("Light", "light"),
        ("Windows (follow system)", "auto"),
    ]

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── Appearance ─────────────────────────────────────
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QGridLayout(appearance_group)
        appearance_layout.setSpacing(10)

        appearance_layout.addWidget(QLabel("Theme:"), 0, 0)
        self._theme_combo = QComboBox()
        for label, value in self._THEME_OPTIONS:
            self._theme_combo.addItem(label, value)
        appearance_layout.addWidget(self._theme_combo, 0, 1)

        layout.addWidget(appearance_group)

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

        # ── Startup ─────────────────────────────────────────
        startup_group = QGroupBox("Startup")
        startup_layout = QGridLayout(startup_group)
        startup_layout.setSpacing(10)

        startup_layout.addWidget(QLabel("Default user:"), 0, 0)
        self._default_user_combo = QComboBox()
        self._default_user_combo.addItem("None", "")
        for profile in get_all_profiles():
            display = f"{profile.username} ({profile.surname})"
            self._default_user_combo.addItem(display, profile.username)
        startup_layout.addWidget(self._default_user_combo, 0, 1)

        self._autostart_check = QCheckBox(
            "Start recording with Windows startup"
        )
        self._autostart_check.setToolTip(
            "Auto-login the default user and start recording at boot.\n"
            "The app stays in the system tray (no window shown)."
        )
        startup_layout.addWidget(self._autostart_check, 1, 0, 1, 2)

        self._minimize_check = QCheckBox("Minimize on close")
        self._minimize_check.setToolTip(
            "Close button minimizes to system tray instead of exiting.\n"
            "Use right-click → Quit on the tray icon to exit."
        )
        startup_layout.addWidget(self._minimize_check, 2, 0, 1, 2)

        layout.addWidget(startup_group)

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
        saved = load_globals()

        # Theme
        theme = saved.get("appearance.theme", "dark")
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        # Data dir
        if config.CUSTOM_USER_DATA_DIR:
            self._data_dir_edit.setText(config.CUSTOM_USER_DATA_DIR)

        # Default user
        default_user = saved.get("startup.default_user", "")
        idx = self._default_user_combo.findData(default_user)
        if idx >= 0:
            self._default_user_combo.setCurrentIndex(idx)

        # Autostart + minimize on close
        self._autostart_check.setChecked(_is_autostart_enabled())
        self._minimize_check.setChecked(config.MINIMIZE_ON_CLOSE)

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
        theme = self._theme_combo.currentData()
        settings = {
            "appearance.theme": theme,
            "storage.data_dir": self._data_dir_edit.text(),
            "startup.default_user": self._default_user_combo.currentData() or "",
            "system.start_with_windows": str(self._autostart_check.isChecked()),
            "system.minimize_on_close": str(self._minimize_check.isChecked()),
        }

        # Persist to profiles.db
        save_globals(settings)

        # Apply theme immediately
        QApplication.instance().setStyleSheet(get_stylesheet(theme))

        # Apply to config
        config.CUSTOM_USER_DATA_DIR = settings["storage.data_dir"]
        config.DEFAULT_USER = settings["startup.default_user"]
        config.START_WITH_WINDOWS = self._autostart_check.isChecked()
        config.MINIMIZE_ON_CLOSE = self._minimize_check.isChecked()

        # Handle autostart registry
        _set_autostart(self._autostart_check.isChecked())

        self.accept()

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
import subprocess
import sys

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

_TASK_NAME = "InputDNA"


def _is_autostart_enabled() -> bool:
    """Check if InputDNA scheduled task exists and is enabled.

    Uses Task Scheduler instead of registry Run key because the exe
    requires admin elevation (--uac-admin), and Windows silently skips
    elevated apps from the registry Run key at boot.
    Task Scheduler with /rl highest launches elevated apps without UAC prompt.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", _TASK_NAME, "/fo", "CSV", "/nh"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False
        # CSV output: "TaskName","Next Run Time","Status"
        # Status = Ready means enabled, Disabled means disabled
        return "Disabled" not in result.stdout
    except OSError as e:
        logger.error(f"Failed to query scheduled task: {e}")
        return False


def _set_autostart(enabled: bool) -> None:
    """Enable or disable Windows autostart via Task Scheduler.

    Uses schtasks with /rl highest to launch the elevated exe at logon
    without a UAC prompt. Registry Run key does NOT work for elevated apps
    because Windows silently skips them at boot.
    """
    if enabled:
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = __file__
        try:
            subprocess.run(
                [
                    "schtasks", "/create",
                    "/tn", _TASK_NAME,
                    "/tr", f'"{exe_path}" --autostart',
                    "/sc", "onlogon",
                    "/rl", "highest",
                    "/f",
                ],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=True,
            )
            logger.info("Autostart scheduled task created")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create autostart task: {e.stderr}")
        except OSError as e:
            logger.error(f"Failed to run schtasks: {e}")
    else:
        try:
            subprocess.run(
                ["schtasks", "/delete", "/tn", _TASK_NAME, "/f"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logger.info("Autostart scheduled task removed")
        except OSError as e:
            logger.error(f"Failed to delete autostart task: {e}")

    _cleanup_registry_autostart()


def _cleanup_registry_autostart() -> None:
    """Remove old registry Run key entries from previous versions.

    Previous versions used HKCU\\...\\Run which doesn't work for elevated apps.
    Clean up to avoid confusion in Task Manager's Startup apps tab.
    """
    import winreg
    for key_path in (
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
    ):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, _TASK_NAME)
            winreg.CloseKey(key)
            logger.info(f"Cleaned up old registry entry: {key_path}\\{_TASK_NAME}")
        except (FileNotFoundError, OSError):
            pass


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

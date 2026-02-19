"""
Login / Register screen.

First screen shown on app start. Two tabs:
- Login: enter username to access existing profile
- Register: create new profile (username, surname, date of birth)

On successful login, emits signal with UserProfile to switch to dashboard.
When a user is already logged in (navigated here via Home), shows recording
status indicator and disables login for other users.
"""

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDateEdit, QPushButton, QTabWidget, QMessageBox, QSpacerItem,
    QSizePolicy, QComboBox,
)
from PySide6.QtCore import Signal, QDate, Qt
from PySide6.QtGui import QPixmap

from gui.user_db import UserProfile, register, login, get_all_profiles
from gui.global_settings_dialog import GlobalSettingsDialog
from ui.tray_icon import detect_windows_theme

_UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class LoginScreen(QWidget):
    """Login/Register screen with two tabs."""

    # Emitted on successful login with user profile
    login_success = Signal(object)

    # Emitted when user clicks "Back to Dashboard" (while logged in)
    back_to_dashboard = Signal()

    # Emitted when user clicks "Readme" button
    readme_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_user: UserProfile | None = None
        self._is_idle = False
        self._build_ui()
        self._load_status_icons()

    def _load_status_icons(self):
        """Load recording/idle status icons from tray icon PNGs."""
        theme = detect_windows_theme()
        theme_dir = _UI_DIR / theme
        self._icon_recording = QPixmap(str(theme_dir / "InputDNA-start.png"))
        self._icon_idle = QPixmap(str(theme_dir / "InputDNA-pause.png"))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(60, 40, 60, 40)

        # ── Top row: Back to Dashboard button (hidden by default) ──
        top_row = QHBoxLayout()
        self._back_btn = QPushButton("\u2190 Dashboard")
        self._back_btn.setToolTip("Return to the active user's dashboard")
        self._back_btn.clicked.connect(self.back_to_dashboard.emit)
        self._back_btn.setVisible(False)
        top_row.addWidget(self._back_btn)
        top_row.addStretch()

        readme_btn = QPushButton("Readme")
        readme_btn.setToolTip("Browse project documentation")
        readme_btn.clicked.connect(self.readme_signal.emit)
        top_row.addWidget(readme_btn)

        layout.addLayout(top_row)

        # Title
        title = QLabel("Human Input Simulator")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Personalized AI Input Agent")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Tab widget
        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), "Login")
        tabs.addTab(self._build_register_tab(), "Register")
        tabs.setMinimumWidth(400)
        layout.addWidget(tabs, alignment=Qt.AlignCenter)

        layout.addStretch()

        # ── Recording status indicator (hidden by default) ─────────
        self._status_row = QHBoxLayout()
        self._status_row.setAlignment(Qt.AlignCenter)

        self._status_icon_label = QLabel()
        self._status_icon_label.setFixedSize(24, 24)
        self._status_icon_label.setScaledContents(True)
        self._status_row.addWidget(self._status_icon_label)

        self._status_text_label = QLabel()
        self._status_text_label.setObjectName("info-value")
        self._status_row.addWidget(self._status_text_label)

        self._status_widget = QWidget()
        self._status_widget.setLayout(self._status_row)
        self._status_widget.setVisible(False)
        layout.addWidget(self._status_widget, alignment=Qt.AlignCenter)

        layout.addSpacing(10)

        # Settings button — bottom right
        settings_row = QHBoxLayout()
        settings_row.addStretch()
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_global_settings)
        settings_row.addWidget(settings_btn)
        layout.addLayout(settings_row)

    def _open_global_settings(self):
        """Open the global settings dialog."""
        dialog = GlobalSettingsDialog(self)
        dialog.exec()

    def _build_login_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        lay.addWidget(QLabel("Username:"))
        self._login_combo = QComboBox()
        self._login_combo.setPlaceholderText("Select user")
        self._refresh_user_list()
        lay.addWidget(self._login_combo)

        lay.addSpacing(10)

        self._login_btn = QPushButton("Login")
        self._login_btn.setObjectName("primary")
        self._login_btn.clicked.connect(self._do_login)
        lay.addWidget(self._login_btn)

        lay.addStretch()
        return w

    def _build_register_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        lay.addWidget(QLabel("Username:"))
        self._reg_username = QLineEdit()
        self._reg_username.setPlaceholderText("Choose a username")
        lay.addWidget(self._reg_username)

        lay.addWidget(QLabel("Surname:"))
        self._reg_surname = QLineEdit()
        self._reg_surname.setPlaceholderText("Your surname")
        lay.addWidget(self._reg_surname)

        lay.addWidget(QLabel("Date of Birth:"))
        self._reg_dob = QDateEdit()
        self._reg_dob.setCalendarPopup(True)
        self._reg_dob.setDate(QDate(2000, 1, 1))
        self._reg_dob.setDisplayFormat("yyyy-MM-dd")
        lay.addWidget(self._reg_dob)

        lay.addSpacing(10)

        btn = QPushButton("Register")
        btn.setObjectName("primary")
        btn.clicked.connect(self._do_register)
        lay.addWidget(btn)

        lay.addStretch()
        return w

    def _refresh_user_list(self):
        """Populate the login dropdown with 'Username Surname Agey' format."""
        self._login_combo.clear()
        today = date.today()
        for profile in get_all_profiles():
            age = self._calc_age(profile.date_of_birth, today)
            display = f"{profile.username} {profile.surname} {age}y"
            self._login_combo.addItem(display, profile.username)

    @staticmethod
    def _calc_age(dob_str: str, today: date) -> int:
        """Calculate age in years from ISO date string."""
        parts = dob_str.split("-")
        dob = date(int(parts[0]), int(parts[1]), int(parts[2]))
        age = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1
        return age

    def _do_login(self):
        if self._active_user:
            QMessageBox.information(
                self, "User Active",
                f"{self._active_user.username} ({self._active_user.surname}) "
                f"is currently logged in.\nLog out first to switch users.",
            )
            return

        username = self._login_combo.currentData()
        if not username:
            QMessageBox.warning(self, "Error", "No user selected.\nPlease register first.")
            return

        profile = login(username)
        if profile:
            self.login_success.emit(profile)
        else:
            QMessageBox.warning(self, "Error",
                                f"Username '{username}' not found.")

    def _do_register(self):
        username = self._reg_username.text().strip()
        surname = self._reg_surname.text().strip()
        dob = self._reg_dob.date().toString("yyyy-MM-dd")

        if not username or not surname:
            QMessageBox.warning(self, "Error", "All fields are required.")
            return

        ok, msg = register(username, surname, dob)
        if ok:
            QMessageBox.information(self, "Success", msg)
            self._refresh_user_list()
            # Auto-login after registration (only if no active user)
            if not self._active_user:
                profile = login(username)
                if profile:
                    self.login_success.emit(profile)
        else:
            QMessageBox.warning(self, "Error", msg)

    # ── Active user / recording status management ──────────────

    def set_active_user(self, profile: UserProfile):
        """Mark a user as active — disables login, shows back button."""
        self._active_user = profile
        self._back_btn.setVisible(True)
        self._login_btn.setEnabled(False)
        self._login_btn.setToolTip(
            f"{profile.username} is logged in — log out first to switch users"
        )
        self._status_widget.setVisible(True)
        self._update_status_display()

    def clear_active_user(self):
        """Clear active user — re-enables login, hides status."""
        self._active_user = None
        self._is_idle = False
        self._back_btn.setVisible(False)
        self._login_btn.setEnabled(True)
        self._login_btn.setToolTip("")
        self._status_widget.setVisible(False)

    def update_recording_status(self, is_recording: bool, is_idle: bool):
        """Update recording status indicator (called from stats timer)."""
        self._is_idle = is_idle
        if self._active_user:
            self._update_status_display(is_recording)

    def _update_status_display(self, is_recording: bool = True):
        """Refresh the status icon and text."""
        user = self._active_user
        if not user:
            return
        if is_recording and self._is_idle:
            self._status_icon_label.setPixmap(self._icon_idle)
            self._status_text_label.setText(
                f"Recording (idle): {user.username} ({user.surname})"
            )
        elif is_recording:
            self._status_icon_label.setPixmap(self._icon_recording)
            self._status_text_label.setText(
                f"Recording: {user.username} ({user.surname})"
            )
        else:
            self._status_icon_label.setPixmap(self._icon_idle)
            self._status_text_label.setText(
                f"Logged in: {user.username} ({user.surname})"
            )

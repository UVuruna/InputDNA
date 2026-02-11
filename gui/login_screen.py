"""
Login / Register screen.

First screen shown on app start. Two tabs:
- Login: enter username to access existing profile
- Register: create new profile (username, surname, date of birth)

On successful login, emits signal with UserProfile to switch to dashboard.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDateEdit, QPushButton, QTabWidget, QMessageBox, QSpacerItem,
    QSizePolicy,
)
from PySide6.QtCore import Signal, QDate, Qt

from gui.user_db import UserProfile, register, login


class LoginScreen(QWidget):
    """Login/Register screen with two tabs."""

    # Emitted on successful login with user profile
    login_success = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(60, 40, 60, 40)

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
        tabs.setFixedWidth(400)
        layout.addWidget(tabs, alignment=Qt.AlignCenter)

        layout.addStretch()

    def _build_login_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        lay.addWidget(QLabel("Username:"))
        self._login_username = QLineEdit()
        self._login_username.setPlaceholderText("Enter your username")
        lay.addWidget(self._login_username)

        lay.addSpacing(10)

        btn = QPushButton("Login")
        btn.setObjectName("primary")
        btn.clicked.connect(self._do_login)
        lay.addWidget(btn)

        # Enter key triggers login
        self._login_username.returnPressed.connect(self._do_login)

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

    def _do_login(self):
        username = self._login_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Error", "Please enter a username.")
            return

        profile = login(username)
        if profile:
            self.login_success.emit(profile)
        else:
            QMessageBox.warning(self, "Error",
                                f"Username '{username}' not found.\nPlease register first.")

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
            # Auto-login after registration
            profile = login(username)
            if profile:
                self.login_success.emit(profile)
        else:
            QMessageBox.warning(self, "Error", msg)

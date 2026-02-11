"""
Model validation screen.

Validates mouse and keyboard models separately in real-time.

Mouse validation:
- Waits for user to perform a mouse action (movement start → click/end)
- After action ends, model predicts what the path should look like
  for the same start/end points
- Compares actual path vs predicted path
- Shows similarity percentage

Keyboard validation:
- Waits for user to type (key transitions)
- Model predicts delays between keys based on scan code pairs
- Compares actual delays vs predicted delays
- Shows similarity percentage
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QTextEdit, QSplitter,
)
from PySide6.QtCore import Signal, Qt, QTimer


class ValidationScreen(QWidget):
    """Real-time model validation view."""

    back_signal = Signal()           # Go back to dashboard
    start_validation_signal = Signal()
    stop_validation_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._validating = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        # ── Header ─────────────────────────────────────────
        header = QHBoxLayout()

        back_btn = QPushButton("← Back")
        back_btn.setFixedWidth(80)
        back_btn.clicked.connect(self._on_back)
        header.addWidget(back_btn)

        title = QLabel("Model Validation")
        title.setObjectName("title")
        header.addWidget(title)

        header.addStretch()

        self._toggle_btn = QPushButton("Start Validation")
        self._toggle_btn.setObjectName("success")
        self._toggle_btn.setMinimumWidth(150)
        self._toggle_btn.clicked.connect(self._toggle_validation)
        header.addWidget(self._toggle_btn)

        layout.addLayout(header)

        # ── Status ─────────────────────────────────────────
        self._status_label = QLabel(
            "Press 'Start Validation' then use your mouse and keyboard normally. "
            "The model will predict your behavior and compare in real-time."
        )
        self._status_label.setObjectName("status")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # ── Splitter: Mouse | Keyboard ─────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Mouse validation panel
        mouse_group = QGroupBox("Mouse Validation")
        mouse_layout = QVBoxLayout(mouse_group)

        self._mouse_score_label = QLabel("Overall: —")
        self._mouse_score_label.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: #e94560; padding: 10px;"
        )
        self._mouse_score_label.setAlignment(Qt.AlignCenter)
        mouse_layout.addWidget(self._mouse_score_label)

        self._mouse_progress = QProgressBar()
        self._mouse_progress.setRange(0, 100)
        self._mouse_progress.setValue(0)
        mouse_layout.addWidget(self._mouse_progress)

        mouse_layout.addWidget(QLabel("Actions validated:"))
        self._mouse_count_label = QLabel("0")
        self._mouse_count_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        mouse_layout.addWidget(self._mouse_count_label)

        mouse_layout.addWidget(QLabel("Recent:"))
        self._mouse_log = QTextEdit()
        self._mouse_log.setReadOnly(True)
        self._mouse_log.setMaximumHeight(200)
        self._mouse_log.setStyleSheet(
            "background-color: #16213e; color: #aaa; font-family: Consolas; font-size: 12px;"
        )
        mouse_layout.addWidget(self._mouse_log)

        mouse_layout.addStretch()
        splitter.addWidget(mouse_group)

        # Keyboard validation panel
        kb_group = QGroupBox("Keyboard Validation")
        kb_layout = QVBoxLayout(kb_group)

        self._kb_score_label = QLabel("Overall: —")
        self._kb_score_label.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: #e94560; padding: 10px;"
        )
        self._kb_score_label.setAlignment(Qt.AlignCenter)
        kb_layout.addWidget(self._kb_score_label)

        self._kb_progress = QProgressBar()
        self._kb_progress.setRange(0, 100)
        self._kb_progress.setValue(0)
        kb_layout.addWidget(self._kb_progress)

        kb_layout.addWidget(QLabel("Transitions validated:"))
        self._kb_count_label = QLabel("0")
        self._kb_count_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        kb_layout.addWidget(self._kb_count_label)

        kb_layout.addWidget(QLabel("Recent:"))
        self._kb_log = QTextEdit()
        self._kb_log.setReadOnly(True)
        self._kb_log.setMaximumHeight(200)
        self._kb_log.setStyleSheet(
            "background-color: #16213e; color: #aaa; font-family: Consolas; font-size: 12px;"
        )
        kb_layout.addWidget(self._kb_log)

        kb_layout.addStretch()
        splitter.addWidget(kb_group)

        layout.addWidget(splitter, stretch=1)

    def _toggle_validation(self):
        if self._validating:
            self._stop_validation()
        else:
            self._start_validation()

    def _start_validation(self):
        self._validating = True
        self._toggle_btn.setText("Stop Validation")
        self._toggle_btn.setObjectName("danger")
        self._toggle_btn.setStyleSheet("")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._status_label.setText("Validating... Use your mouse and keyboard normally.")
        self.start_validation_signal.emit()

    def _stop_validation(self):
        self._validating = False
        self._toggle_btn.setText("Start Validation")
        self._toggle_btn.setObjectName("success")
        self._toggle_btn.setStyleSheet("")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._status_label.setText("Validation stopped.")
        self.stop_validation_signal.emit()

    def _on_back(self):
        if self._validating:
            self._stop_validation()
        self.back_signal.emit()

    # ── Public update methods (called from validation thread) ──

    def update_mouse_score(self, score: float, action_count: int, detail: str):
        """Update mouse validation display."""
        self._mouse_score_label.setText(f"Overall: {score:.1f}%")
        self._mouse_progress.setValue(int(score))
        self._mouse_count_label.setText(str(action_count))
        self._mouse_log.append(detail)
        # Auto-scroll
        sb = self._mouse_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_keyboard_score(self, score: float, transition_count: int, detail: str):
        """Update keyboard validation display."""
        self._kb_score_label.setText(f"Overall: {score:.1f}%")
        self._kb_progress.setValue(int(score))
        self._kb_count_label.setText(str(transition_count))
        self._kb_log.append(detail)
        sb = self._kb_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def reset(self):
        """Reset all validation displays."""
        self._mouse_score_label.setText("Overall: —")
        self._mouse_progress.setValue(0)
        self._mouse_count_label.setText("0")
        self._mouse_log.clear()
        self._kb_score_label.setText("Overall: —")
        self._kb_progress.setValue(0)
        self._kb_count_label.setText("0")
        self._kb_log.clear()

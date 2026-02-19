"""
Click speed calibration dialog.

Measures the user's natural double-click speed by having them
click a button rapidly 20 times. The 95th percentile of inter-click
gaps becomes their personal CLICK_SEQUENCE_GAP_MS threshold.
"""

import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox,
)
from PySide6.QtCore import Qt

import config
from gui.user_settings import save_setting
from utils.system_monitor import get_system_double_click_time


class ClickCalibrationDialog(QDialog):
    """Modal dialog for calibrating click speed."""

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._click_times_ns: list[int] = []
        self._target_clicks = config.CALIBRATION_CLICK_COUNT
        self._result_ms: int | None = None
        self.setWindowTitle("Click Speed Calibration")
        self.setMinimumWidth(450)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("Click Speed Calibration")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            f"Click the button below as fast as you can,\n"
            f"{self._target_clicks} times."
        )
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setObjectName("hint")
        layout.addWidget(instructions)

        # System reference
        sys_dct = get_system_double_click_time()
        ref = QLabel(f"Windows double-click setting: {sys_dct} ms")
        ref.setAlignment(Qt.AlignCenter)
        ref.setObjectName("hint-dim")
        layout.addWidget(ref)

        layout.addSpacing(10)

        # Click target button
        self._click_btn = QPushButton("CLICK HERE")
        self._click_btn.setObjectName("primary")
        self._click_btn.setMinimumHeight(80)
        self._click_btn.setStyleSheet("font-size: 20px; font-weight: bold;")
        self._click_btn.clicked.connect(self._on_click)
        layout.addWidget(self._click_btn)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, self._target_clicks)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._count_label = QLabel(f"0 / {self._target_clicks}")
        self._count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._count_label)

        # Results (hidden until complete)
        self._results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(self._results_group)

        self._result_label = QLabel("")
        self._result_label.setAlignment(Qt.AlignCenter)
        self._result_label.setObjectName("result-value")
        results_layout.addWidget(self._result_label)

        self._detail_label = QLabel("")
        self._detail_label.setAlignment(Qt.AlignCenter)
        self._detail_label.setObjectName("hint-dim")
        results_layout.addWidget(self._detail_label)

        btn_row = QHBoxLayout()
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.clicked.connect(self._reset)
        btn_row.addWidget(self._retry_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("success")
        self._save_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(self._save_btn)
        results_layout.addLayout(btn_row)

        self._results_group.setVisible(False)
        layout.addWidget(self._results_group)

        layout.addStretch()

    def _on_click(self):
        """Record a click timestamp."""
        self._click_times_ns.append(time.perf_counter_ns())
        count = len(self._click_times_ns)
        self._progress.setValue(count)
        self._count_label.setText(f"{count} / {self._target_clicks}")

        if count >= self._target_clicks:
            self._calculate_result()

    def _calculate_result(self):
        """Analyze click intervals and show result."""
        # Calculate inter-click intervals (in ms)
        intervals_ms = []
        for i in range(1, len(self._click_times_ns)):
            gap_ns = self._click_times_ns[i] - self._click_times_ns[i - 1]
            intervals_ms.append(gap_ns / 1_000_000)

        # Discard the first interval (reaction time, not click speed)
        if len(intervals_ms) > 1:
            intervals_ms = intervals_ms[1:]

        # Sort and calculate percentiles
        intervals_ms.sort()
        avg_ms = sum(intervals_ms) / len(intervals_ms)
        min_ms = intervals_ms[0]
        max_ms = intervals_ms[-1]

        # 95th percentile — threshold that covers 95% of the user's clicks
        p95_idx = int(len(intervals_ms) * 0.95)
        p95_ms = intervals_ms[min(p95_idx, len(intervals_ms) - 1)]

        self._result_ms = round(p95_ms)

        # Show results
        self._click_btn.setEnabled(False)
        self._click_btn.setText("Done!")
        self._results_group.setVisible(True)

        self._result_label.setText(f"Your click threshold: {self._result_ms} ms")
        self._detail_label.setText(
            f"Average: {avg_ms:.0f} ms  |  "
            f"Min: {min_ms:.0f} ms  |  "
            f"Max: {max_ms:.0f} ms\n"
            f"95th percentile: {p95_ms:.0f} ms"
        )

    def _reset(self):
        """Reset calibration for another attempt."""
        self._click_times_ns.clear()
        self._result_ms = None
        self._progress.setValue(0)
        self._count_label.setText(f"0 / {self._target_clicks}")
        self._click_btn.setEnabled(True)
        self._click_btn.setText("CLICK HERE")
        self._results_group.setVisible(False)

    def _save_and_close(self):
        """Save calibrated value and close dialog."""
        if self._result_ms is not None:
            save_setting(
                self._user_id,
                "recording.click_sequence_gap_ms",
                str(self._result_ms),
            )
            config.CLICK_SEQUENCE_GAP_MS = self._result_ms
        self.accept()

    @property
    def result_ms(self) -> int | None:
        """The calibrated click gap in ms, or None if not completed."""
        return self._result_ms

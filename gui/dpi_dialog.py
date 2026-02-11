"""
DPI measurement dialog.

Measures mouse DPI by having the user drag across a known physical
distance. The user enters the distance of a reference object (e.g.
credit card width = 8.56 cm), then drags the mouse that same distance.
DPI is calculated from the pixel delta.

Two options: manual entry (if user already knows their DPI) or
interactive measurement.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox,
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QColor

import config
from gui.user_settings import save_setting


class _MeasurementArea(QLabel):
    """
    Widget where the user drags the mouse to measure DPI.

    Press at the start position, release at the end position.
    The horizontal pixel delta is used to calculate DPI.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setStyleSheet(
            "background-color: #16213e; border: 1px solid #0f3460; border-radius: 6px;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setText("Press and drag horizontally across your reference distance")
        self._start_x: float | None = None
        self._end_x: float | None = None
        self._pixel_delta: int | None = None

    def mousePressEvent(self, event):
        self._start_x = event.position().x()
        self._end_x = None
        self._pixel_delta = None
        self.setText(f"Start: {self._start_x:.0f} px — now release at the end")
        self.update()

    def mouseReleaseEvent(self, event):
        if self._start_x is not None:
            self._end_x = event.position().x()
            raw_delta = abs(self._end_x - self._start_x)
            # Account for HiDPI scaling
            self._pixel_delta = round(raw_delta * self.devicePixelRatio())
            self.setText(f"Measured: {self._pixel_delta} pixels")
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        pen = QPen(QColor("#e94560"), 2)
        painter.setPen(pen)

        h = self.height()
        if self._start_x is not None:
            x = round(self._start_x)
            painter.drawLine(x, 10, x, h - 10)

        if self._end_x is not None:
            x = round(self._end_x)
            painter.drawLine(x, 10, x, h - 10)

        painter.end()

    @property
    def pixel_delta(self) -> int | None:
        return self._pixel_delta

    def reset(self):
        self._start_x = None
        self._end_x = None
        self._pixel_delta = None
        self.setText("Press and drag horizontally across your reference distance")
        self.update()


class DpiMeasurementDialog(QDialog):
    """Modal dialog for measuring mouse DPI."""

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._result_dpi: int | None = None
        self.setWindowTitle("Measure Mouse DPI")
        self.setFixedSize(500, 480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)

        # Title
        title = QLabel("Mouse DPI Measurement")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "Place a physical object (e.g. credit card, ruler) next to your screen.\n"
            "Enter its width below, then drag the mouse across that same distance."
        )
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setWordWrap(True)
        instructions.setStyleSheet("font-size: 13px; color: #aaa;")
        layout.addWidget(instructions)

        # Distance input
        dist_row = QHBoxLayout()
        dist_row.addWidget(QLabel("Reference distance:"))
        self._distance_spin = QDoubleSpinBox()
        self._distance_spin.setRange(1.0, 50.0)
        self._distance_spin.setValue(8.56)  # Credit card width
        self._distance_spin.setSuffix(" cm")
        self._distance_spin.setDecimals(2)
        dist_row.addWidget(self._distance_spin)
        layout.addLayout(dist_row)

        # Measurement area
        layout.addWidget(QLabel("Drag here:"))
        self._area = _MeasurementArea()
        layout.addWidget(self._area)

        # Calculate button
        calc_btn = QPushButton("Calculate DPI")
        calc_btn.setObjectName("primary")
        calc_btn.clicked.connect(self._calculate)
        layout.addWidget(calc_btn)

        # Results (hidden until calculated)
        self._results_group = QGroupBox("Result")
        results_layout = QVBoxLayout(self._results_group)

        self._result_label = QLabel("")
        self._result_label.setAlignment(Qt.AlignCenter)
        self._result_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #e94560;")
        results_layout.addWidget(self._result_label)

        self._detail_label = QLabel("")
        self._detail_label.setAlignment(Qt.AlignCenter)
        self._detail_label.setStyleSheet("font-size: 12px; color: #aaa;")
        results_layout.addWidget(self._detail_label)

        btn_row = QHBoxLayout()
        retry_btn = QPushButton("Retry")
        retry_btn.clicked.connect(self._reset)
        btn_row.addWidget(retry_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("success")
        self._save_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(self._save_btn)
        results_layout.addLayout(btn_row)

        self._results_group.setVisible(False)
        layout.addWidget(self._results_group)

        layout.addStretch()

    def _calculate(self):
        """Calculate DPI from pixel delta and physical distance."""
        pixel_delta = self._area.pixel_delta
        if pixel_delta is None or pixel_delta < 10:
            self._result_label.setText("Drag the mouse first!")
            self._results_group.setVisible(True)
            self._save_btn.setEnabled(False)
            return

        distance_cm = self._distance_spin.value()
        distance_inches = distance_cm / 2.54
        dpi = round(pixel_delta / distance_inches)

        self._result_dpi = dpi
        self._results_group.setVisible(True)
        self._save_btn.setEnabled(True)

        self._result_label.setText(f"Measured DPI: {dpi}")
        self._detail_label.setText(
            f"Pixels moved: {pixel_delta}  |  "
            f"Distance: {distance_cm:.2f} cm ({distance_inches:.2f} in)"
        )

    def _reset(self):
        """Reset measurement for another attempt."""
        self._area.reset()
        self._result_dpi = None
        self._results_group.setVisible(False)

    def _save_and_close(self):
        """Save measured DPI and close dialog."""
        if self._result_dpi is not None:
            save_setting(self._user_id, "system.dpi", str(self._result_dpi))
            config.USER_DPI = self._result_dpi
        self.accept()

    @property
    def result_dpi(self) -> int | None:
        """The measured DPI, or None if not completed."""
        return self._result_dpi

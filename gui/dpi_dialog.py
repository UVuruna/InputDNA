"""
DPI measurement dialog.

Measures mouse DPI by having the user drag across a known physical
distance. Uses Windows Raw Input API to capture actual mouse sensor
counts, bypassing OS pointer speed and Enhanced Pointer Precision.

Two options: manual entry (if user already knows their DPI) or
interactive measurement.
"""

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox, QApplication,
)
from PySide6.QtCore import Qt, QAbstractNativeEventFilter
from PySide6.QtGui import QPainter, QPen, QColor

import config
from gui.user_settings import save_setting

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Win32 Raw Input API
# ─────────────────────────────────────────────────────────────

_user32 = ctypes.windll.user32

WM_INPUT = 0x00FF
RIM_TYPEMOUSE = 0
RID_INPUT = 0x10000003
RIDEV_REMOVE = 0x00000001


class _RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage", ctypes.c_ushort),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class _RAWMOUSE(ctypes.Structure):
    # usFlags → ulButtons has 2 bytes padding (ctypes handles alignment)
    _fields_ = [
        ("usFlags", ctypes.c_ushort),
        ("ulButtons", wintypes.ULONG),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class _RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", _RAWINPUTHEADER),
        ("mouse", _RAWMOUSE),
    ]


_SIZEOF_HEADER = ctypes.sizeof(_RAWINPUTHEADER)


def _register_raw_mouse(hwnd: int) -> bool:
    """Register window to receive WM_INPUT for mouse. Returns success."""
    rid = _RAWINPUTDEVICE()
    rid.usUsagePage = 0x01  # HID_USAGE_PAGE_GENERIC
    rid.usUsage = 0x02      # HID_USAGE_GENERIC_MOUSE
    rid.dwFlags = 0
    rid.hwndTarget = hwnd
    ok = _user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid))
    if not ok:
        logger.error("RegisterRawInputDevices failed")
    return bool(ok)


def _unregister_raw_mouse():
    """Stop receiving WM_INPUT for mouse."""
    rid = _RAWINPUTDEVICE()
    rid.usUsagePage = 0x01
    rid.usUsage = 0x02
    rid.dwFlags = RIDEV_REMOVE
    rid.hwndTarget = 0
    _user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid))


class _RawMouseAccumulator(QAbstractNativeEventFilter):
    """
    Native event filter that captures raw mouse X deltas from WM_INPUT.

    Raw input bypasses Windows pointer speed and Enhanced Pointer Precision,
    giving actual mouse sensor counts — same approach as mousedpianalyzer.com.
    """

    def __init__(self):
        super().__init__()
        self._capturing = False
        self._dx_sum = 0

    def nativeEventFilter(self, eventType, message):
        if self._capturing and eventType == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_INPUT:
                    self._process(msg.lParam)
            except (ValueError, OSError):
                pass
        return False

    def _process(self, lParam):
        size = wintypes.UINT()
        _user32.GetRawInputData(lParam, RID_INPUT, None, ctypes.byref(size), _SIZEOF_HEADER)
        if size.value == 0:
            return
        buf = (ctypes.c_byte * size.value)()
        result = _user32.GetRawInputData(lParam, RID_INPUT, buf, ctypes.byref(size), _SIZEOF_HEADER)
        if result == 0xFFFFFFFF:  # (UINT)-1 = error
            return
        raw = _RAWINPUT.from_buffer_copy(buf)
        # Only accumulate relative mouse moves (usFlags bit 0 = MOUSE_MOVE_ABSOLUTE)
        if raw.header.dwType == RIM_TYPEMOUSE and (raw.mouse.usFlags & 0x01) == 0:
            self._dx_sum += abs(raw.mouse.lLastX)

    def start(self):
        """Start accumulating raw X deltas."""
        self._dx_sum = 0
        self._capturing = True

    def stop(self) -> int:
        """Stop accumulating, return total raw X counts."""
        self._capturing = False
        return self._dx_sum


# ─────────────────────────────────────────────────────────────
# Measurement area widget
# ─────────────────────────────────────────────────────────────

class _MeasurementArea(QLabel):
    """
    Widget where the user drags the mouse to measure DPI.

    On press: starts raw input accumulation.
    On release: stops accumulation, displays raw count.
    Visual markers show drag start/end positions.
    """

    def __init__(self, accumulator: _RawMouseAccumulator, parent=None):
        super().__init__(parent)
        self._acc = accumulator
        self.setMinimumHeight(120)
        self.setStyleSheet(
            "background-color: #16213e; border: 1px solid #0f3460; border-radius: 6px;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setText("Press and drag horizontally across your reference distance")
        self._start_x: float | None = None
        self._end_x: float | None = None
        self._raw_counts: int | None = None

    def mousePressEvent(self, event):
        self._start_x = event.position().x()
        self._end_x = None
        self._raw_counts = None
        self._acc.start()
        self.setText("Dragging — release at the end")
        self.update()

    def mouseReleaseEvent(self, event):
        if self._start_x is not None:
            self._end_x = event.position().x()
            self._raw_counts = self._acc.stop()
            self.setText(f"Measured: {self._raw_counts} raw counts")
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
    def raw_counts(self) -> int | None:
        return self._raw_counts

    def reset(self):
        self._start_x = None
        self._end_x = None
        self._raw_counts = None
        self.setText("Press and drag horizontally across your reference distance")
        self.update()


# ─────────────────────────────────────────────────────────────
# DPI measurement dialog
# ─────────────────────────────────────────────────────────────

class DpiMeasurementDialog(QDialog):
    """Modal dialog for measuring mouse DPI via raw input."""

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._result_dpi: int | None = None
        self.setWindowTitle("Measure Mouse DPI")
        self.setMinimumWidth(500)

        self._accumulator = _RawMouseAccumulator()
        QApplication.instance().installNativeEventFilter(self._accumulator)

        self._build_ui()

        # Register after winId() exists (layout triggers native window creation)
        _register_raw_mouse(int(self.winId()))

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
        self._area = _MeasurementArea(self._accumulator)
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
        """Calculate DPI from raw mouse counts and physical distance."""
        raw_counts = self._area.raw_counts
        if raw_counts is None or raw_counts < 10:
            self._result_label.setText("Drag the mouse first!")
            self._results_group.setVisible(True)
            self._save_btn.setEnabled(False)
            return

        distance_cm = self._distance_spin.value()
        distance_inches = distance_cm / 2.54
        dpi = round(raw_counts / distance_inches)

        self._result_dpi = dpi
        self._results_group.setVisible(True)
        self._save_btn.setEnabled(True)

        self._result_label.setText(f"Measured DPI: {dpi}")
        self._detail_label.setText(
            f"Raw counts: {raw_counts}  |  "
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

    def done(self, result):
        """Clean up raw input registration on dialog close."""
        _unregister_raw_mouse()
        QApplication.instance().removeNativeEventFilter(self._accumulator)
        super().done(result)

    @property
    def result_dpi(self) -> int | None:
        """The measured DPI, or None if not completed."""
        return self._result_dpi

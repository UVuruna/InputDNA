"""
Shared QSS stylesheet for the application.
Dark theme consistent with Aviator application.
"""

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #eee;
    font-family: "Segoe UI", sans-serif;
    font-size: 14px;
}

QLabel {
    color: #eee;
}

QLabel#title {
    font-size: 24px;
    font-weight: bold;
    color: #e94560;
    padding: 10px;
}

QLabel#subtitle {
    font-size: 16px;
    color: #aaa;
    padding: 5px;
}

QLabel#status {
    font-size: 13px;
    color: #aaa;
    padding: 8px;
    background-color: #16213e;
    border-radius: 6px;
}

QLabel#status-recording {
    font-size: 13px;
    color: #22c55e;
    padding: 8px;
    background-color: #16213e;
    border-radius: 6px;
}

QLineEdit, QDateEdit {
    background-color: #16213e;
    color: #eee;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 10px;
    font-size: 14px;
}

QLineEdit:focus, QDateEdit:focus {
    border: 1px solid #e94560;
}

QPushButton {
    background-color: #0f3460;
    color: #eee;
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: bold;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #1a4a8a;
}

QPushButton:pressed {
    background-color: #0a2540;
}

QPushButton#primary {
    background-color: #e94560;
}

QPushButton#primary:hover {
    background-color: #ff6b81;
}

QPushButton#primary:pressed {
    background-color: #c0392b;
}

QPushButton#success {
    background-color: #22c55e;
    color: #000;
}

QPushButton#success:hover {
    background-color: #4ade80;
}

QPushButton#danger {
    background-color: #ef4444;
}

QPushButton#danger:hover {
    background-color: #f87171;
}

QPushButton:disabled {
    background-color: #333;
    color: #666;
}

QTabWidget::pane {
    border: 1px solid #0f3460;
    background-color: #1a1a2e;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: #16213e;
    color: #aaa;
    padding: 10px 30px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #0f3460;
    color: #eee;
}

QGroupBox {
    border: 1px solid #0f3460;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 20px;
    font-weight: bold;
    color: #aaa;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 5px;
}

QProgressBar {
    border: 1px solid #0f3460;
    border-radius: 6px;
    background-color: #16213e;
    text-align: center;
    color: #eee;
    height: 24px;
}

QProgressBar::chunk {
    background-color: #e94560;
    border-radius: 5px;
}

QComboBox {
    background-color: #16213e;
    color: #eee;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    min-width: 120px;
}

QComboBox:hover {
    border: 1px solid #e94560;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #aaa;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #16213e;
    color: #eee;
    selection-background-color: #0f3460;
    selection-color: #eee;
    border: 1px solid #0f3460;
}

QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background-color: #16213e;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #e94560;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: #ff6b81;
}

QSlider::sub-page:horizontal {
    background-color: #e94560;
    border-radius: 3px;
}

QSpinBox, QDoubleSpinBox {
    background-color: #16213e;
    color: #eee;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #e94560;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #0f3460;
    border: none;
    width: 20px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #1a4a8a;
}

QCheckBox {
    spacing: 8px;
    color: #eee;
    font-size: 14px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid #0f3460;
    border-radius: 4px;
    background-color: #16213e;
}

QCheckBox::indicator:checked {
    background-color: #e94560;
    border-color: #e94560;
}

QCheckBox::indicator:hover {
    border-color: #e94560;
}

QKeySequenceEdit {
    background-color: #16213e;
    color: #eee;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}

QKeySequenceEdit:focus {
    border: 1px solid #e94560;
}
"""

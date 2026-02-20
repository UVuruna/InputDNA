"""
Theme system — dark and light palettes based on InputDNA SVG brand colors.

Three brand color families from support/logo/*/UV-InputDNA.svg:
  Pink   (#d83a95, #862065)  — text accents: titles, stats, results
  Purple (#6371d7, #343d80)  — primary actions: buttons, checkboxes
  Cyan   (#4cc4e4, #65cbe9)  — state feedback: focus, progress, sliders
"""

from string import Template

from ui.tray_icon import detect_windows_theme

# ── Color palettes ────────────────────────────────────────────

DARK_PALETTE = {
    # Backgrounds (darkest SVG blues)
    "bg":               "#031520",
    "bg_alt":           "#082433",
    "bg_button":        "#0f384d",
    "bg_hover":         "#195370",
    "bg_pressed":       "#000c14",
    "border":           "#18526f",
    # Brand: Pink (text accents — titles, stats, results)
    "accent":           "#d83a95",
    "accent_hover":     "#e55aab",   # minor correction (lighter than #d83a95)
    "accent_pressed":   "#862065",
    # Brand: Purple (primary action buttons, checkboxes, selections)
    "primary":          "#6371d7",
    "primary_hover":    "#7b87e0",   # minor correction (lighter than #6371d7)
    "primary_pressed":  "#343d80",
    "primary_text":     "#eef7fe",
    # Brand: Cyan (focus rings, progress bars, sliders)
    "highlight":        "#4cc4e4",
    "highlight_hover":  "#65cbe9",
    # Text (lightest SVG blues)
    "text":             "#eef7fe",
    "text_muted":       "#adcad9",
    "text_dim":         "#6e9eb4",
    "text_disabled":    "#3b7b97",
    # Button text
    "btn_text":         "#eef7fe",
    "success_text":     "#000000",
    "danger_text":      "#eef7fe",
    # Status colors (standard)
    "success":          "#22c55e",
    "success_hover":    "#4ade80",
    "danger":           "#ef4444",
    "danger_hover":     "#f87171",
    # Disabled
    "disabled_bg":      "#1e2a50",   # minor correction (between #0f384d and #082433)
    "disabled_text":    "#3b7b97",
    # Combo arrow / subtle indicators
    "indicator":        "#adcad9",
}

LIGHT_PALETTE = {
    # Backgrounds (lightest SVG blues → near white)
    "bg":               "#eef7fe",
    "bg_alt":           "#e4f0f8",
    "bg_button":        "#90b6c8",   # darker blue-grey for visible buttons
    "bg_hover":         "#6e9eb4",   # darker on hover
    "bg_pressed":       "#47839d",   # darkest on press
    "border":           "#adcad9",
    # Brand: Dark Blue (text accents — titles, stats, results)
    "accent":           "#004c6f",
    "accent_hover":     "#0a5aa0",
    "accent_pressed":   "#031520",
    # Brand: Dark Purple (primary action buttons, checkboxes, selections)
    "primary":          "#343d80",
    "primary_hover":    "#6371d7",
    "primary_pressed":  "#252c6e",   # minor correction (darker than #343d80)
    "primary_text":     "#eef7fe",
    # Brand: Dark Pink (focus rings, progress bars, sliders)
    "highlight":        "#862065",
    "highlight_hover":  "#d83a95",
    # Text (darkest SVG blues)
    "text":             "#031520",
    "text_muted":       "#0f384d",
    "text_dim":         "#47839d",
    "text_disabled":    "#90b6c8",
    # Button text
    "btn_text":         "#031520",   # dark text on light blue-grey buttons
    "success_text":     "#000000",
    "danger_text":      "#eef7fe",
    # Status colors (standard)
    "success":          "#22c55e",
    "success_hover":    "#4ade80",
    "danger":           "#ef4444",
    "danger_hover":     "#f87171",
    # Disabled
    "disabled_bg":      "#d7e7f1",
    "disabled_text":    "#90b6c8",
    # Combo arrow / subtle indicators
    "indicator":        "#47839d",
}


# ── QSS template ──────────────────────────────────────────────
# Uses $variable substitution from the palette dicts above.
#
# Dark palette color mapping:
#   $accent*    → Pink  (#d83a95) — text accents (titles, stat labels, results)
#   $primary*   → Purple (#6371d7) — primary buttons, checkboxes, calendar selection
#   $highlight* → Cyan  (#4cc4e4) — focus borders, progress bars, sliders, combo hover
#
# Light palette color mapping:
#   $accent*    → Dark Blue (#004c6f) — text accents (titles, stat labels, results)
#   $primary*   → Dark Purple (#343d80) — primary buttons, checkboxes, calendar selection
#   $highlight* → Dark Pink (#862065) — focus borders, progress bars, sliders, combo hover

_QSS_TEMPLATE = Template("""
/* ── Base ──────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: $bg;
    color: $text;
    font-family: "Segoe UI", sans-serif;
    font-size: 14px;
}

QLabel {
    color: $text;
}

QLabel#title {
    font-size: 24px;
    font-weight: bold;
    color: $accent;
    padding: 10px;
}

QLabel#subtitle {
    font-size: 16px;
    color: $text_muted;
    padding: 5px;
}

QLabel#status {
    font-size: 13px;
    color: $text_muted;
    padding: 8px;
    background-color: $bg_alt;
    border-radius: 6px;
}

QWidget#status-bar {
    background-color: $bg_alt;
    border-radius: 6px;
}

QWidget#status-bar QLabel {
    background-color: transparent;
}

QLabel#status-text {
    font-size: 13px;
    color: $text_muted;
}

QLabel#status-recording {
    font-size: 13px;
    color: $success;
}

QLabel#status-detail {
    font-size: 13px;
    color: $text_dim;
}

/* ── Stat/info labels (Pink accent) ──────────────────────── */
QLabel#stat-value {
    font-size: 18px;
    font-weight: bold;
    color: $accent;
}

QLabel#stat-sub-label {
    font-size: 14px;
    color: $text_dim;
}

QLabel#stat-sub-value {
    font-size: 18px;
    font-weight: bold;
    color: $accent;
}

QLabel#stat-nav {
    font-size: 13px;
    font-weight: bold;
    color: $highlight;
}

QPushButton#stat-arrow {
    background-color: transparent;
    color: $highlight;
    font-size: 16px;
    font-weight: bold;
    padding: 2px 8px;
    min-height: 16px;
    border: none;
    border-radius: 4px;
}

QPushButton#stat-arrow:hover {
    background-color: $bg_button;
}

QLabel#info-value {
    font-size: 13px;
    font-weight: bold;
    color: $accent;
}

QLabel#hint {
    font-size: 14px;
    color: $text_muted;
}

QLabel#hint-small {
    font-size: 13px;
    color: $text_muted;
}

QLabel#hint-dim {
    font-size: 12px;
    color: $text_dim;
}

QLabel#result-value {
    font-size: 16px;
    font-weight: bold;
    color: $accent;
}

QLabel#result-value-large {
    font-size: 18px;
    font-weight: bold;
    color: $accent;
}

QLabel#score-value {
    font-size: 28px;
    font-weight: bold;
    color: $accent;
    padding: 10px;
}

QLabel#count-value {
    font-size: 16px;
    font-weight: bold;
}

/* ── Log areas ────────────────────────────────────────────── */
QTextEdit#log-area {
    background-color: $bg_alt;
    color: $text_muted;
    font-family: Consolas, monospace;
    font-size: 12px;
}

/* ── Drag measurement area ────────────────────────────────── */
QLabel#drag-area {
    background-color: $bg_alt;
    border: 1px solid $border;
    border-radius: 6px;
}

/* ── Inputs (Cyan focus) ─────────────────────────────────── */
QLineEdit, QDateEdit {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 10px;
    font-size: 14px;
}

QDateEdit {
    padding: 6px 4px;
}

QLineEdit:focus, QDateEdit:focus {
    border: 1px solid $highlight;
}

/* ── Buttons (Purple primary) ────────────────────────────── */
QPushButton {
    background-color: $bg_button;
    color: $btn_text;
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: bold;
    min-height: 20px;
}

QPushButton:hover {
    background-color: $bg_hover;
}

QPushButton:pressed {
    background-color: $bg_pressed;
}

QPushButton#primary {
    background-color: $primary;
    color: $primary_text;
}

QPushButton#primary:hover {
    background-color: $primary_hover;
}

QPushButton#primary:pressed {
    background-color: $primary_pressed;
}

QPushButton#success {
    background-color: $success;
    color: $success_text;
}

QPushButton#success:hover {
    background-color: $success_hover;
}

QPushButton#danger {
    background-color: $danger;
    color: $danger_text;
}

QPushButton#danger:hover {
    background-color: $danger_hover;
}

QPushButton:disabled,
QPushButton#primary:disabled,
QPushButton#success:disabled,
QPushButton#danger:disabled {
    background-color: $disabled_bg;
    color: $disabled_text;
}

/* ── Tabs ─────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid $border;
    background-color: $bg;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: $bg_alt;
    color: $text_muted;
    padding: 10px 30px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: $bg_button;
    color: $text;
}

/* ── Group boxes ──────────────────────────────────────────── */
QGroupBox {
    border: 1px solid $border;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 20px;
    font-weight: bold;
    color: $text_muted;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 5px;
}

/* ── Progress bar (Cyan) ─────────────────────────────────── */
QProgressBar {
    border: 1px solid $border;
    border-radius: 6px;
    background-color: $bg_alt;
    text-align: center;
    color: $text;
    height: 24px;
}

QProgressBar::chunk {
    background-color: $highlight;
    border-radius: 5px;
}

/* ── Combo box (Cyan hover) ──────────────────────────────── */
QComboBox {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    min-width: 120px;
}

QComboBox:hover {
    border: 1px solid $highlight;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid $indicator;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: $bg_alt;
    color: $text;
    selection-background-color: $bg_button;
    selection-color: $text;
    border: 1px solid $border;
}

/* ── Slider (Cyan) ───────────────────────────────────────── */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background-color: $bg_alt;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: $highlight;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: $highlight_hover;
}

QSlider::sub-page:horizontal {
    background-color: $highlight;
    border-radius: 3px;
}

/* ── Spin boxes (Cyan focus) ─────────────────────────────── */
QSpinBox, QDoubleSpinBox {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid $highlight;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: $bg_button;
    border: none;
    width: 20px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: $bg_hover;
}

/* ── Checkbox (Purple) ───────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: $text;
    font-size: 14px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid $border;
    border-radius: 4px;
    background-color: $bg_alt;
}

QCheckBox::indicator:checked {
    background-color: $primary;
    border-color: $primary;
}

QCheckBox::indicator:hover {
    border-color: $highlight;
}

/* ── Key sequence edit (Cyan focus) ──────────────────────── */
QKeySequenceEdit {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}

QKeySequenceEdit:focus {
    border: 1px solid $highlight;
}

/* ── Button focus indicator removal ───────────────────────── */
QPushButton:focus {
    border: none;
    outline: none;
}

QPushButton#primary:focus {
    border: none;
    outline: none;
}

QPushButton#success:focus {
    border: none;
    outline: none;
}

QPushButton#danger:focus {
    border: none;
    outline: none;
}

/* ── Calendar popup (Purple selection) ───────────────────── */
QCalendarWidget {
    background-color: $bg;
    color: $text;
}

QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: $bg_alt;
    padding: 4px;
}

QCalendarWidget QToolButton {
    background-color: $bg_alt;
    color: $text;
    border: none;
    padding: 6px;
    font-size: 14px;
    font-weight: bold;
}

QCalendarWidget QToolButton:hover {
    background-color: $bg_button;
}

QCalendarWidget QToolButton::menu-indicator {
    image: none;
}

QCalendarWidget QSpinBox {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 14px;
    selection-background-color: $primary;
    selection-color: $primary_text;
}

QCalendarWidget QSpinBox::up-button,
QCalendarWidget QSpinBox::down-button {
    background-color: $bg_button;
    border: none;
    width: 18px;
}

QCalendarWidget QSpinBox::up-button:hover,
QCalendarWidget QSpinBox::down-button:hover {
    background-color: $bg_hover;
}

QCalendarWidget QMenu {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
}

QCalendarWidget QMenu::item:selected {
    background-color: $bg_button;
    color: $text;
}

QCalendarWidget QAbstractItemView {
    background-color: $bg;
    color: $text;
    selection-background-color: $primary;
    selection-color: $primary_text;
    border: 1px solid $border;
    outline: none;
}

QCalendarWidget QAbstractItemView:enabled {
    color: $text;
}

QCalendarWidget QAbstractItemView:disabled {
    color: $text_disabled;
}

/* ── Readme viewer ───────────────────────────────────────── */
QWidget#readme-nav {
    background-color: $bg_alt;
    border-bottom: 1px solid $border;
}

/* ── Scroll area ──────────────────────────────────────────── */
QScrollArea {
    background-color: $bg;
    border: none;
}

/* ── Splitter ─────────────────────────────────────────────── */
QSplitter::handle {
    background-color: $border;
}

/* ── Message box ──────────────────────────────────────────── */
QMessageBox {
    background-color: $bg;
}

QMessageBox QLabel {
    color: $text;
}
""")


# ── Pre-built stylesheets ─────────────────────────────────────

DARK_STYLE = _QSS_TEMPLATE.substitute(DARK_PALETTE)
LIGHT_STYLE = _QSS_TEMPLATE.substitute(LIGHT_PALETTE)


# ── Theme resolver ────────────────────────────────────────────

def get_stylesheet(theme: str) -> str:
    """Return QSS for the given theme name.

    Args:
        theme: "dark", "light", or "auto" (follow Windows setting).
    """
    if theme == "light":
        return LIGHT_STYLE
    if theme == "auto":
        win_theme = detect_windows_theme()
        return LIGHT_STYLE if win_theme == "light" else DARK_STYLE
    # Default to dark
    return DARK_STYLE

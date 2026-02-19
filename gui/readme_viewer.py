"""
Markdown documentation viewer.

Full-screen widget for browsing project documentation (.md files).
Accessible from the login screen via the Readme button.

Uses QWebEngineView (Chromium) with Python's markdown library for
rendering. Supports Mermaid diagrams (via CDN), internal .md links,
back/forward navigation, and theme-aware styling.
"""

import re
import logging
import webbrowser
from pathlib import Path
from string import Template

import markdown

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Signal, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage

from gui.styles import DARK_PALETTE, LIGHT_PALETTE
from gui.global_settings import load_globals
from ui.tray_icon import detect_windows_theme

logger = logging.getLogger(__name__)


# ── HTML template ─────────────────────────────────────────────
# Full CSS3 via Chromium. Uses $variable substitution (like styles.py).

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="color-scheme" content="$color_scheme">
<style>
body {
    background-color: $bg;
    color: $text;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px 40px;
    word-wrap: break-word;
}

h1 {
    color: $accent;
    font-size: 2em;
    border-bottom: 1px solid $border;
    padding-bottom: 0.3em;
    margin-top: 24px;
}

h2 {
    color: $accent;
    font-size: 1.5em;
    border-bottom: 1px solid $border;
    padding-bottom: 0.3em;
    margin-top: 24px;
}

h3 {
    color: $accent;
    font-size: 1.25em;
    margin-top: 24px;
}

h4, h5, h6 {
    color: $text_muted;
    margin-top: 20px;
}

a {
    color: $highlight;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

code {
    background-color: rgba(110, 118, 129, 0.25);
    border-radius: 4px;
    padding: 0.2em 0.4em;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 85%;
}

pre {
    background-color: $bg_alt;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 16px;
    overflow: auto;
    line-height: 1.45;
}

pre code {
    background: transparent;
    padding: 0;
    border-radius: 0;
    font-size: 85%;
}

table {
    border-collapse: collapse;
    margin: 16px 0;
    display: block;
    overflow-x: auto;
}

th, td {
    padding: 8px 16px;
    border: 1px solid $border;
}

th {
    background-color: $bg_alt;
    font-weight: 600;
}

blockquote {
    border-left: 4px solid $highlight;
    padding: 0.5em 1em;
    margin: 16px 0;
    color: $text_muted;
}

blockquote > :first-child { margin-top: 0; }
blockquote > :last-child { margin-bottom: 0; }

img {
    max-width: 100%;
    height: auto;
}

hr {
    border: none;
    border-top: 1px solid $border;
    margin: 24px 0;
}

details {
    border: 1px solid $border;
    border-radius: 6px;
    padding: 8px 16px;
    margin: 8px 0;
}

summary {
    cursor: pointer;
    font-weight: 600;
    color: $highlight;
}

ul, ol {
    padding-left: 2em;
}

li + li {
    margin-top: 0.25em;
}

.mermaid {
    background-color: $bg_alt;
    border-radius: 6px;
    padding: 16px;
    text-align: center;
    margin: 16px 0;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: $bg; }
::-webkit-scrollbar-thumb { background: $border; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: $text_dim; }
</style>
</head>
<body>
$content

<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({
    startOnLoad: true,
    theme: '$mermaid_theme',
    themeVariables: {
        primaryColor: '$primary',
        primaryTextColor: '$text',
        primaryBorderColor: '$border',
        lineColor: '$text_dim',
        secondaryColor: '$bg_alt',
        tertiaryColor: '$bg_alt',
        background: '$bg',
        mainBkg: '$bg_alt',
        nodeBorder: '$border',
        clusterBkg: '$bg_alt',
        clusterBorder: '$border',
        titleColor: '$accent',
        edgeLabelBackground: '$bg_alt',
        fontSize: '14px'
    }
});
</script>
</body>
</html>""")


# ── Custom web page for link interception ─────────────────────


class _MarkdownPage(QWebEnginePage):
    """Intercepts link clicks to handle .md files internally."""

    def __init__(self, link_callback, parent=None):
        super().__init__(parent)
        self._link_callback = link_callback

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True

        # External URLs: open in system browser
        if url.scheme() in ("http", "https"):
            webbrowser.open(url.toString())
            return False

        # Local .md file links: load internally
        if url.path().endswith(".md"):
            if self._link_callback:
                QTimer.singleShot(0, lambda u=url: self._link_callback(u))
            return False

        # Everything else (fragment scrolls, etc.): let Chromium handle
        return True


# ── Main viewer widget ────────────────────────────────────────


class ReadmeViewer(QWidget):
    """Markdown documentation viewer with back/forward navigation.

    Uses QWebEngineView (Chromium) for full HTML5/CSS3 rendering.
    Links to .md files load internally; external URLs open in the
    system browser. Mermaid diagrams rendered via CDN.
    """

    back_signal = Signal()

    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self._project_root = project_root
        self._current_file: Path | None = None
        self._history: list[Path] = []
        self._forward_history: list[Path] = []
        self._md = markdown.Markdown(
            extensions=["tables", "fenced_code", "toc"],
        )
        self._build_ui()
        self._load_file(project_root / "README.md", add_to_history=False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Navigation bar ────────────────────────────────────
        nav_widget = QWidget()
        nav_widget.setObjectName("readme-nav")
        nav = QHBoxLayout(nav_widget)
        nav.setContentsMargins(12, 8, 12, 8)
        nav.setSpacing(8)

        back_btn = QPushButton("\u2190 Back")
        back_btn.setToolTip("Return to login screen")
        back_btn.clicked.connect(self.back_signal.emit)
        nav.addWidget(back_btn)

        nav.addSpacing(8)

        self._hist_back_btn = QPushButton("\u25C0")
        self._hist_back_btn.setToolTip("Previous document")
        self._hist_back_btn.setObjectName("stat-arrow")
        self._hist_back_btn.clicked.connect(self._go_back)
        self._hist_back_btn.setEnabled(False)
        nav.addWidget(self._hist_back_btn)

        self._hist_fwd_btn = QPushButton("\u25B6")
        self._hist_fwd_btn.setToolTip("Next document")
        self._hist_fwd_btn.setObjectName("stat-arrow")
        self._hist_fwd_btn.clicked.connect(self._go_forward)
        self._hist_fwd_btn.setEnabled(False)
        nav.addWidget(self._hist_fwd_btn)

        nav.addSpacing(8)

        self._file_label = QLabel("")
        self._file_label.setObjectName("hint-small")
        nav.addWidget(self._file_label, 1)

        home_btn = QPushButton("Home")
        home_btn.setToolTip("Go to README.md")
        home_btn.clicked.connect(self.load_readme)
        nav.addWidget(home_btn)

        layout.addWidget(nav_widget, 0)

        # ── Web engine view ───────────────────────────────────
        self._web_view = QWebEngineView()
        self._web_page = _MarkdownPage(self._on_link_click, self._web_view)
        self._web_view.setPage(self._web_page)
        layout.addWidget(self._web_view, 1)

    # ── Public methods ────────────────────────────────────────

    def load_readme(self):
        """Load main README.md and reset navigation history."""
        self._load_file(
            self._project_root / "README.md", add_to_history=False,
        )
        self._history.clear()
        self._forward_history.clear()
        self._update_nav_buttons()

    # ── File loading ──────────────────────────────────────────

    def _load_file(self, file_path: Path, add_to_history: bool = True):
        """Load and render a markdown file."""
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            self._web_view.setHtml(
                f"<p style='color:red;'>File not found: {file_path}</p>"
            )
            return

        # History management
        if add_to_history and self._current_file:
            self._history.append(self._current_file)
            self._forward_history.clear()

        self._current_file = file_path

        # Read markdown, preprocess mermaid, convert to HTML
        content = file_path.read_text(encoding="utf-8")
        content = _preprocess_mermaid(content)
        self._md.reset()
        html_body = self._md.convert(content)

        # Wrap in styled HTML with current theme palette
        palette = _current_palette()
        full_html = _HTML_TEMPLATE.substitute(**palette, content=html_body)

        # Base URL for relative resource resolution (images, etc.)
        base_url = QUrl.fromLocalFile(str(file_path.parent) + "/")
        self._web_view.setHtml(full_html, base_url)

        # Update navigation UI
        try:
            rel_path = file_path.relative_to(self._project_root)
        except ValueError:
            rel_path = file_path.name
        self._file_label.setText(str(rel_path))
        self._update_nav_buttons()

    # ── Link handling ─────────────────────────────────────────

    def _on_link_click(self, url: QUrl):
        """Handle .md link click (called from _MarkdownPage)."""
        target = Path(url.toLocalFile())
        fragment = url.fragment()

        if target.exists():
            self._load_file(target)
            if fragment:
                js = f"document.getElementById('{fragment}')?.scrollIntoView();"
                QTimer.singleShot(
                    200, lambda: self._web_view.page().runJavaScript(js),
                )
        else:
            logger.warning(f"Linked file not found: {target}")

    # ── Navigation history ────────────────────────────────────

    def _go_back(self):
        """Navigate back to previous document in history."""
        if self._history:
            if self._current_file:
                self._forward_history.append(self._current_file)
            prev_file = self._history.pop()
            self._load_file(prev_file, add_to_history=False)
            self._update_nav_buttons()

    def _go_forward(self):
        """Navigate forward to next document in history."""
        if self._forward_history:
            if self._current_file:
                self._history.append(self._current_file)
            next_file = self._forward_history.pop()
            self._load_file(next_file, add_to_history=False)
            self._update_nav_buttons()

    def _update_nav_buttons(self):
        """Enable/disable back/forward buttons based on history state."""
        self._hist_back_btn.setEnabled(bool(self._history))
        self._hist_fwd_btn.setEnabled(bool(self._forward_history))


# ── Helpers ───────────────────────────────────────────────────


def _preprocess_mermaid(content: str) -> str:
    """Convert ```mermaid code blocks to <div class="mermaid">.

    Must run BEFORE markdown conversion so mermaid.js can find them.
    """
    return re.sub(
        r'```mermaid\s*\n(.*?)```',
        r'<div class="mermaid">\n\1</div>',
        content,
        flags=re.DOTALL,
    )


def _current_palette() -> dict:
    """Get the active theme palette with mermaid theme added."""
    settings = load_globals()
    theme = settings.get("appearance.theme", "dark")
    if theme == "light":
        palette = dict(LIGHT_PALETTE)
        palette["mermaid_theme"] = "default"
        palette["color_scheme"] = "light"
        return palette
    if theme == "auto":
        is_light = detect_windows_theme() == "light"
        palette = dict(LIGHT_PALETTE if is_light else DARK_PALETTE)
        palette["mermaid_theme"] = "default" if is_light else "dark"
        palette["color_scheme"] = "light" if is_light else "dark"
        return palette
    palette = dict(DARK_PALETTE)
    palette["mermaid_theme"] = "dark"
    palette["color_scheme"] = "dark"
    return palette

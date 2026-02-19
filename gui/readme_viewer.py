"""
Markdown documentation viewer — browser-based.

Renders all project .md files to themed HTML (with Mermaid CDN support)
in a temp directory, then serves them via a local HTTP server and opens
the requested file in the default browser.

No QWebEngine dependency — uses the system browser for full HTML5/CSS3
and Mermaid diagram rendering.
"""

import os
import re
import sys
import shutil
import logging
import tempfile
import threading
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from string import Template

import markdown

from gui.styles import DARK_PALETTE, LIGHT_PALETTE
from gui.global_settings import load_globals
from ui.tray_icon import detect_windows_theme

logger = logging.getLogger(__name__)

# Stable temp directory (reused across app runs, overwritten on re-render)
_DOCS_DIR = Path(tempfile.gettempdir()) / "InputDNA_docs"

# Tracks which theme was last rendered (re-render on theme change)
_rendered_theme: str | None = None

# Project root used for resolving image paths
_project_root: Path | None = None

# Local HTTP server (started once, serves docs temp dir)
_server_port: int | None = None


# ── HTML template ─────────────────────────────────────────────
# Full CSS3 via system browser. Uses $variable substitution.

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
</style>
</head>
<body>
$content

<script>
// Mermaid: load from CDN, initialize only after script loads
(function() {
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    script.onload = function() {
        mermaid.initialize({
            startOnLoad: false,
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
        mermaid.run();
    };
    script.onerror = function() {
        // CDN failed — show raw text as-is (no crash)
        console.warn('Mermaid CDN unavailable, diagrams shown as text');
    };
    document.head.appendChild(script);
})();
</script>
</body>
</html>""")


# ── Local HTTP server ─────────────────────────────────────────


class _SilentHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves from docs dir without logging to console."""

    def log_message(self, format, *args):
        pass  # Suppress request logging


def _ensure_server() -> int:
    """Start a local HTTP server (once) serving the docs temp dir. Returns port."""
    global _server_port
    if _server_port is not None:
        return _server_port

    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    handler = partial(_SilentHandler, directory=str(_DOCS_DIR))
    server = HTTPServer(("127.0.0.1", 0), handler)
    _server_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Docs server started on http://127.0.0.1:{_server_port}")
    return _server_port


# ── Public API ────────────────────────────────────────────────


def open_docs(project_root: Path, file_name: str = "README.md"):
    """Render project docs to HTML and open in the default browser.

    On first call, renders all .md files from project_root to the docs
    temp directory and starts a local HTTP server. Subsequent calls reuse
    the cache unless the theme changed.
    """
    global _rendered_theme, _project_root

    # Frozen exe: .md files are bundled inside _MEIPASS
    if getattr(sys, "frozen", False):
        project_root = Path(sys._MEIPASS)

    _project_root = project_root.resolve()
    palette = _current_palette()
    current_theme = palette.get("color_scheme", "dark")

    # Re-render if first call or theme changed
    if _rendered_theme != current_theme:
        try:
            _render_all_docs(_project_root, _DOCS_DIR, palette)
            _rendered_theme = current_theme
        except Exception as e:
            logger.error(f"Failed to render docs: {e}")
            return

    # Ensure HTTP server is running
    port = _ensure_server()

    # Open the requested file via HTTP (no file:// restrictions)
    html_name = Path(file_name).with_suffix(".html").as_posix()
    url = f"http://127.0.0.1:{port}/{html_name}"
    webbrowser.open(url)


# ── Rendering engine ──────────────────────────────────────────


def _render_all_docs(project_root: Path, output_dir: Path, palette: dict):
    """Render all .md files from project root to HTML in output_dir."""
    # Clean previous render
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    md_files = list(project_root.glob("*.md")) + list(project_root.rglob("__*.md"))

    md_converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc"],
    )

    for md_path in md_files:
        _render_single(md_path, project_root, output_dir, palette, md_converter)
        md_converter.reset()

    logger.info(f"Rendered {len(md_files)} docs to {output_dir}")


def _render_single(
    md_path: Path,
    project_root: Path,
    output_dir: Path,
    palette: dict,
    md_converter: markdown.Markdown | None = None,
):
    """Render a single .md file to HTML."""
    if md_converter is None:
        md_converter = markdown.Markdown(
            extensions=["tables", "fenced_code", "toc"],
        )

    try:
        rel_path = md_path.relative_to(project_root)
    except ValueError:
        rel_path = Path(md_path.name)

    html_rel = rel_path.with_suffix(".html")
    html_path = output_dir / html_rel
    html_path.parent.mkdir(parents=True, exist_ok=True)

    content = md_path.read_text(encoding="utf-8")
    content = _preprocess_mermaid(content)
    content = _rewrite_md_links(content)
    html_body = md_converter.convert(content)

    full_html = _HTML_TEMPLATE.substitute(**palette, content=html_body)
    html_path.write_text(full_html, encoding="utf-8")

    # Copy referenced images to temp dir (HTTP server serves them)
    _copy_referenced_images(html_body, project_root, output_dir)


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


def _rewrite_md_links(content: str) -> str:
    """Rewrite .md links to .html so browser navigation works.

    Converts [text](path/to/file.md) -> [text](path/to/file.html)
    and [text](path/to/file.md#anchor) -> [text](path/to/file.html#anchor)
    Leaves external URLs (http/https) untouched.
    """
    def _replace(m):
        link = m.group(2)
        if link.startswith(("http://", "https://")):
            return m.group(0)
        return f'[{m.group(1)}]({link[:-3]}.html{m.group(3) or ""})'

    return re.sub(
        r'\[([^\]]*)\]\(([^)]*?\.md)(#[^)]*)?\)',
        _replace,
        content,
    )


def _copy_referenced_images(html: str, project_root: Path, output_dir: Path):
    """Copy images referenced in HTML from project root to the output dir.

    Images in .md files use paths relative to the project root
    (e.g. support/logo/dark/UV-InputDNA.svg). The rendered HTML
    is served via local HTTP, so relative paths resolve correctly
    as long as the files exist in the serving directory.
    """
    for m in re.finditer(r'(?:src|srcset)="([^"]*)"', html):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:", "file://")):
            continue
        src_path = (project_root / src).resolve()
        if src_path.exists():
            dest_path = output_dir / src
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)


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

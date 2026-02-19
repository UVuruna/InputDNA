"""
Generate InputDNA.ico from UV-InputDNA.svg.

Renders the SVG at multiple sizes and saves as a multi-resolution ICO file.
Uses the light-theme variant (dark outlines) for best visibility in most
OS contexts (Explorer, shortcuts, installer, Add/Remove Programs).

Called automatically by build.py. Can also be run standalone:
    python setup/svg_to_ico.py

Requires: PySide6, Pillow (both already project dependencies).
"""

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

SETUP_DIR = Path(__file__).parent
PROJECT_DIR = SETUP_DIR.parent

# Light variant = dark outlines, visible on both light and dark backgrounds
SVG_PATH = PROJECT_DIR / "support" / "logo" / "light" / "UV-InputDNA.svg"
ICO_PATH = SETUP_DIR / "InputDNA.ico"

# Standard Windows ICO sizes
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _render_svg_to_pil(renderer: QSvgRenderer, size: int) -> Image.Image:
    """Render SVG at the given size and return a Pillow RGBA Image."""
    qimage = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    qimage.fill(Qt.GlobalColor.transparent)

    painter = QPainter(qimage)
    renderer.render(painter)
    painter.end()

    # QImage (ARGB32) → bytes → Pillow
    buf = qimage.bits().tobytes()
    return Image.frombytes("RGBA", (size, size), buf, "raw", "BGRA")


def generate_ico() -> Path:
    """Generate InputDNA.ico from UV-InputDNA.svg. Returns the ICO path.

    Creates a QGuiApplication if one doesn't exist (needed by QSvgRenderer).
    Safe to call from build.py which doesn't have a Qt app yet.
    """
    if not SVG_PATH.exists():
        raise FileNotFoundError(f"SVG not found: {SVG_PATH}")

    # QSvgRenderer needs a QGuiApplication — create one if none exists
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Failed to load SVG: {SVG_PATH}")

    # Render at the largest size and let Pillow downscale for each ICO frame.
    # Pillow's ICO save ignores append_images — it only uses `sizes` to
    # auto-resize from the base image.
    largest = _render_svg_to_pil(renderer, max(ICO_SIZES))
    largest.save(
        str(ICO_PATH),
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )

    return ICO_PATH


def main():
    print(f"Source: {SVG_PATH}")

    ico_path = generate_ico()

    size_kb = ico_path.stat().st_size / 1024
    print(f"Output: {ico_path} ({size_kb:.0f} KB)")
    print(f"Sizes: {', '.join(f'{s}x{s}' for s in ICO_SIZES)}")


if __name__ == "__main__":
    main()

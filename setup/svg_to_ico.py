"""
Generate InputDNA.ico from UV-InputDNA.svg.

Renders the SVG at multiple sizes and saves as a multi-resolution ICO file.
Uses the light-theme variant (dark outlines) for best visibility in most
OS contexts (Explorer, shortcuts, installer, Add/Remove Programs).

Usage:
    python setup/svg_to_ico.py

Requires: PySide6, Pillow (both already project dependencies).
"""

import io
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


def render_svg_to_pil(renderer: QSvgRenderer, size: int) -> Image.Image:
    """Render SVG at the given size and return a Pillow RGBA Image."""
    qimage = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    qimage.fill(Qt.GlobalColor.transparent)

    painter = QPainter(qimage)
    renderer.render(painter)
    painter.end()

    # QImage (ARGB32) → bytes → Pillow
    buf = qimage.bits().tobytes()
    pil_img = Image.frombytes("RGBA", (size, size), buf, "raw", "BGRA")
    return pil_img


def main():
    if not SVG_PATH.exists():
        print(f"ERROR: SVG not found: {SVG_PATH}")
        sys.exit(1)

    # QSvgRenderer needs a QGuiApplication
    app = QGuiApplication(sys.argv)

    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"ERROR: Failed to load SVG: {SVG_PATH}")
        sys.exit(1)

    print(f"Source: {SVG_PATH}")
    print(f"SVG size: {renderer.defaultSize().width()}x{renderer.defaultSize().height()}")

    images = []
    for size in ICO_SIZES:
        img = render_svg_to_pil(renderer, size)
        images.append(img)
        print(f"  Rendered {size}x{size}")

    # Save as ICO (first image is the "main" one, rest are alternates)
    images[0].save(
        str(ICO_PATH),
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=images[1:],
    )

    size_kb = ICO_PATH.stat().st_size / 1024
    print(f"\nOutput: {ICO_PATH} ({size_kb:.0f} KB)")
    print(f"Sizes: {', '.join(f'{s}x{s}' for s in ICO_SIZES)}")


if __name__ == "__main__":
    main()

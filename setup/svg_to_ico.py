"""
Generate InputDNA.ico from UV-InputDNA.svg.

Renders the SVG at each ICO size individually for crisp results,
then saves as a multi-resolution ICO file.

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

    buf = qimage.bits().tobytes()
    return Image.frombytes("RGBA", (size, size), buf, "raw", "BGRA")


def generate_ico() -> Path:
    """Generate InputDNA.ico from UV-InputDNA.svg. Returns the ICO path."""
    if not SVG_PATH.exists():
        raise FileNotFoundError(f"SVG not found: {SVG_PATH}")

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Failed to load SVG: {SVG_PATH}")

    # Render each size individually from SVG for maximum sharpness
    frames = []
    for size in ICO_SIZES:
        img = _render_svg_to_pil(renderer, size)
        # Verify the frame isn't fully transparent (debug)
        if img.getextrema()[3] == (0, 0):  # alpha channel min/max both 0
            print(f"  WARNING: {size}x{size} frame is fully transparent!")
        frames.append(img)

    # Save: first frame is the base, rest go in append_images
    # The largest frame should be first (Windows uses it as the primary)
    frames.reverse()  # 256 first, 16 last
    frames[0].save(
        str(ICO_PATH),
        format="ICO",
        append_images=frames[1:],
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
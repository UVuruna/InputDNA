"""
Generate ICO files from UV-InputDNA.svg logos.

Two ICO files are produced:
  - InputDNA.ico       (dark variant) — exe icon, shortcuts, taskbar
  - InputDNA-setup.ico (light variant) — installer wizard

Renders each ICO size individually from SVG for crisp results.

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

LOGO_DIR = PROJECT_DIR / "support" / "logo"

# Standard Windows ICO sizes
ICO_SIZES = [16, 32, 48, 64, 128, 256]

# Which SVG variant → which ICO file
ICO_VARIANTS = {
    "dark": SETUP_DIR / "InputDNA.ico",          # exe, shortcuts, taskbar
    "light": SETUP_DIR / "InputDNA-setup.ico",    # installer wizard
}


def _render_svg_to_pil(renderer: QSvgRenderer, size: int) -> Image.Image:
    """Render SVG at the given size and return a Pillow RGBA Image."""
    qimage = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    qimage.fill(Qt.GlobalColor.transparent)

    painter = QPainter(qimage)
    renderer.render(painter)
    painter.end()

    buf = qimage.bits().tobytes()
    return Image.frombytes("RGBA", (size, size), buf, "raw", "BGRA")


def _render_ico(svg_path: Path, ico_path: Path) -> Path:
    """Render an SVG to a multi-resolution ICO file."""
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Failed to load SVG: {svg_path}")

    frames = []
    for size in ICO_SIZES:
        img = _render_svg_to_pil(renderer, size)
        if img.getextrema()[3] == (0, 0):
            print(f"  WARNING: {size}x{size} frame is fully transparent!")
        frames.append(img)

    # Largest frame first (Windows uses it as the primary)
    frames.reverse()
    frames[0].save(
        str(ico_path),
        format="ICO",
        append_images=frames[1:],
    )

    return ico_path


def generate_icos() -> dict[str, Path]:
    """Generate all ICO variants. Returns dict of theme→path."""
    # QSvgRenderer needs a QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    results = {}
    for theme, ico_path in ICO_VARIANTS.items():
        svg_path = LOGO_DIR / theme / "UV-InputDNA.svg"
        if not svg_path.exists():
            raise FileNotFoundError(f"SVG not found: {svg_path}")

        _render_ico(svg_path, ico_path)
        size_kb = ico_path.stat().st_size / 1024
        print(f"  {ico_path.name} ({size_kb:.0f} KB) ← {theme}/UV-InputDNA.svg")
        results[theme] = ico_path

    return results


def main():
    print("Generating ICO files from SVG logos:")
    generate_icos()
    print(f"Sizes: {', '.join(f'{s}x{s}' for s in ICO_SIZES)}")


if __name__ == "__main__":
    main()
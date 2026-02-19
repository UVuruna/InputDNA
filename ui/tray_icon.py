"""
System tray icon for recording status.

Shows custom InputDNA logos in the taskbar notification area.
Icons are loaded from light/ or dark/ subfolder based on Windows theme:
  {theme}/InputDNA-start.png  = recording
  {theme}/InputDNA-pause.png  = paused
  {theme}/InputDNA-stop.png   = stopped / error

Right-click menu: Pause/Resume, Stats, Quit.

pystray requires the icon to run on the main thread on some
platforms, so TrayIcon.run() is a blocking call.
"""

import logging
import winreg
from pathlib import Path
from typing import Callable, Optional
from PIL import Image
import pystray

logger = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent

_THEME_REG_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_THEME_REG_VALUE = "SystemUsesLightTheme"


def _detect_windows_theme() -> str:
    """Detect Windows taskbar theme from registry.

    Returns 'light' or 'dark'. Defaults to 'dark' if detection fails.
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_REG_PATH)
        value, _ = winreg.QueryValueEx(key, _THEME_REG_VALUE)
        winreg.CloseKey(key)
        return "light" if value == 1 else "dark"
    except OSError:
        logger.warning("Could not detect Windows theme, defaulting to dark")
        return "dark"


def _load_themed_icons() -> dict[str, Image.Image]:
    """Load all tray icons from the theme-appropriate subfolder."""
    theme = _detect_windows_theme()
    theme_dir = _UI_DIR / theme
    logger.info(f"Loading tray icons from ui/{theme}/")
    return {
        "recording": Image.open(theme_dir / "InputDNA-start.png"),
        "paused": Image.open(theme_dir / "InputDNA-pause.png"),
        "stopped": Image.open(theme_dir / "InputDNA-stop.png"),
    }


# Pre-load icons based on current Windows theme
_icons = _load_themed_icons()


class TrayIcon:
    """
    System tray icon with status and controls.

    Usage:
        tray = TrayIcon(
            on_toggle_pause=my_toggle_fn,
            on_quit=my_quit_fn,
            get_stats=my_stats_fn,
        )
        tray.run()  # Blocks main thread
    """

    def __init__(self,
                 on_toggle_pause: Callable[[], None],
                 on_quit: Callable[[], None],
                 get_stats: Optional[Callable[[], str]] = None):
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit
        self._get_stats = get_stats
        self._paused = False
        self._icon: Optional[pystray.Icon] = None

    def run(self):
        """Start the tray icon. Blocks until quit."""
        menu = pystray.Menu(
            pystray.MenuItem(
                text=lambda _: "Resume" if self._paused else "Pause",
                action=self._toggle,
            ),
            pystray.MenuItem(
                text="Stats",
                action=self._show_stats,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                text="Quit",
                action=self._quit,
            ),
        )

        self._icon = pystray.Icon(
            name="InputRecorder",
            icon=_icons["recording"],
            title="Input Recorder — Recording",
            menu=menu,
        )

        logger.info("System tray icon started")
        self._icon.run()  # Blocks

    def set_paused(self, paused: bool):
        """Update icon to reflect pause state."""
        self._paused = paused
        if self._icon is not None:
            if paused:
                self._icon.icon = _icons["paused"]
                self._icon.title = "Input Recorder — Paused"
            else:
                self._icon.icon = _icons["recording"]
                self._icon.title = "Input Recorder — Recording"

    def set_stopped(self):
        """Update icon to stopped state."""
        if self._icon is not None:
            self._icon.icon = _icons["stopped"]
            self._icon.title = "Input Recorder — Stopped"

    def _toggle(self, icon, item):
        """Menu: Pause/Resume clicked."""
        self._paused = not self._paused
        self._on_toggle_pause()
        self.set_paused(self._paused)

    def _show_stats(self, icon, item):
        """Menu: Stats clicked — show notification with counts."""
        if self._get_stats:
            stats = self._get_stats()
        else:
            stats = "No stats available"

        # pystray notification (Windows toast)
        if self._icon is not None:
            try:
                self._icon.notify(stats, "Input Recorder Stats")
            except Exception:
                # notify not supported on all platforms
                logger.info(f"Stats: {stats}")

    def stop(self):
        """Stop the tray icon programmatically (called from outside)."""
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    def _quit(self, icon, item):
        """Menu: Quit clicked."""
        logger.info("Quit requested from tray")
        if self._icon is not None:
            self._icon.stop()
        self._on_quit()

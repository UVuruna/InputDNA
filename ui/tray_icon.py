"""
System tray icon for application status.

Always visible while the app is running. Shows custom InputDNA logos
in the taskbar notification area, loaded from light/ or dark/ subfolder
based on the current Windows theme.

Icon states:
  {theme}/InputDNA.png        = default (app logo, before first recording)
  {theme}/InputDNA-start.png  = actively recording
  {theme}/InputDNA-pause.png  = recording but input idle
  {theme}/InputDNA-stop.png   = stopped recording

Double-click: opens the GUI window.
Right-click menu: Stop Recording (during recording), Stats, Quit.

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


def detect_windows_theme() -> str:
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
    theme = detect_windows_theme()
    theme_dir = _UI_DIR / theme
    logger.info(f"Loading tray icons from ui/{theme}/")
    return {
        "default": Image.open(theme_dir / "InputDNA.png"),
        "recording": Image.open(theme_dir / "InputDNA-start.png"),
        "idle": Image.open(theme_dir / "InputDNA-pause.png"),
        "stopped": Image.open(theme_dir / "InputDNA-stop.png"),
    }


# Pre-load icons based on current Windows theme
_icons = _load_themed_icons()


class TrayIcon:
    """
    System tray icon with status and controls.

    Always visible while the app is running. Starts with the default
    app logo. Double-click opens the GUI window.

    Usage:
        tray = TrayIcon(
            on_stop_recording=my_stop_fn,
            on_quit=my_quit_fn,
            get_stats=my_stats_fn,
            on_show_gui=my_show_fn,
        )
        tray.run()  # Blocks
    """

    def __init__(self,
                 on_stop_recording: Callable[[], None],
                 on_quit: Callable[[], None],
                 get_stats: Optional[Callable[[], str]] = None,
                 on_show_gui: Optional[Callable[[], None]] = None):
        self._on_stop_recording = on_stop_recording
        self._on_quit = on_quit
        self._get_stats = get_stats
        self._on_show_gui = on_show_gui
        self._recording = False
        self._icon: Optional[pystray.Icon] = None

    def run(self):
        """Start the tray icon with default app logo. Blocks until quit."""
        menu = pystray.Menu(
            # Default action (double-click) — invisible menu item
            pystray.MenuItem(
                text="Show",
                action=self._show_gui,
                default=True,
                visible=False,
            ),
            pystray.MenuItem(
                text="Stop Recording",
                action=self._stop_recording,
                visible=lambda _: self._recording,
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
            name="InputDNA",
            icon=_icons["default"],
            title="InputDNA",
            menu=menu,
        )

        logger.info("System tray icon started")
        self._icon.run()  # Blocks

    def set_default(self):
        """Set icon to default (app logo) state — no user logged in."""
        self._recording = False
        if self._icon is not None:
            self._icon.icon = _icons["default"]
            self._icon.title = "InputDNA"
            self._icon.update_menu()

    def set_recording(self):
        """Set icon to recording (green) state."""
        self._recording = True
        if self._icon is not None:
            self._icon.icon = _icons["recording"]
            self._icon.title = "InputDNA — Recording"
            self._icon.update_menu()

    def set_idle(self):
        """Set icon to idle (yellow) state — recording but no input activity."""
        if self._icon is not None:
            self._icon.icon = _icons["idle"]
            self._icon.title = "InputDNA — Recording (Idle)"

    def set_stopped(self):
        """Set icon to stopped (red) state — not recording."""
        self._recording = False
        if self._icon is not None:
            self._icon.icon = _icons["stopped"]
            self._icon.title = "InputDNA — Not Recording"
            self._icon.update_menu()

    def _show_gui(self, icon, item):
        """Default action (double-click) — open the GUI window."""
        if self._on_show_gui:
            self._on_show_gui()

    def _stop_recording(self, icon, item):
        """Menu: Stop Recording clicked."""
        logger.info("Stop recording requested from tray")
        self._on_stop_recording()

    def _show_stats(self, icon, item):
        """Menu: Stats clicked — show notification with counts."""
        if self._get_stats:
            stats = self._get_stats()
        else:
            stats = "No stats available"

        if self._icon is not None:
            try:
                self._icon.notify(stats, "InputDNA Stats")
            except Exception:
                logger.info(f"Stats: {stats}")

    def stop(self):
        """Stop the tray icon programmatically (called from outside)."""
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    def _quit(self, icon, item):
        """Menu: Quit clicked — close entire app."""
        logger.info("Quit requested from tray")
        self._on_quit()

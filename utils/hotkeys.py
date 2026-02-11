"""
Global hotkey registration for pause/resume.

Uses pynput's GlobalHotKeys to register Ctrl+Alt+R (configurable)
as a toggle for recording. Runs in its own daemon thread.
"""

from pynput import keyboard
from typing import Callable
import config


def register_toggle_hotkey(on_toggle: Callable[[], None]) -> keyboard.GlobalHotKeys:
    """
    Register the global hotkey for pausing/resuming recording.

    Args:
        on_toggle: Callback function called when hotkey is pressed.
                   Should toggle recording state.

    Returns:
        The GlobalHotKeys listener (already started as daemon thread).
    """
    hotkeys = keyboard.GlobalHotKeys({
        config.HOTKEY_TOGGLE: on_toggle
    })
    hotkeys.daemon = True
    hotkeys.start()
    return hotkeys

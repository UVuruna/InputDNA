# ui/

System tray interface for the recorder. Provides minimal visual feedback
and controls without a full window — the recorder runs silently in the
background with just a tray icon.

<a id="folder-structure"></a>

## Folder Structure

```
📁 ui/
  📝 __ui.md
  🐍 __init__.py
  🐍 tray_icon.py
  📁 light/                              Icons for light Windows theme
    🖼️ InputDNA-start.png
    🖼️ InputDNA-pause.png
    🖼️ InputDNA-stop.png
  📁 dark/                               Icons for dark Windows theme
    🖼️ InputDNA-start.png
    🖼️ InputDNA-pause.png
    🖼️ InputDNA-stop.png
```

<a id="files"></a>

## Files

### `tray_icon.py` — System Tray Icon & Menu

Uses `pystray` + `Pillow` to show custom InputDNA logos in the Windows
notification area (system tray). Icons are loaded from `light/` or `dark/`
subfolder based on the current Windows theme.

**Theme detection:** Reads `SystemUsesLightTheme` from the Windows registry
(`HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize`).
Theme is detected once at startup.

**Icon states:**

| State | File | Description |
|-------|------|-------------|
| Recording | `{theme}/InputDNA-start.png` | Actively recording input |
| Paused | `{theme}/InputDNA-pause.png` | Paused (via hotkey or menu) |
| Stopped | `{theme}/InputDNA-stop.png` | Stopped or error |

### `light/` / `dark/` — Theme Icon Folders

256x256 PNG icons exported from the SVG sources in `support/logo/`.
Each folder contains the same three icons with colors optimized for
the respective Windows taskbar background:

- **light/** — dark outlines/shadows, visible on light taskbar
- **dark/** — light outlines/shadows, visible on dark taskbar

Loaded at startup by `tray_icon.py` via Pillow. pystray handles
resizing to the appropriate system tray size (16-32px depending on DPI).

**Right-click menu:**

| Menu Item | Action |
|-----------|--------|
| **Pause / Resume** | Toggles recording on/off. Label updates dynamically. |
| **Stats** | Shows a Windows toast notification with current counts: movements, clicks, keystrokes, DB queue depth. |
| **Quit** | Graceful shutdown: stops listeners → flushes DB writer → updates recording session → exits. |

<a id="threading"></a>

## Threading

```mermaid
flowchart TB
    MAIN["Main Thread\n(blocked by tray icon)"]
    T1["Thread 1: Mouse Listener"]
    T2["Thread 2: Keyboard Listener"]
    T3["Thread 3: Event Processor"]
    T4["Thread 4: DB Writer"]

    MAIN -.- T1
    MAIN -.- T2
    MAIN -.- T3
    MAIN -.- T4

    MAIN -- "Quit / Ctrl+C" --> SHUTDOWN["Graceful Shutdown"]
```

`pystray` requires `Icon.run()` to block the main thread on Windows.
All other components (listeners, processor, writer) run in daemon threads.
When the tray icon stops (via Quit or Ctrl+C), the main thread unblocks
and triggers graceful shutdown.

<a id="why-not-a-full-gui"></a>

## Why Not a Full GUI?

The recorder is designed to run invisibly. A full window would be
distracting and unnecessary — all you need to know is:

| Question | Answer |
|----------|--------|
| Is it recording? | Green mouse icon (start) |
| Is it paused? | Yellow mouse icon (pause) |
| Is it stopped? | Red mouse icon (stop) |
| How much data so far? | Stats menu → toast notification |
| How to pause/stop? | Right-click menu or `Ctrl+Alt+R` |

The separate `gui/` package handles the full PySide6 dashboard for
user profiles, training, and validation — that's a different concern.

# ui/

System tray interface for the application. The tray icon is always visible
while the app is running (from startup to exit), providing visual feedback
about recording state. Double-click opens the GUI window.

<a id="folder-structure"></a>

## Folder Structure

```
📁 ui/
  📝 __ui.md
  🐍 __init__.py
  🐍 tray_icon.py
  📁 light/                              Icons for light Windows theme
    🖼️ InputDNA.png
    🖼️ InputDNA-start.png
    🖼️ InputDNA-pause.png
    🖼️ InputDNA-stop.png
  📁 dark/                               Icons for dark Windows theme
    🖼️ InputDNA.png
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
| Default | `{theme}/InputDNA.png` | App logo (initial state, before login or between sessions) |
| Recording | `{theme}/InputDNA-start.png` | Actively recording input |
| Idle | `{theme}/InputDNA-pause.png` | Recording but no input for 60+ seconds (cosmetic) |
| Stopped | `{theme}/InputDNA-stop.png` | Recording stopped |

### `light/` / `dark/` — Theme Icon Folders

256x256 PNG icons exported from the SVG sources in `support/logo/`.
Each folder contains four icons with colors optimized for
the respective Windows taskbar background:

- **light/** — dark outlines/shadows, visible on light taskbar
- **dark/** — light outlines/shadows, visible on dark taskbar

Loaded at startup by `tray_icon.py` via Pillow. pystray handles
resizing to the appropriate system tray size (16-32px depending on DPI).

**Double-click:** Opens/raises the GUI window (default action via invisible
menu item with `default=True`). Useful when window is hidden (minimize on close)
or when app started in autostart mode (tray only, no window).

**Right-click menu:**

| Menu Item | Visible | Action |
|-----------|---------|--------|
| **Stop Recording** | During recording | Stops recording, icon → red. |
| **Stats** | Always | Shows a Windows toast notification with current counts (or "Not recording"). |
| **Quit** | Always | Force-closes the entire application (bypasses minimize on close). |

<a id="lifecycle"></a>

## Lifecycle

```
App start  →  Tray appears (app logo/default)
Login      →  (tray stays, no change until recording starts)
Start      →  Green (recording) → Yellow after 60s idle → Green on input
Stop       →  Red (stopped) — tray stays visible
Logout     →  Tray resets to default icon (stays visible)
Quit       →  Tray removed (only via right-click → Quit)
```

The tray icon runs in a daemon thread (`pystray.Icon.run()` blocks).
It persists for the entire app lifetime — from startup to Quit.

<a id="tray-at-a-glance"></a>

## Tray at a Glance

| Question | Answer |
|----------|--------|
| Just logged in? | App logo (default) |
| Is it recording? | Green mouse icon (start) |
| Is the user idle? | Yellow mouse icon (pause) — cosmetic only |
| Is it stopped? | Red mouse icon (stop) |
| How much data so far? | Stats menu → toast notification |

The separate `gui/` package handles the full PySide6 dashboard for
user profiles, training, and validation — that's a different concern.

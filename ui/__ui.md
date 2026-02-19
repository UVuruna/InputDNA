# ui/

System tray interface for the application. The tray icon is always visible
after login, providing visual feedback about recording state. It persists
for the entire logged-in session (not just during recording).

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
| Default | `{theme}/InputDNA.png` | App logo (initial state after login, before first recording) |
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

**Right-click menu:**

| Menu Item | Visible | Action |
|-----------|---------|--------|
| **Stop Recording** | During recording | Stops recording, icon → red. |
| **Stats** | Always | Shows a Windows toast notification with current counts (or "Not recording"). |
| **Quit** | Always | Closes the entire application. |

<a id="lifecycle"></a>

## Lifecycle

```
Login  →  Tray appears (app logo/default)
Start  →  Green (recording) → Yellow after 60s idle → Green on input
Stop   →  Red (stopped) — tray stays visible
Logout →  Tray removed
Close  →  Tray removed
```

The tray icon runs in a daemon thread (`pystray.Icon.run()` blocks).
It persists from login to logout/close, independent of recording state.

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

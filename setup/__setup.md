# setup/

Build and installation scripts for packaging InputDNA as a distributable Windows application.

## Build Process

```
1. python setup/create_cert.py    — One-time: generate signing certificate
2. python setup/svg_to_ico.py     — After logo changes: regenerate ICO from SVG
3. python setup/build.py          — Each release: build exe + installer
```

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| PyInstaller | Bundle Python → exe | `pip install pyinstaller` |
| NSIS | Create Windows installer | [nsis.sourceforge.io](https://nsis.sourceforge.io/) |
| Windows SDK | Code signing (signtool) | Optional — signing is skipped if not found |

## Files

### `build.py` — Main Build Script

Orchestrates the full build pipeline:
1. Runs PyInstaller in `--onedir` mode (no console, UAC admin)
2. Signs the exe with the self-signed certificate (if available)
3. Calls NSIS `makensis` to create `InputDNA_Setup.exe`

Output goes to `dist/` folder (gitignored).

### `create_cert.py` — Certificate Generator

Creates a self-signed code signing certificate using PowerShell:
- Publisher name: `UVuruna`
- Valid for 5 years
- Exports to `setup/cert/InputDNA.pfx`
- Run once, then the certificate is reused by `build.py`

The `cert/` folder is gitignored — never commit certificates.

### `installer.nsi` — NSIS Installer Script

Defines the Windows installer wizard:
- **Welcome page** with app description
- **Directory selection** (default: `C:\Program Files\InputDNA\`)
- **Components page** — optional Desktop shortcut and autostart
- **Installation** — copies files, creates data dirs, adds Defender exclusions
- **Finish page** — option to launch immediately

Data directories created at install time:
- `%LOCALAPPDATA%\InputDNA\db\` — SQLite databases
- `%LOCALAPPDATA%\InputDNA\logs\` — Log files

Uninstaller removes program files but preserves user data.

### `svg_to_ico.py` — ICO Generator

Renders `support/logo/light/UV-InputDNA.svg` into a multi-resolution ICO file
at `setup/InputDNA.ico`. Uses PySide6 `QSvgRenderer` + Pillow. Run once after
logo changes:

```
python setup/svg_to_ico.py
```

Uses the light-theme variant (dark outlines) for the static ICO — best
visibility across most OS contexts (Explorer, shortcuts, Add/Remove Programs).

### `InputDNA.ico` — Application Icon

Generated from `UV-InputDNA.svg` by `svg_to_ico.py`. Contains multiple
resolutions (16, 32, 48, 64, 128, 256px). Used by PyInstaller (exe binary
icon) and NSIS (installer icon, shortcuts).

> **Note:** At runtime, the window title bar and taskbar icon use the
> theme-aware SVG directly (`support/logo/{theme}/UV-InputDNA.svg`), not
> the ICO. The ICO is only for the exe file icon and installer.

## Installed File Layout

```
C:\Program Files\InputDNA\          ← Program files
  InputDNA.exe
  InputDNA.ico
  ui/light/                         ← Tray icons (light theme)
  ui/dark/                          ← Tray icons (dark theme)
  logo/light/UV-InputDNA.svg        ← Window icon (light theme)
  logo/dark/UV-InputDNA.svg         ← Window icon (dark theme)
  (PyInstaller runtime files)

C:\Users\<user>\AppData\Local\InputDNA\   ← User data
  db\
    profiles.db                     ← User profiles
  (per-user data folders)
```

## Design Decisions

- **`--onedir` over `--onefile`** — Less RAM usage, faster startup, fewer antivirus false positives.
- **Self-signed certificate** — Free, sufficient for personal use and small distribution. Can upgrade to purchased cert for public release.
- **NSIS over alternatives** — Free, widely used (VLC, 7-Zip), mature, small installer size with LZMA compression.
- **Defender exclusion in installer** — `pynput` uses `SetWindowsHookEx` which triggers antivirus. Exclusion added automatically since installer already runs as admin.
- **Data in AppData, not Program Files** — Program Files requires admin to write. Recorder writes constantly to SQLite, so data must be in a user-writable location.
- **Uninstall preserves data** — User's recorded input patterns are valuable. Uninstalling the app should not delete months of collected data.

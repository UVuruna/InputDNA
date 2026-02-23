# setup/

Build and installation scripts for packaging InputDNA as a distributable Windows application.

## Build Process

```
1. python setup/create_cert.py    — One-time: generate signing certificate
2. python setup/build.py          — Each release: build exe + installer
```

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| PyInstaller | Bundle Python → exe | `pip install pyinstaller` |
| NSIS | Create Windows installer | [nsis.sourceforge.io](https://nsis.sourceforge.io/) |
| Windows SDK | Code signing (signtool) | Optional — signing is skipped if not found |

## Files

### `app_info.json` — App Metadata (Single Source of Truth)

Static app metadata used by the build pipeline. **Version is not here** — it
comes from `version.py` (auto-updated by the git `commit-msg` hook).

```json
{
    "app_name": "InputDNA",
    "company": "UVuruna",
    "product_name": "InputDNA",
    "description": "Human Input Recorder",
    "copyright": "© 2026 UVuruna"
}
```

Used to generate:
- **`_version_info.py`** (at build time) — embedded in the EXE as Windows VERSIONINFO
  resource (CompanyName, FileDescription, FileVersion, LegalCopyright, etc.)
- **NSIS `APP_PUBLISHER`** — shown in Add/Remove Programs → Publisher column

> **`_version_info.py`** is generated at build time and gitignored — never commit it.

### `build.py` — Main Build Script

Orchestrates the full build pipeline:
1. Generates ICO files from SVG logos (`svg_to_ico.py` — dark + light variants)
2. Runs PyInstaller in `--onedir` mode (no console, UAC admin)
3. Signs the exe with the self-signed certificate (if available)
4. Calls NSIS `makensis` to create `InputDNA_Setup.exe`

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

Generates two multi-resolution ICO files from the UV-InputDNA.svg logos:

| ICO File | SVG Source | Used For |
|----------|-----------|----------|
| `InputDNA.ico` | `support/logo/dark/` | Exe binary icon, shortcuts, taskbar, Add/Remove Programs |
| `InputDNA-setup.ico` | `support/logo/light/` | Installer wizard icon (`InputDNA_Setup.exe`) |

Uses PySide6 `QSvgRenderer` + Pillow. Renders each size individually from
SVG for crisp results at all resolutions (16, 32, 48, 64, 128, 256px).

Called automatically by `build.py` as the first step. Can also be run
standalone: `python setup/svg_to_ico.py`

### `InputDNA.ico` / `InputDNA-setup.ico` — Application Icons

Generated from `UV-InputDNA.svg` by `svg_to_ico.py`. Each contains multiple
resolutions (16, 32, 48, 64, 128, 256px).

- **`InputDNA.ico`** (dark variant) — embedded in exe by PyInstaller, used for
  shortcuts and Add/Remove Programs display icon
- **`InputDNA-setup.ico`** (light variant) — used as the installer wizard icon
  and the `InputDNA_Setup.exe` file icon

> **Note:** At runtime, the window title bar and taskbar icon use the
> theme-aware SVG directly (`support/logo/{theme}/UV-InputDNA.svg`), not
> the ICO. The ICO files are only for the static exe/installer file icons.

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

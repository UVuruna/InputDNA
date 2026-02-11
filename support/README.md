# support/

Design assets and branding resources for the Uncanny Valley project family. These files are NOT used by the application at runtime — they are source materials for documentation and UI design.

## Files

### 📁 `logo/` — SVG Logos

Project logos exported from Adobe Illustrator. Used in README documentation and as reference for UI assets.

| File | Purpose |
|------|---------|
| `Uncanny Valley.svg` | Parent project logo, displayed in root README |
| `InputDNA.svg` | InputDNA sub-project logo, displayed in root README |
| `InputDNA-working.svg` | Status variant — green/active state, reference for tray icon |
| `InputDNA-stopped.svg` | Status variant — red/stopped state, reference for tray icon |
| `VoiceDNA.svg` | VoiceDNA sub-project logo (future), displayed in root README |
| `GamingDNA.svg` | GamingDNA sub-project logo (future), displayed in root README |

> **Note:** SVG files cannot be used directly by pystray (requires Pillow-compatible formats: PNG, ICO).
> The status variants serve as design reference — the actual tray icon is generated programmatically in `ui/tray_icon.py`.

### 📁 `adobe/` — Source Files

| File | Purpose |
|------|---------|
| `Documentation-Logo.ai` | Adobe Illustrator master file used to create all logo variants |

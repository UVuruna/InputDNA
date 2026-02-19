# support/

Design assets and branding resources for the UVirtual project family. These files are NOT used by the application at runtime — they are source materials for documentation and UI design.

## Files

### 📁 `logo/` — SVG Logos

Project logos exported from Adobe Illustrator. Each logo has a `light/` and `dark/` variant optimized for the respective background. The README uses `<picture>` elements with `prefers-color-scheme` to serve the correct variant based on the reader's theme.

**Folder structure:**

```
📁 logo/
  📁 light/                              Logos for light backgrounds
  📁 dark/                               Logos for dark backgrounds
```

**Platform Logo:**

| File | Purpose |
|------|---------|
| `{theme}/UVirtual.svg` | UVirtual parent platform logo — "UV" monogram with orbital swirl |

**DNA Module Logos:**

| File | Purpose |
|------|---------|
| `{theme}/UV-InputDNA.svg` | InputDNA module logo — stylized mouse |
| `{theme}/UV-VoiceDNA.svg` | VoiceDNA module logo — headphones with sound wave visualization |
| `{theme}/UV-GamingDNA.svg` | GamingDNA module logo — game controller |
| `{theme}/UV-ExpressionDNA.svg` | ExpressionDNA module logo — photo camera with lens detail |
| `{theme}/UV-MotionDNA.svg` | MotionDNA module logo — surveillance/video camera |
| `{theme}/UV-Avatar.svg` | UV Avatar logo — bearded character face (the virtual twin) |

**InputDNA Status Icons (tray icon references):**

| File | Purpose |
|------|---------|
| `InputDNA-start.svg` | Status variant — active/recording state, reference for tray icon |
| `InputDNA-pause.svg` | Status variant — paused state, reference for tray icon |
| `InputDNA-stop.svg` | Status variant — stopped state, reference for tray icon |

> **Note:** SVG files cannot be used directly by pystray (requires Pillow-compatible formats: PNG, ICO).
> The status variants serve as design reference — the actual tray icons (PNG) live in `ui/light/` and `ui/dark/`.

### 📁 `adobe/` — Source Files

| File | Purpose |
|------|---------|
| `Documentation-Logo.ai` | Adobe Illustrator master file used to create all logo variants |

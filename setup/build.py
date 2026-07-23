"""
Build InputDNA into a distributable package.

Steps:
  1. Generate ICOs from SVG logos (svg_to_ico — dark + light variants)
  2. Run PyInstaller (--onedir mode) to create the exe
  3. Sign the exe with self-signed certificate
  4. Call NSIS to create the installer

Prerequisites:
  - pip install pyinstaller
  - Run create_cert.py once (for code signing)
  - Install NSIS (https://nsis.sourceforge.io/) and add to PATH

Usage:
    python setup/build.py
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
SETUP_DIR = Path(__file__).parent
PROJECT_DIR = SETUP_DIR.parent

# ── Version (single source of truth: version.py) ──────────────
sys.path.insert(0, str(PROJECT_DIR))
from version import __version__ as APP_VERSION

# ── App metadata ──────────────────────────────────────────────
# All metadata (project-specific + company-level) lives in setup/app_info.json
APP_INFO = json.loads((SETUP_DIR / "app_info.json").read_text(encoding="utf-8"))
# Company-level metadata is owned by the monorepo-root company.json (single
# source — never duplicated per project). CompanyName in the exe comes from
# here, so the company legend shows "UVuruna", not a stale per-project value.
COMPANY_JSON_PATH = PROJECT_DIR.parent.parent / "company.json"
COMPANY = json.loads(COMPANY_JSON_PATH.read_text(encoding="utf-8"))
VERSION_INFO_PATH = SETUP_DIR / "_version_info.py"  # generated at build time, gitignored

DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"

ICON_PATH = SETUP_DIR / "InputDNA.ico"              # dark variant — exe, shortcuts
SETUP_ICON_PATH = SETUP_DIR / "InputDNA-setup.ico"  # light variant — installer wizard
CERT_PATH = SETUP_DIR / "cert" / "InputDNA.pfx"
PASSWORD_PATH = SETUP_DIR / "cert" / "password.txt"   # gitignored (never hardcode)
NSI_PATH = SETUP_DIR / "installer.nsi"


def _load_password() -> str | None:
    """Read the certificate password from the gitignored password file.
    Never hardcode it in build.py (root CLAUDE.md build pipeline)."""
    if not PASSWORD_PATH.exists():
        return None
    return PASSWORD_PATH.read_text(encoding="utf-8").strip()


CERT_PASSWORD = _load_password()
APP_NAME = "InputDNA"
ENTRY_POINT = PROJECT_DIR / "main.py"


def _version_tuple(version_str: str) -> tuple[int, int, int, int]:
    """Convert '0.2.490' to (0, 2, 490, 0) for VERSIONINFO fixed file info."""
    parts = version_str.split(".")
    parts += ["0"] * (4 - len(parts))
    return tuple(int(p) for p in parts[:4])


def generate_version_info() -> None:
    """Write PyInstaller VERSIONINFO file from app_info.json + version.py."""
    ver = _version_tuple(APP_VERSION)
    ver_str = ".".join(str(v) for v in ver)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName',      {COMPANY['company_name']!r}),
          StringStruct('FileDescription',  {APP_INFO['description']!r}),
          StringStruct('FileVersion',      {ver_str!r}),
          StringStruct('InternalName',     {APP_INFO['name']!r}),
          StringStruct('LegalCopyright',   {APP_INFO['copyright_string']!r}),
          StringStruct('OriginalFilename', {APP_INFO['exe_name']!r}),
          StringStruct('ProductName',      {APP_INFO['name']!r}),
          StringStruct('ProductVersion',   {ver_str!r}),
        ]
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ]
)
"""
    VERSION_INFO_PATH.write_text(content, encoding="utf-8")
    print(f"Version info: {COMPANY['company_name']} / {APP_INFO['name']} "
          f"/ {APP_INFO['description']} / {ver_str} / {APP_INFO['copyright_string']}")


def step(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def run(cmd: list[str], **kwargs):
    """Run a command, print it, and check for errors."""
    print(f"  > {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"  FAILED (exit code {result.returncode})")
        if result.stderr:
            print(f"  {result.stderr}")
        sys.exit(1)
    return result


def generate_ico():
    step("1/4  Generating ICOs from SVG logos")
    run([sys.executable, str(SETUP_DIR / "svg_to_ico.py")])


def build_pyinstaller():
    step("2/4  Building exe with PyInstaller")

    # Clean previous build
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            print(f"  Cleaning {d}")
            shutil.rmtree(d)

    # Packages that get pulled in as transitive dependencies
    # but are not used by InputDNA at runtime.
    # ONLY exclude packages we are 100% certain are not needed.
    # Do NOT exclude stdlib modules (unittest, pydoc, etc.) — ML libs use them internally.
    exclude_modules = [
        "tkinter",
        # QWebEngine = Chromium (~500 MB). Docs viewer uses system browser instead.
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineQuick",
        # Deep learning frameworks — InputDNA uses only sklearn/scipy/numpy, not these
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "tensorboard",
        "keras",
        # Heavy optional deps we don't use
        "matplotlib",
        "IPython",
        "notebook",
        "jupyter",
    ]

    # Modules PyInstaller fails to detect automatically
    hidden_imports = [
        "pystray",
        "pystray._win32",
        "PySide6.QtSvg",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name", APP_NAME,
        "--icon", str(ICON_PATH),
        # Windowed mode (no console window)
        "--windowed",
        # Request admin privileges (needed for input hooks)
        "--uac-admin",
        # Embed version info (CompanyName, ProductName, FileVersion, etc.)
        "--version-file", str(VERSION_INFO_PATH),
        # Add data files
        "--add-data", f"{ICON_PATH};.",
        "--add-data", f"{PROJECT_DIR / 'ui' / 'light'};ui/light",
        "--add-data", f"{PROJECT_DIR / 'ui' / 'dark'};ui/dark",
        "--add-data", f"{PROJECT_DIR / 'support' / 'logo' / 'light' / 'UV-InputDNA.svg'};logo/light",
        "--add-data", f"{PROJECT_DIR / 'support' / 'logo' / 'dark' / 'UV-InputDNA.svg'};logo/dark",
    ]

    # Bundle documentation .md files (for Readme viewer in frozen exe)
    for md_path in list(PROJECT_DIR.glob("*.md")) + list(PROJECT_DIR.rglob("__*.md")):
        rel = md_path.relative_to(PROJECT_DIR)
        dest = str(rel.parent) if str(rel.parent) != "." else "."
        cmd.extend(["--add-data", f"{md_path};{dest}"])
    # Also bundle docs/ folder (linked from README)
    docs_dir = PROJECT_DIR / "docs"
    if docs_dir.exists():
        for md_path in docs_dir.glob("*.md"):
            cmd.extend(["--add-data", f"{md_path};docs"])
    # Bundle all logo SVGs at original paths (for image rendering in docs)
    for variant in ("dark", "light"):
        logo_dir = PROJECT_DIR / "support" / "logo" / variant
        if logo_dir.exists():
            for svg in logo_dir.glob("*.svg"):
                cmd.extend(["--add-data", f"{svg};support/logo/{variant}"])

    # Add hidden imports
    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    # Add exclude flags
    for mod in exclude_modules:
        cmd.extend(["--exclude-module", mod])

    # Entry point (must be last)
    cmd.append(str(ENTRY_POINT))

    start = time.time()
    run(cmd)
    elapsed = time.time() - start
    print(f"  PyInstaller completed in {elapsed:.1f}s")

    exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    if not exe_path.exists():
        print(f"  ERROR: Expected exe not found: {exe_path}")
        sys.exit(1)

    # Copy ICO to dist root so NSIS shortcuts can reference $INSTDIR\InputDNA.ico
    # (PyInstaller puts --add-data files inside _internal/, not the exe directory)
    dist_ico = DIST_DIR / APP_NAME / ICON_PATH.name
    shutil.copy2(ICON_PATH, dist_ico)
    print(f"  Copied {ICON_PATH.name} to {dist_ico.parent}")

    print(f"  Output: {exe_path}")
    return exe_path


def _find_signtool() -> str | None:
    """Locate signtool.exe (PATH first, then the Windows SDK)."""
    signtool = shutil.which("signtool")
    if signtool:
        return signtool
    sdk_paths = [
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
        Path(r"C:\Program Files\Windows Kits\10\bin"),
    ]
    for sdk_base in sdk_paths:
        if sdk_base.exists():
            versions = sorted(sdk_base.glob("10.*/x64/signtool.exe"))
            if versions:
                return str(versions[-1])
    return None


def sign_file(path: Path, what: str) -> bool:
    """Authenticode-sign one file with the project certificate.

    Reused for BOTH the inner exe AND the distributed installer — signing
    only the inner exe leaves the file the user actually runs (the installer)
    unsigned, which defeats the SmartScreen mitigation. Returns True when the
    file was signed, False when a prerequisite was missing (skipped, not an
    error — signing is the documented-optional step).
    """
    if not CERT_PATH.exists():
        print(f"  WARNING: Certificate not found: {CERT_PATH}")
        print("  Run 'python setup/create_cert.py' first.")
        print("  Skipping signing...")
        return False

    if not CERT_PASSWORD:
        print(f"  WARNING: Password file not found: {PASSWORD_PATH}")
        print("  Skipping signing...")
        return False

    signtool = _find_signtool()
    if not signtool:
        print("  WARNING: signtool.exe not found.")
        print("  Install Windows SDK or add signtool to PATH.")
        print("  Skipping signing...")
        return False

    cmd = [
        signtool, "sign",
        "/f", str(CERT_PATH),
        "/p", CERT_PASSWORD,
        "/fd", "SHA256",
        "/t", "http://timestamp.digicert.com",
        str(path),
    ]

    run(cmd)
    print(f"  {what.capitalize()} signed successfully.")
    return True


def sign_exe(exe_path: Path):
    step("3/4  Signing exe with certificate")
    sign_file(exe_path, "exe")


def build_installer():
    step("4/4  Building installer with NSIS")

    makensis = shutil.which("makensis")
    if not makensis:
        # Try common NSIS locations
        nsis_paths = [
            Path(r"C:\Program Files (x86)\NSIS\makensis.exe"),
            Path(r"C:\Program Files\NSIS\makensis.exe"),
        ]
        for p in nsis_paths:
            if p.exists():
                makensis = str(p)
                break

    if not makensis:
        print("  ERROR: makensis.exe not found.")
        print("  Install NSIS from https://nsis.sourceforge.io/")
        sys.exit(1)

    cmd = [
        makensis,
        f"/DPROJECT_DIR={PROJECT_DIR}",
        f"/DDIST_DIR={DIST_DIR}",
        f"/DSETUP_DIR={SETUP_DIR}",
        f"/DAPP_VERSION={APP_VERSION}",
        f"/DAPP_PUBLISHER={COMPANY['company_name']}",
        str(NSI_PATH),
    ]

    run(cmd)

    installer_path = DIST_DIR / f"{APP_NAME}_Setup.exe"
    if installer_path.exists():
        # Sign the installer itself — this is the file the user downloads and
        # runs, so it (not just the inner exe) must carry the signature.
        sign_file(installer_path, "installer")
        print(f"  Installer: {installer_path}")
        size_mb = installer_path.stat().st_size / (1024 * 1024)
        print(f"  Size: {size_mb:.1f} MB")
    else:
        print("  WARNING: Installer exe not found at expected location.")


def _powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True)
    return result.stdout.strip()


def verify_build(exe_path: Path, installer_path: Path):
    """Fail-closed gate: assert the OUTPUT actually carries what the pipeline
    promises, instead of trusting that every step ran. A missing step here
    (no CompanyName, unsigned installer) produces no error on its own — it
    just ships broken metadata — so nothing but an explicit check catches it.

    Asserts: exe CompanyName == company.json, exe FileVersion == version.py,
    and (when a signing cert is configured) both exe AND installer are signed.
    """
    step("VERIFY  metadata + signatures (build fails if anything is missing)")
    problems = []

    info = _powershell(
        f"$v=(Get-Item '{exe_path}').VersionInfo; "
        f"\"$($v.CompanyName)|$($v.FileVersion)\"")
    company, _, file_version = info.partition("|")
    expected_company = COMPANY["company_name"]
    if company != expected_company:
        problems.append(
            f"exe CompanyName is {company!r}, expected {expected_company!r} "
            "(version resource missing/empty — company legends show 'Unknown')")
    if APP_VERSION not in file_version:
        problems.append(
            f"exe FileVersion is {file_version!r}, expected to contain {APP_VERSION!r}")

    # Signing is documented-optional: only assert it when a cert is configured.
    if CERT_PATH.exists() and CERT_PASSWORD:
        for label, target in (("exe", exe_path), ("installer", installer_path)):
            status = _powershell(f"(Get-AuthenticodeSignature '{target}').Status")
            if status in ("", "NotSigned"):
                problems.append(f"{label} is NOT signed (status {status or 'missing'!r})")

    if problems:
        for p in problems:
            print(f"  FAIL: {p}")
        print("\n  Build produced artifacts but they FAIL the pipeline contract.")
        sys.exit(1)

    print(f"  OK: CompanyName={company!r}  FileVersion={file_version!r}")
    if CERT_PATH.exists() and CERT_PASSWORD:
        print("  OK: exe + installer signed")
    else:
        print("  NOTE: signing skipped (no certificate) — installer is UNSIGNED")


def main():
    print(f"Building {APP_NAME}")
    print(f"Project: {PROJECT_DIR}")

    if not ENTRY_POINT.exists():
        print(f"ERROR: Entry point not found: {ENTRY_POINT}")
        sys.exit(1)

    generate_version_info()
    generate_ico()
    exe_path = build_pyinstaller()
    sign_exe(exe_path)
    build_installer()
    verify_build(exe_path, DIST_DIR / f"{APP_NAME}_Setup.exe")

    step("BUILD COMPLETE")
    print(f"  Installer: {DIST_DIR / f'{APP_NAME}_Setup.exe'}")
    print()


if __name__ == "__main__":
    main()

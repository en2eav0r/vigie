"""Build Vigie for Windows.

    python desktop/build.py

1. Copies the shared screens (server/web/static) into desktop/ui/static.
2. Builds dist/Vigie/ (Vigie.exe and its files) with PyInstaller, as a folder so each click starts fast.
3. Builds dist/VigieSetup.exe, a single-file per-user installer, and its SHA-256 checksum (N12).
The installer is not code-signed yet: Windows SmartScreen will warn until a certificate is bought.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
REPO = DESKTOP.parent
BUILD = DESKTOP / "build"
DIST = DESKTOP / "dist"
sys.path.insert(0, str(DESKTOP))
from vigie_desktop import __version__  # noqa: E402

# Modules that are installed on build machines but never used by Vigie; keeps the app small.
EXCLUDES = ["tkinter", "numpy", "torch", "PIL", "matplotlib", "pandas", "scipy", "whisper", "IPython",
            "pytest", "openai", "anthropic", "fastapi", "uvicorn", "cryptography", "pygments"]


def pyinstaller(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--workpath", str(BUILD), "--distpath", str(DIST), *args], check=True, cwd=DESKTOP)


def version_file() -> Path:
    major, minor, patch = (int(x) for x in __version__.split("."))
    path = BUILD / "version.txt"
    BUILD.mkdir(exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Vigie'),
    StringStruct('FileDescription', 'Vigie: checks every link before it opens'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'Vigie'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('LegalCopyright', 'MIT licence')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
    return path


def main() -> None:
    static = DESKTOP / "ui" / "static"
    shutil.rmtree(static, ignore_errors=True)
    shutil.copytree(REPO / "server" / "web" / "static", static, ignore=shutil.ignore_patterns("icons"))

    server = os.environ.get("VIGIE_SERVER", "http://127.0.0.1:8740").rstrip("/")
    (DESKTOP / "vigie_desktop" / "_build.py").write_text(
        f'"""Written by desktop/build.py."""\nDEFAULT_SERVER = {server!r}\n', encoding="utf-8")
    print(f"Server written into the app: {server}")

    excludes = [arg for name in EXCLUDES for arg in ("--exclude-module", name)]
    # White logo 03 on a blue tile: visible on light and dark taskbars.
    icon = str(DESKTOP / "assets" / "vigie-blue.ico")
    pyinstaller("--name", "Vigie", "--windowed", "--icon", icon, "--version-file", str(version_file()),
                "--add-data", f"{DESKTOP / 'ui'};ui", *excludes, str(DESKTOP / "vigie_launcher.py"))

    app_dir = DIST / "Vigie"
    archive = BUILD / "vigie-app.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in app_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(app_dir))
    (BUILD / "VERSION").write_text(__version__, encoding="utf-8")

    pyinstaller("--name", "VigieSetup", "--onefile", "--windowed", "--icon", icon,
                "--version-file", str(version_file()),
                "--add-data", f"{archive};.", "--add-data", f"{BUILD / 'VERSION'};.",
                "--add-data", f"{DESKTOP / 'vigie_desktop'};vigie_desktop",
                "--exclude-module", "webview", *excludes, str(DESKTOP / "installer" / "setup_main.py"))

    setup = DIST / "VigieSetup.exe"
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (DIST / "VigieSetup.exe.sha256").write_text(f"{digest}  VigieSetup.exe\n", encoding="utf-8")
    size_app = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file()) / 1e6
    print(f"Vigie {__version__}: app folder {size_app:.1f} MB, installer {setup.stat().st_size / 1e6:.1f} MB")
    print(f"SHA-256 {digest}")


if __name__ == "__main__":
    main()

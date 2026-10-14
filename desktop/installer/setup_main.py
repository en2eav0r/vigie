"""VigieSetup.exe: installs Vigie for the current user, without administrator rights (D01).

    VigieSetup.exe        asks for confirmation, installs, then opens Vigie on its setup screen
    VigieSetup.exe /S     silent install (for tests and IT deployment)
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

APP = "Vigie"
INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP
START_MENU = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs"


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def message(text: str, flags: int = 0x40) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, "Vigie setup", flags)


def stop_running_vigie() -> None:
    subprocess.run(["taskkill", "/IM", "Vigie.exe", "/F"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(0.8)


def create_shortcuts(target: Path) -> None:
    """Start menu and desktop shortcuts; the desktop folder is read from Windows (it may be on OneDrive)."""
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$places = @($env:VIGIE_START_MENU, [Environment]::GetFolderPath('Desktop')); "
        "foreach ($dir in $places) { "
        "$s = $shell.CreateShortcut((Join-Path $dir 'Vigie.lnk')); "
        "$s.TargetPath = $env:VIGIE_EXE; $s.WorkingDirectory = $env:VIGIE_DIR; "
        "$s.IconLocation = $env:VIGIE_EXE + ',0'; $s.Description = 'Checks every link before it opens.'; $s.Save() }"
    )
    env = {**os.environ, "VIGIE_START_MENU": str(START_MENU), "VIGIE_EXE": str(target), "VIGIE_DIR": str(target.parent)}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)


def folder_size_kb(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // 1024


def install(silent: bool) -> int:
    version = (bundle_dir() / "VERSION").read_text(encoding="utf-8").strip()
    if not silent and message(
        f"Install Vigie {version} for your Windows account?\n\n"
        "Vigie checks every link you click before it opens. No administrator rights are needed.",
        0x24,
    ) != 6:
        return 1
    stop_running_vigie()
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_dir() / "vigie-app.zip") as archive:
        archive.extractall(INSTALL_DIR)
    exe = INSTALL_DIR / "Vigie.exe"
    sys.path.insert(0, str(bundle_dir()))
    from vigie_desktop import registry
    registry.register(str(exe), version, str(INSTALL_DIR), folder_size_kb(INSTALL_DIR))
    create_shortcuts(exe)
    if not silent:
        subprocess.Popen([str(exe), "--first-run"], close_fds=True, creationflags=subprocess.DETACHED_PROCESS)
    return 0


def main() -> int:
    silent = any(a.lower() in ("/s", "--silent") for a in sys.argv[1:])
    try:
        return install(silent)
    except Exception as exc:  # show the reason instead of failing silently
        if not silent:
            message(f"Vigie could not be installed.\n\n{type(exc).__name__}: {exc}", 0x10)
        else:
            print(f"install failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

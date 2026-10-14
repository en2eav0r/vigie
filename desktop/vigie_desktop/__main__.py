"""Vigie.exe entry point.

    Vigie.exe                    open Vigie (setup and "Paste a link to check")
    Vigie.exe <url>              check a link; Windows calls this for every clicked link
    Vigie.exe --uninstall        remove Vigie: registry keys, data and program files
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _message(text: str, title: str = "Vigie", flags: int = 0x40) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def _desktop_dir() -> Path:
    """The user's desktop folder as Windows reports it (it may be redirected to OneDrive)."""
    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer)  # CSIDL_DESKTOPDIRECTORY
    return Path(buffer.value)


def uninstall(quiet: bool) -> int:
    from . import registry, single_instance
    from .settings import DATA_DIR

    if not quiet and _message("Remove Vigie from this computer?\n\nLinks will open directly in your browser again, "
                              "without being checked.", "Uninstall Vigie", 0x24) != 6:
        return 1
    # Close the running Vigie window, if any, so its files can be removed.
    subprocess.run(["taskkill", "/IM", "Vigie.exe", "/F", "/FI", f"PID ne {os.getpid()}"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    registry.unregister()
    single_instance.release()
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    for folder in (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs", _desktop_dir()):
        (folder / "Vigie.lnk").unlink(missing_ok=True)
    if getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).parent
        if install_dir.name.lower() == "vigie":
            # A running program cannot delete itself: a detached shell removes the folder once Vigie has exited.
            subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{install_dir}"',
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)
    if not quiet:
        _message("Vigie has been removed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--uninstall" in args:
        return uninstall("--quiet" in args)
    debug = "--debug" in args
    if debug or os.environ.get("VIGIE_DEBUG"):
        import logging
        from .settings import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Events only, never the links themselves.
        logging.basicConfig(filename=DATA_DIR / "vigie.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    urls = [a for a in args if not a.startswith("--")]
    url = urls[0] if urls else None

    from . import single_instance
    if single_instance.hand_over(url):
        return 0  # the running Vigie takes the link

    from .app import run
    run(url, debug=debug, first_run="--first-run" in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

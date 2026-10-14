"""Installed browsers, read from the registry, so a safe link opens in the user's choice (D04)."""
from __future__ import annotations

import os
import re
import subprocess
import winreg
from dataclasses import asdict, dataclass

_ROOTS = (
    (winreg.HKEY_CURRENT_USER, r"Software\Clients\StartMenuInternet"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
)


@dataclass(frozen=True)
class Browser:
    id: str
    name: str
    exe: str

    def to_dict(self) -> dict:
        return asdict(self)


def _exe_from_command(command: str) -> str | None:
    command = os.path.expandvars(command.strip())
    match = re.match(r'^"([^"]+)"', command) or re.match(r"^(\S+\.exe)", command, re.I)
    return match.group(1) if match else None


def installed() -> list[Browser]:
    found: dict[str, Browser] = {}
    for hive, root in _ROOTS:
        try:
            with winreg.OpenKey(hive, root) as key:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    if sub.lower() == "vigie":
                        continue
                    try:
                        with winreg.OpenKey(key, sub) as entry:
                            name = winreg.QueryValueEx(entry, "")[0] or sub
                        with winreg.OpenKey(key, rf"{sub}\shell\open\command") as cmd:
                            exe = _exe_from_command(winreg.QueryValueEx(cmd, "")[0])
                    except OSError:
                        continue
                    if exe and os.path.isfile(exe) and sub.lower() not in found:
                        found[sub.lower()] = Browser(id=sub, name=_tidy(name), exe=exe)
        except FileNotFoundError:
            continue
    return sorted(found.values(), key=lambda b: b.name.lower())


def _tidy(name: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*$", "", name).replace("Mozilla Firefox", "Firefox").strip()


def open_in(browser: Browser, url: str) -> None:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only web links can be opened.")
    subprocess.Popen([browser.exe, url], close_fds=True, creationflags=subprocess.DETACHED_PROCESS)

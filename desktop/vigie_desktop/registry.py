"""Register Vigie as a browser for the current user (HKCU, no admin rights) and remove every key (D01)."""
from __future__ import annotations

import ctypes
import winreg

APP = "Vigie"
PROG_ID = "VigieURL"
CLIENT_KEY = rf"Software\Clients\StartMenuInternet\{APP}"
CAPABILITIES = rf"{CLIENT_KEY}\Capabilities"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP}"
DESCRIPTION = "Checks every link before it opens."


def _set(path: str, values: dict[str, str | int]) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
        for name, value in values.items():
            kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
            winreg.SetValueEx(key, name or None, 0, kind, value)


def _delete_tree(path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def _notify() -> None:
    # SHCNE_ASSOCCHANGED tells Windows the list of browsers changed.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def register(exe: str, version: str, install_dir: str, size_kb: int = 0) -> None:
    command = f'"{exe}" "%1"'
    icon = f'"{exe}",0'
    _set(rf"Software\Classes\{PROG_ID}", {"": "Vigie link", "FriendlyTypeName": "Vigie link"})
    _set(rf"Software\Classes\{PROG_ID}\Application", {"ApplicationName": APP, "ApplicationIcon": icon,
                                                       "ApplicationDescription": DESCRIPTION})
    _set(rf"Software\Classes\{PROG_ID}\DefaultIcon", {"": icon})
    _set(rf"Software\Classes\{PROG_ID}\shell\open\command", {"": command})
    _set(CLIENT_KEY, {"": APP, "LocalizedString": APP})
    _set(rf"{CLIENT_KEY}\DefaultIcon", {"": icon})
    _set(rf"{CLIENT_KEY}\shell\open\command", {"": f'"{exe}"'})
    _set(rf"{CLIENT_KEY}\InstallInfo", {"IconsVisible": 1})
    _set(CAPABILITIES, {"ApplicationName": APP, "ApplicationDescription": DESCRIPTION, "ApplicationIcon": icon})
    _set(rf"{CAPABILITIES}\URLAssociations", {"http": PROG_ID, "https": PROG_ID})
    _set(rf"{CAPABILITIES}\StartMenu", {"StartMenuInternet": APP})
    _set(r"Software\RegisteredApplications", {APP: CAPABILITIES})
    _set(UNINSTALL_KEY, {
        "DisplayName": APP, "DisplayVersion": version, "Publisher": "Vigie", "DisplayIcon": icon,
        "InstallLocation": install_dir, "UninstallString": f'"{exe}" --uninstall',
        "QuietUninstallString": f'"{exe}" --uninstall --quiet', "NoModify": 1, "NoRepair": 1,
        "EstimatedSize": size_kb,
    })
    _notify()


def unregister() -> None:
    _delete_tree(rf"Software\Classes\{PROG_ID}")
    _delete_tree(CLIENT_KEY)
    _delete_tree(UNINSTALL_KEY)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications", 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP)
    except FileNotFoundError:
        pass
    _notify()


def leftover_keys() -> list[str]:
    """Keys or values Vigie owns that still exist. Used by the uninstall test."""
    found = []
    for path in (rf"Software\Classes\{PROG_ID}", CLIENT_KEY, UNINSTALL_KEY):
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, path).Close()
            found.append(path)
        except FileNotFoundError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications") as key:
            winreg.QueryValueEx(key, APP)
            found.append(r"Software\RegisteredApplications\Vigie")
    except FileNotFoundError:
        pass
    return found


def is_registered() -> bool:
    return CLIENT_KEY in leftover_keys()


def is_default_browser() -> bool:
    """True when Windows sends both http and https links to Vigie (D06)."""
    for scheme in ("http", "https"):
        path = rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                prog_id, _ = winreg.QueryValueEx(key, "ProgId")
        except FileNotFoundError:
            return False
        if prog_id != PROG_ID:
            return False
    return True


def open_default_apps_settings() -> None:
    """Windows 11 does not let an app make itself the default browser; open the settings page on Vigie (D02)."""
    import os
    try:
        os.startfile(f"ms-settings:defaultapps?registeredAppUser={APP}")
    except OSError:
        os.startfile("ms-settings:defaultapps")

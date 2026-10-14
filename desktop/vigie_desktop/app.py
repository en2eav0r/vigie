"""Vigie Desktop window: a small frameless window rendering the shared Vigie screens.

The window only ever shows Vigie's own interface; the destination page is never loaded here.
A safe link is handed to the user's browser (D04).
"""
from __future__ import annotations

import os

import json
import logging
import sys
import threading
from pathlib import Path

import webview

from . import __version__, browsers, client, registry
from . import settings as store

UI_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "ui"
log = logging.getLogger("vigie")


class Api:
    def __init__(self) -> None:
        self._window: webview.Window | None = None  # private: pywebview exposes public attributes to JS
        self._pending: str | None = None
        self._ui_ready = False
        self._cleared: set[str] = set()   # links the server declared safe in this session
        self._lock = threading.Lock()
        self._maximized = True  # the window opens maximized
        self._first_run = False

    # Called from Python --------------------------------------------------------------
    def _receive(self, url: str | None) -> None:
        """A link arrived from Windows (first launch or the running instance)."""
        with self._lock:
            if not self._ui_ready:
                self._pending = url
                log.info("link queued until the window is ready")
                return
        log.info("link received from another Vigie process")
        self._bring_to_front()
        if url:
            self._js("window.vigie.check", url)
        else:
            self._js("window.vigie.home")

    def _js(self, fn: str, *args) -> None:
        if self._window:
            try:
                self._window.evaluate_js(f"{fn}({', '.join(json.dumps(a) for a in args)})")
            except Exception:
                log.exception("could not update the window (%s)", fn)

    def _bring_to_front(self) -> None:
        if not self._window:
            return
        try:
            self._window.restore()
            self._window.show()
            self._window.on_top = True
            self._window.on_top = False
        except Exception:
            pass

    # Called from JavaScript ------------------------------------------------------------
    def ready(self) -> dict:
        with self._lock:
            self._ui_ready = True
            pending, self._pending = self._pending, None
        config = store.load()
        is_default = registry.is_default_browser()
        reset_warning = bool(config.get("was_default")) and not is_default
        if is_default and not config.get("was_default"):
            store.save({"was_default": True})
        return {
            "version": __version__,
            "server": config["server"],
            "browser": config.get("browser"),
            "registered": registry.is_registered(),
            "isDefault": is_default,
            "resetWarning": reset_warning,
            "pending": pending,
            "firstRun": self._consume_first_run(),
        }

    def _consume_first_run(self) -> bool:
        first, self._first_run = self._first_run, False
        return first

    def check(self, url: str) -> None:
        def emit(event: str, data: dict) -> None:
            if event == "verdict" and data.get("verdict") == "safe":
                self._cleared.add(data.get("url") or url)
            self._js("window.vigie.onEvent", event, data)

        threading.Thread(target=client.investigate, args=(url, emit), daemon=True).start()

    def list_browsers(self) -> list[dict]:
        return [b.to_dict() for b in browsers.installed()]

    def open_link(self, url: str, browser_id: str | None, always: bool) -> dict:
        # The only path that opens a destination, and only for a link the server has just cleared.
        if url not in self._cleared:
            return {"ok": False, "error": "This link has not been cleared by Vigie."}
        config = store.load()
        installed = {b.id: b for b in browsers.installed()}
        chosen = installed.get(browser_id or "") or (
            installed.get(config["browser"]["id"]) if config.get("browser") else None)
        if not chosen:
            return {"ok": False, "error": "Choose a browser first."}
        if always:
            store.save({"browser": chosen.to_dict()})
        try:
            browsers.open_in(chosen, url)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"{chosen.name} could not be started ({type(exc).__name__})."}
        self._cleared.discard(url)
        threading.Timer(1.5, self._minimize_quietly).start()
        return {"ok": True, "browser": chosen.name}

    def _minimize_quietly(self) -> None:
        try:
            if self._window:
                self._window.minimize()
        except Exception:
            pass

    def forget_browser(self) -> None:
        store.save({"browser": None})

    def open_default_settings(self) -> None:
        if not registry.is_registered():
            exe = sys.executable if getattr(sys, "frozen", False) else None
            if exe:
                registry.register(exe, __version__, str(Path(exe).parent))
        registry.open_default_apps_settings()

    def default_status(self) -> dict:
        is_default = registry.is_default_browser()
        if is_default:
            store.save({"was_default": True})
        return {"isDefault": is_default, "registered": registry.is_registered()}

    def report(self, url: str, verdict: str) -> bool:
        return client.report(url, verdict)

    def save_server(self, url: str) -> dict:
        valid = store.valid_server(url)
        if not valid:
            return {"ok": False, "error": "Use an https:// address (http:// only works for this computer)."}
        reachable = client.server_reachable(valid)
        store.save({"server": valid, "token": ""})
        return {"ok": True, "server": valid, "reachable": reachable}

    # Window controls (the window has no system frame) --------------------------------
    def minimize(self) -> None:
        self._window.minimize()

    def toggle_maximize(self) -> None:
        # The window fills the work area by default; this button switches to the small centred window (D03) and back.
        self._maximized = not self._maximized
        _place(self._window, full=self._maximized)

    def close(self) -> None:
        self._window.destroy()


def _hwnd(window) -> int:
    """The Windows handle of our window: the visible top-level window titled "Vigie" that belongs to this process."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 64)
            if title.value == window.title:
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def _place(window, full: bool) -> None:
    """Fill the work area (the screen minus the taskbar), or show the small centred window (D03).
    Done with SetWindowPos: the work area and the position then share the same units at any display scaling,
    which pywebview's own sizes and a maximized frameless window do not."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = _hwnd(window)
        if not hwnd:
            return
        area = wintypes.RECT()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
        x, y, w, h = area.left, area.top, area.right - area.left, area.bottom - area.top
        if not full:
            sw, sh = int(w * 0.62), int(h * 0.78)
            x, y, w, h = x + (w - sw) // 2, y + (h - sh) // 2, sw, sh
        user32.SetWindowPos(hwnd, None, x, y, w, h, 0x0004 | 0x0010)  # SWP_NOZORDER | SWP_NOACTIVATE
    except Exception:
        pass


def run(initial_url: str | None, debug: bool = False, first_run: bool = False) -> None:
    from . import single_instance

    api = Api()
    api._pending = initial_url
    api._first_run = first_run
    single_instance.serve(api._receive)
    window = webview.create_window(
        "Vigie",
        url=str(UI_DIR / "index.html"),
        js_api=api,
        width=1120,
        height=760,
        min_size=(760, 560),
        frameless=True,
        easy_drag=False,
        background_color="#FFFFFF",
        text_select=True,
    )
    api._window = window
    window.events.shown += lambda: _place(window, full=True)  # full screen by default, above the taskbar
    try:
        webview.start(http_server=True, debug=debug, private_mode=True)
    finally:
        single_instance.release()

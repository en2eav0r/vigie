"""Per-user settings and the local copy of past verdicts (N04), in %LOCALAPPDATA%\\Vigie."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Vigie"
SETTINGS_FILE = DATA_DIR / "settings.json"
VERDICTS_FILE = DATA_DIR / "verdicts.json"
# Server address written into the app by desktop/build.py (VIGIE_SERVER at build time). The user can still
# change it in the settings, so an organisation can point its clients at its own server (C07).
try:
    from ._build import DEFAULT_SERVER
except ImportError:  # running from source
    DEFAULT_SERVER = os.environ.get("VIGIE_SERVER", "http://127.0.0.1:8740")
LOCAL_VERDICT_DAYS = 7

_lock = threading.Lock()


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load() -> dict:
    with _lock:
        data = _read(SETTINGS_FILE, {})
    data.setdefault("server", DEFAULT_SERVER)
    data.setdefault("token", "")
    data.setdefault("browser", None)          # {"id", "name", "exe"} when "always use this browser" is on
    data.setdefault("was_default", False)     # to warn when Windows resets the default browser (D06)
    return data


def save(changes: dict) -> dict:
    with _lock:
        data = _read(SETTINGS_FILE, {})
        data.update(changes)
        _write(SETTINGS_FILE, data)
    return load()


def valid_server(url: str) -> str | None:
    """Clients talk to the server over HTTPS only (N11); plain HTTP is accepted for this computer only."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"):
        return url
    return None


def cache_key(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower(), path, urlencode(sorted(query)), ""))


def remember_verdict(url: str, verdict: dict) -> None:
    if verdict.get("verdict") not in ("safe", "blocked"):
        return
    with _lock:
        cache = _read(VERDICTS_FILE, {})
        cutoff = time.time() - LOCAL_VERDICT_DAYS * 86400
        cache = {k: v for k, v in cache.items() if v.get("saved", 0) > cutoff}
        keep = {k: verdict.get(k) for k in ("verdict", "explanation", "host", "url", "destination", "evidence",
                                             "threat_type", "impersonated_brand")}
        cache[cache_key(url)] = {**keep, "saved": time.time()}
        _write(VERDICTS_FILE, cache)


def past_verdict(url: str) -> dict | None:
    with _lock:
        entry = _read(VERDICTS_FILE, {}).get(cache_key(url))
    if entry and entry.get("saved", 0) > time.time() - LOCAL_VERDICT_DAYS * 86400:
        return entry
    return None

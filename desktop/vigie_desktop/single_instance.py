"""Every clicked link reaches the running instance (D03).

The first Vigie process listens on a local socket protected by a random key stored in the user's
profile. A second process started by Windows for a new link hands the link over and exits.
"""
from __future__ import annotations

import json
import secrets
import threading
from multiprocessing.connection import Client, Listener
from typing import Callable

from .settings import DATA_DIR

INSTANCE_FILE = DATA_DIR / "instance.json"


def hand_over(url: str | None) -> bool:
    """Send the link to a running Vigie. Returns False when no instance is running."""
    try:
        info = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        with Client(("127.0.0.1", int(info["port"])), authkey=bytes.fromhex(info["key"])) as conn:
            conn.send({"url": url})
            return conn.recv() == "ok"
    except Exception:
        return False


def serve(on_url: Callable[[str | None], None]) -> Listener:
    key = secrets.token_bytes(32)
    listener = Listener(("127.0.0.1", 0), authkey=key)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps({"port": listener.address[1], "key": key.hex()}), encoding="utf-8")

    def loop() -> None:
        while True:
            try:
                with listener.accept() as conn:
                    message = conn.recv()
                    conn.send("ok")
                on_url(message.get("url"))
            except Exception:
                continue

    threading.Thread(target=loop, name="vigie-ipc", daemon=True).start()
    return listener


def release() -> None:
    try:
        INSTANCE_FILE.unlink()
    except OSError:
        pass

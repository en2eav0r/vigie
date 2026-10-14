"""Talks to the Vigie server: client token, streamed investigation, report a mistake."""
from __future__ import annotations

import json
from typing import Callable
from urllib.parse import urlsplit

import httpx

from . import settings as store

Emit = Callable[[str, dict], None]
TIMEOUT = httpx.Timeout(60.0, connect=6.0)


class ServerUnreachable(Exception):
    pass


def _host(url: str) -> str:
    try:
        return urlsplit(url if "://" in url else "https://" + url).hostname or url[:80]
    except ValueError:
        return url[:80]


def new_token(server: str) -> str:
    try:
        r = httpx.post(f"{server}/api/token", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["token"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ServerUnreachable(str(exc)) from exc


def _stream(server: str, token: str, url: str, emit: Emit) -> str:
    """Stream one investigation. Returns the last event name."""
    last = ""
    with httpx.stream("POST", f"{server}/investigate", json={"url": url}, timeout=TIMEOUT,
                      headers={"X-Vigie-Token": token, "Accept": "text/event-stream"}) as response:
        if response.status_code != 200:
            raise ServerUnreachable(f"The server answered with an error ({response.status_code}).")
        event, data = "message", ""
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
            elif line == "" and data:
                payload = json.loads(data)
                last = event
                if event == "verdict":
                    store.remember_verdict(payload.get("url", url), payload)
                if event != "token":
                    emit(event, payload)
                event, data = "message", ""
    return last


def investigate(url: str, emit: Emit) -> None:
    """Run the journey for one link. Every failure ends on a screen that keeps the link closed."""
    config = store.load()
    server = config["server"]
    try:
        token = config["token"] or new_token(server)
        if token != config["token"]:
            store.save({"token": token})
        last = _stream(server, token, url, emit)
        if last == "token":  # the server no longer knows this token: get a new one, once
            token = new_token(server)
            store.save({"token": token})
            last = _stream(server, token, url, emit)
        if last not in ("verdict", "limit", "invalid"):
            raise ServerUnreachable("The connection closed before the verdict.")
    except (ServerUnreachable, httpx.HTTPError, ValueError) as exc:
        past = store.past_verdict(url)
        if past:
            # N04: a link Vigie already judged still gets its verdict while the server is down.
            emit("step", {"id": 1, "tool": "memory", "label": "Server unreachable: using Vigie's earlier verdict",
                          "status": "done"})
            emit("verdict", {**past, "from_local_copy": True})
        else:
            detail = str(exc) if isinstance(exc, ServerUnreachable) and "error" in str(exc) else ""
            emit("offline", {"host": _host(url), "detail": detail})


def report(url: str, verdict: str) -> bool:
    config = store.load()
    try:
        r = httpx.post(f"{config['server']}/api/report", json={"url": url, "verdict": verdict}, timeout=TIMEOUT)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def server_reachable(server: str) -> bool:
    try:
        return httpx.get(f"{server}/api/health", timeout=4.0).status_code == 200
    except httpx.HTTPError:
        return False

"""HTTP API and Vigie Web.

POST /investigate   streamed investigation (server-sent events), used by every client (S01)
GET  /go?url=       the journey for a wrapped link (W02)
GET  /example/fresh a recent phishing link picked from a public feed (S12)
POST /api/token     anonymous client token (S09)
POST /api/report    "Report a mistake" (C05)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import investigate
from .config import ROOT, settings
from .db import Store
from .normalize import InvalidLink, normalise
from .providers import ProviderChoice
from .tools import new_http_client
from .tools.reputation import openphish_feed

WEB = ROOT / "web"
SETTINGS = settings()
store = Store(SETTINGS.db_path)
app = FastAPI(title="Vigie", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

_token_requests: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    )
    return response


def _page(name: str) -> FileResponse:
    return FileResponse(WEB / "templates" / name, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/")
async def home():
    """The presentation page is the front door of the site."""
    return _page("how.html")


@app.get("/check")
async def check_page():
    return _page("index.html")


@app.get("/go")
async def go():
    return _page("go.html")


@app.get("/replay/{name}")
async def replay_page(name: str):
    return _page("go.html")


@app.get("/api/replays/{name}")
async def replay_data(name: str):
    from .replay import load
    data = load(name)
    if data is None:
        return JSONResponse({"error": "No replay with this name."}, status_code=404)
    return data


@app.get("/how-it-works")
async def how_it_works():
    # Old address of the presentation page, kept so shared links still work.
    return RedirectResponse("/", status_code=301)


@app.get("/privacy")
async def privacy():
    return _page("privacy.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "provider": SETTINGS.provider, "spend_cap_reached": _cap_reached()}


def _client_ip(request: Request) -> str:
    """The visitor's address. Behind the Cloudflare tunnel or Caddy every request reaches Vigie from a local or
    Docker address; only then are the proxy headers trusted (anyone could send them from outside)."""
    import ipaddress
    peer = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = False
    # Cloudflare sends CF-Connecting-IP; Caddy appends the visitor's address to X-Forwarded-For.
    forwarded = request.headers.get("cf-connecting-ip", "").strip() or         request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    return forwarded if local and forwarded else (peer or "?")


@app.post("/api/token")
async def token(request: Request):
    # Tokens are free to create, so creation is rate limited. The IP is only hashed, in memory (N06).
    ip_hash = hashlib.sha256(_client_ip(request).encode()).hexdigest()[:16]
    window = _token_requests[ip_hash]
    now = time.time()
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= 30:
        return JSONResponse({"error": "too_many_tokens"}, status_code=429)
    window.append(now)
    return {"token": store.new_token()}


def _cap_reached() -> bool:
    return store.spend_today() >= SETTINGS.daily_spend_cap_usd


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@app.post("/investigate")
async def investigate_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_url = str(body.get("url", ""))
    client_token = request.headers.get("x-vigie-token", "")
    # S11: the user's own key is used in memory for this investigation and never written anywhere.
    user_key = request.headers.get("x-vigie-user-key", "").strip()
    choice = ProviderChoice(
        name=request.headers.get("x-vigie-provider", "").strip() if user_key else "",
        model=request.headers.get("x-vigie-model", "").strip() if user_key else "",
        key=user_key,
        base_url=request.headers.get("x-vigie-base-url", "").strip() if user_key else "",
    )

    async def stream():
        try:
            link = normalise(raw_url)
        except InvalidLink as exc:
            yield _sse("invalid", {"message": str(exc)})
            return
        if not store.token_exists(client_token):
            yield _sse("token", {"message": "This app needs a new client token."})
            return
        yield _sse("start", {"url": link.url, "host": link.display_host, "sensitive": link.sensitive,
                             "test_agent": SETTINGS.provider == "scripted"})

        cached = store.get_verdict(link.key, SETTINGS.verdict_ttl_hours)
        if cached:
            label = "Already investigated by Vigie: " + ("safe" if cached["verdict"] == "safe" else "blocked")
            yield _sse("step", {"id": 1, "tool": "memory", "label": label, "status": "done"})
            yield _sse("verdict", {**cached, "url": link.url, "host": link.display_host, "from_memory": True})
            return

        if not user_key:
            if _cap_reached():
                yield _sse("limit", {"kind": "daily_cap",
                                     "message": "Vigie has used today's free checks for everyone. "
                                                "Try again tomorrow, or add your own AI key in the app settings."})
                return
            quota = SETTINGS.daily_quota_per_token
            if store.usage_today(client_token) >= quota:
                checks = "free check" if quota == 1 else "free checks"
                yield _sse("limit", {"kind": "token_quota", "quota": quota,
                                     "message": f"You have used today's {quota} {checks}. New links stay closed "
                                                "until tomorrow; links Vigie has already checked still open."})
                return
            store.add_usage(client_token)

        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def run() -> None:
            try:
                result = await investigate(link, SETTINGS, store, choice, emit)
            except Exception as exc:  # never leave a client hanging: unknown blocks the page
                result = {"verdict": "unknown", "reason": "Vigie hit an internal error.", "url": link.url,
                          "host": link.display_host, "explanation": "Vigie could not finish checking this link, "
                          "so it stays closed.", "evidence": [], "steps": [], "decisive_evidence": [],
                          "error": type(exc).__name__}
            if result["verdict"] in ("safe", "blocked"):
                stored = {k: v for k, v in result.items() if k not in ("steps",)}
                store.put_verdict(link.key, link.public, link.registered_domain, result["verdict"], stored)
            store.log_investigation(link.public, result["verdict"], result.get("steps", []))
            await queue.put(("verdict", result))
            await queue.put(None)

        # The investigation keeps running if the client disconnects, so its verdict still reaches the memory.
        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            if event == "verdict":
                data = {k: v for k, v in data.items() if k != "steps"}
            yield _sse(event, data)
        await task

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/report")
async def report(request: Request):
    body = await request.json()
    try:
        link = normalise(str(body.get("url", "")))
    except InvalidLink as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    report_id = store.add_report(link.public, str(body.get("verdict", ""))[:20], str(body.get("note", "")))
    return {"ok": True, "id": report_id}


@app.get("/example/fresh")
async def example_fresh():
    """A recent phishing link from a public feed, so no live phishing URL is ever written in the README."""
    http = new_http_client(SETTINGS)
    try:
        urls, _ = await openphish_feed(http)
    finally:
        await http.aclose()
    if not urls:
        return RedirectResponse("/?example=unavailable", status_code=302)
    pick = random.choice(sorted(urls)[-50:] if len(urls) > 50 else sorted(urls))
    return RedirectResponse("/go?url=" + quote(pick, safe="") + "&source=feed", status_code=302)


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(WEB / "static" / "img" / "favicon.svg", media_type="image/svg+xml")


def main() -> None:
    import uvicorn
    uvicorn.run("server.api:app", host="127.0.0.1", port=8740, proxy_headers=True)


if __name__ == "__main__":
    main()

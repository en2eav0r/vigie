"""Reputation sources: VirusTotal, Google Safe Browsing, URLhaus, OpenPhish, AbuseIPDB.

Only Vigie's own verdict is ever published; these answers stay internal (section 10.5).
"""
from __future__ import annotations

import asyncio
import base64
import time
from urllib.parse import urlsplit

from . import ToolContext, resolve_public

_FEED: dict = {"loaded": 0.0, "urls": set(), "hosts": set()}


async def openphish_feed(http) -> tuple[set[str], set[str]]:
    # Downloaded at most once an hour and queried locally; a duplicate download is harmless.
    if time.time() - _FEED["loaded"] > 3600:
        try:
            r = await http.get("https://openphish.com/feed.txt", follow_redirects=True)
            if r.status_code == 200:
                urls = {line.strip().rstrip("/") for line in r.text.splitlines() if line.strip()}
                _FEED.update(loaded=time.time(), urls=urls,
                             hosts={urlsplit(u).hostname for u in urls if urlsplit(u).hostname})
        except Exception:
            pass
    return _FEED["urls"], _FEED["hosts"]


async def _virustotal(ctx: ToolContext, url: str) -> dict:
    if not ctx.settings.virustotal_key:
        return {"checked": False, "reason": "no API key configured"}
    if ctx.link.sensitive:
        return {"checked": False, "reason": "link carries a token; never sent to VirusTotal (N09)"}
    vid = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    r = await ctx.http.get(f"https://www.virustotal.com/api/v3/urls/{vid}",
                           headers={"x-apikey": ctx.settings.virustotal_key})
    if r.status_code == 404:
        return {"checked": True, "known": False}
    r.raise_for_status()
    stats = r.json()["data"]["attributes"].get("last_analysis_stats", {})
    return {"checked": True, "known": True, "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0), "harmless": stats.get("harmless", 0)}


async def _safe_browsing(ctx: ToolContext, url: str) -> dict:
    if not ctx.settings.safebrowsing_key:
        return {"checked": False, "reason": "no API key configured"}
    body = {
        "client": {"clientId": "vigie", "clientVersion": "0.1"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    r = await ctx.http.post(
        f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={ctx.settings.safebrowsing_key}", json=body
    )
    r.raise_for_status()
    matches = r.json().get("matches", [])
    return {"checked": True, "hit": bool(matches), "threats": sorted({m.get("threatType") for m in matches})}


async def _urlhaus(ctx: ToolContext, url: str) -> dict:
    if not ctx.settings.urlhaus_key:
        return {"checked": False, "reason": "no API key configured"}
    r = await ctx.http.post("https://urlhaus-api.abuse.ch/v1/url/", data={"url": url},
                            headers={"Auth-Key": ctx.settings.urlhaus_key})
    r.raise_for_status()
    data = r.json()
    hit = data.get("query_status") == "ok"
    return {"checked": True, "hit": hit, "threat": data.get("threat") if hit else None}


async def _openphish(ctx: ToolContext, url: str) -> dict:
    urls, hosts = await openphish_feed(ctx.http)
    if not urls:
        return {"checked": False, "reason": "feed unavailable"}
    host = urlsplit(url).hostname
    return {"checked": True, "hit": url.rstrip("/") in urls, "host_listed": host in hosts}


async def _abuseipdb(ctx: ToolContext, ip: str | None) -> dict:
    if not ctx.settings.abuseipdb_key:
        return {"checked": False, "reason": "no API key configured"}
    if not ip:
        return {"checked": False, "reason": "host did not resolve"}
    r = await ctx.http.get("https://api.abuseipdb.com/api/v2/check", params={"ipAddress": ip, "maxAgeInDays": 90},
                           headers={"Key": ctx.settings.abuseipdb_key, "Accept": "application/json"})
    r.raise_for_status()
    data = r.json()["data"]
    return {"checked": True, "ip": ip, "abuse_score": data.get("abuseConfidenceScore"), "isp": data.get("isp")}


async def _safe(coro) -> dict:
    try:
        return await coro
    except Exception as exc:
        return {"checked": False, "reason": f"error: {type(exc).__name__}"}


async def run(ctx: ToolContext, args: dict) -> dict:
    url = args.get("url") or ctx.link.url
    # A link carrying a token is checked by its public part only (N09).
    if ctx.link.sensitive:
        url = ctx.link.public
    host = urlsplit(url).hostname or ""
    addresses = await resolve_public(host)
    vt, gsb, uh, op, ab = await asyncio.gather(
        _safe(_virustotal(ctx, url)), _safe(_safe_browsing(ctx, url)), _safe(_urlhaus(ctx, url)),
        _safe(_openphish(ctx, url)), _safe(_abuseipdb(ctx, addresses[0] if addresses else None)),
    )
    return {"url_checked": url, "virustotal": vt, "safe_browsing": gsb, "urlhaus": uh,
            "openphish": op, "abuseipdb": ab}

"""Domain registration (RDAP), TLS certificate and hosting addresses."""
from __future__ import annotations

import asyncio
import re
import socket
import ssl
from datetime import datetime, timezone

from ..normalize import registered_domain
from . import API_HEADERS, ToolContext, resolve_public


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _vcard_name(entity: dict) -> str | None:
    for item in entity.get("vcardArray", [None, []])[1] if entity.get("vcardArray") else []:
        if item and item[0] in ("fn", "org") and item[3]:
            return str(item[3])
    return None


async def rdap(ctx: ToolContext, domain: str) -> dict:
    r = await ctx.http.get(f"https://rdap.org/domain/{domain}", follow_redirects=True,
                           headers={**API_HEADERS, "Accept": "application/rdap+json"})
    if r.status_code == 404:
        return {"found": False}
    r.raise_for_status()
    data = r.json()
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
    created = _parse_date(events.get("registration"))
    registrar = registrant = None
    for entity in data.get("entities", []):
        roles = entity.get("roles", [])
        if "registrar" in roles:
            registrar = _vcard_name(entity) or registrar
        if "registrant" in roles:
            registrant = _vcard_name(entity) or registrant
    age_days = (datetime.now(timezone.utc) - created).days if created else None
    return {"found": True, "registered": created.date().isoformat() if created else None, "age_days": age_days,
            "registrar": registrar, "registrant": registrant or "redacted or not published",
            "expires": (events.get("expiration") or "")[:10] or None}


def _certificate(host: str) -> dict:
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=4) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    return {"valid": True, "issuer": issuer.get("organizationName") or issuer.get("commonName"),
            "issued": not_before.date().isoformat(),
            "issued_days_ago": (datetime.now(timezone.utc) - not_before).days, "names_covered": len(sans)}


async def certificate(host: str) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_certificate, host), 5)
    except ssl.SSLCertVerificationError as exc:
        return {"valid": False, "error": f"certificate rejected: {exc.verify_message}"}
    except Exception as exc:
        return {"valid": False, "error": f"no TLS certificate obtained ({type(exc).__name__})"}




# --- Fallbacks when RDAP has nothing: many African ccTLDs (.tg, .bj, .ci...) publish no RDAP data. ---

_CREATED = re.compile(
    r"^\s*(?:creation date|created(?: on| date)?|registered(?: on)?|registration (?:date|time)|"
    r"domain registration date|record created|registered date)\s*[:.]+\s*(.+)$", re.I | re.M)
# NIC Togo and some other registries only publish an "Activation" date, which can be the last renewal.
_ACTIVATED = re.compile(r"^\s*activation(?: date)?\s*[:.]+\s*(.+)$", re.I | re.M)


def parse_whois_date(text: str, pattern: re.Pattern = _CREATED) -> datetime | None:
    """Accepts the usual WHOIS formats: 2024-05-01, 2024-05-01T10:00:00Z, 01/05/2024, 01-May-2024, 01.05.2024."""
    m = pattern.search(text)
    if not m:
        return None
    value = m.group(1).strip()
    iso = re.match(r"(\d{4})[-./](\d{2})[-./](\d{2})", value)
    if iso:
        return datetime(int(iso[1]), int(iso[2]), int(iso[3]), tzinfo=timezone.utc)
    dmy = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    if dmy:
        return datetime(int(dmy[3]), int(dmy[2]), int(dmy[1]), tzinfo=timezone.utc)
    named = re.match(r"(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ](\d{4})", value)
    if named:
        try:
            return datetime.strptime(f"{named[1]} {named[2]} {named[3]}", "%d %b %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def _whois_query(server: str, query: str) -> str:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(server, 43), 4)
    try:
        writer.write(query.encode("ascii", errors="ignore") + b"\r\n")
        await writer.drain()
        chunks = []
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), 5)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        writer.close()


async def whois(domain: str) -> dict:
    """Ask IANA which WHOIS server handles the TLD, then ask that server."""
    tld = domain.rsplit(".", 1)[-1]
    referral = await _whois_query("whois.iana.org", tld)
    server = re.search(r"^whois:\s*(\S+)", referral, re.M)
    if not server:
        return {"found": False}
    answer = await _whois_query(server.group(1), domain)
    created = parse_whois_date(answer)
    if created:
        return {"found": True, "registered": created.date().isoformat(),
                "age_days": (datetime.now(timezone.utc) - created).days, "source": f"WHOIS ({server.group(1)})"}
    activated = parse_whois_date(answer, _ACTIVATED)
    if activated:
        # Not a creation date: given to the agent as a hint, never used by the guardrails.
        return {"found": True, "activation": activated.date().isoformat(),
                "activation_days_ago": (datetime.now(timezone.utc) - activated).days,
                "note": "The registry publishes an activation date, which may be the last renewal, not the creation.",
                "source": f"WHOIS ({server.group(1)})"}
    return {"found": False, "server": server.group(1)}


async def first_certificate(ctx: ToolContext, domain: str) -> dict:
    """The first TLS certificate ever logged for the domain (public certificate transparency logs, crt.sh).
    A domain created yesterday also got its first certificate yesterday, even when its WHOIS is hidden.
    crt.sh is often overloaded; when it fails the hint is simply missing."""
    r = await ctx.http.get("https://crt.sh/", params={"q": domain, "output": "json"}, headers=API_HEADERS,
                           timeout=7.0)
    if r.status_code != 200:
        return {"found": False}
    dates = [e.get("not_before") for e in r.json() if e.get("not_before")]
    if not dates:
        return {"found": False}
    first = datetime.fromisoformat(min(dates)[:19]).replace(tzinfo=timezone.utc)
    return {"found": True, "first_seen": first.date().isoformat(),
            "age_days": (datetime.now(timezone.utc) - first).days, "certificates_logged": len(dates)}


async def hosting(ctx: ToolContext, ip: str) -> dict:
    """Open ports, tags and known vulnerabilities of the hosting server (Shodan InternetDB, free, no key)."""
    r = await ctx.http.get(f"https://internetdb.shodan.io/{ip}", timeout=5.0)
    if r.status_code != 200:
        return {}
    data = r.json()
    return {"ports": data.get("ports", [])[:10], "tags": data.get("tags", [])[:6],
            "known_vulnerabilities": len(data.get("vulns", [])), "hostnames_on_ip": len(data.get("hostnames", []))}


async def _safe(coro, default):
    try:
        return await coro
    except Exception:
        return default


async def lookup(ctx: ToolContext, domain: str) -> dict:
    domain = domain.strip().lower().removeprefix("www.") if domain else ctx.link.registered_domain
    if domain in ctx._domain_cache:
        return ctx._domain_cache[domain]
    base = registered_domain(domain)
    reg, cert, crt = await asyncio.gather(_safe(rdap(ctx, base), {"found": None}), certificate(domain),
                                          _safe(first_certificate(ctx, base), {"found": None}))
    if reg.get("age_days") is None:
        found = await _safe(whois(base), {"found": None})
        if found.get("found"):
            reg = {**reg, **found}
    elif reg.get("found"):
        reg["source"] = "RDAP"
    try:
        addresses = await resolve_public(domain)
    except Exception as exc:
        addresses = [f"refused: {exc}"]
    usable = addresses and not addresses[0].startswith("refused")
    result = {
        "domain": domain,
        "registered_domain": base,
        "registration": reg,
        "first_certificate": crt,
        "tls": cert,
        "addresses": addresses[:4],
        "hosting": await _safe(hosting(ctx, addresses[0]), {}) if usable else {},
    }
    ctx._domain_cache[domain] = result
    return result


def age_days(result: dict) -> tuple[int | None, str]:
    """The domain's age from a real creation date (RDAP or WHOIS), the only age the guardrails may use.
    An activation date or a first certificate is only a hint for the agent."""
    reg = result.get("registration") or {}
    if reg.get("age_days") is not None:
        return reg["age_days"], reg.get("source", "registration")
    return None, ""


async def run(ctx: ToolContext, args: dict) -> dict:
    return await lookup(ctx, args.get("domain") or ctx.link.host)

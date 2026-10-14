"""Compare two domains: age, registrar, certificate, hosting and favicon."""
from __future__ import annotations

import asyncio
import hashlib

from ..normalize import registered_domain
from . import resolve_public
from .domain import lookup


async def _favicon_hash(ctx, domain: str) -> str | None:
    try:
        await resolve_public(domain)
        r = await ctx.http.get(f"https://{domain}/favicon.ico", follow_redirects=True)
        if r.status_code == 200 and 0 < len(r.content) < 500_000:
            return hashlib.md5(r.content).hexdigest()
    except Exception:
        return None
    return None


async def run(ctx, args: dict) -> dict:
    a = (args.get("domain_a") or "").lower().removeprefix("www.")
    b = (args.get("domain_b") or "").lower().removeprefix("www.")
    if not a or not b:
        return {"error": "two domains are required"}
    da, db, fa, fb = await asyncio.gather(lookup(ctx, a), lookup(ctx, b), _favicon_hash(ctx, a), _favicon_hash(ctx, b))
    ra, rb = da["registration"], db["registration"]
    return {
        "domain_a": a,
        "domain_b": b,
        "same_registered_domain": registered_domain(a) == registered_domain(b),
        "age_days": {a: ra.get("age_days"), b: rb.get("age_days")},
        "registrar": {a: ra.get("registrar"), b: rb.get("registrar")},
        "same_registrar": bool(ra.get("registrar")) and ra.get("registrar") == rb.get("registrar"),
        "certificate_issuer": {a: da["tls"].get("issuer"), b: db["tls"].get("issuer")},
        "hosting": {a: da["addresses"], b: db["addresses"]},
        "shared_hosting_address": bool(set(da["addresses"]) & set(db["addresses"])),
        "same_favicon": bool(fa and fb and fa == fb),
        "favicon_found": {a: bool(fa), b: bool(fb)},
    }

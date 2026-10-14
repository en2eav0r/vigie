"""Verdicts already given on a domain, for any user."""
from __future__ import annotations

from ..normalize import registered_domain


async def run(ctx, args: dict) -> dict:
    domain = registered_domain((args.get("domain") or ctx.link.host).lower())
    history = ctx.store.domain_history(domain)
    return {"domain": domain, "previous_verdicts": history, "count": len(history)}

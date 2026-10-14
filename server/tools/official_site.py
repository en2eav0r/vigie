"""A brand's official domain from two independent sources: Wikidata (P856) and the local brand base.

An official domain counts only when two sources agree, because a model can invent a plausible one.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..normalize import registered_domain
from . import API_HEADERS
from .urlscan import BRANDS

WIKIDATA = "https://www.wikidata.org/w/api.php"


def _match_brand(name: str) -> dict | None:
    target = re.sub(r"[^a-z0-9]", "", name.lower())
    for brand in BRANDS:
        for candidate in [brand["name"], *brand.get("aliases", [])]:
            if re.sub(r"[^a-z0-9]", "", candidate.lower()) == target:
                return brand
    for brand in BRANDS:
        if re.sub(r"[^a-z0-9]", "", brand["name"].lower()) in target:
            return brand
    return None


async def wikidata_official(ctx, brand: str, prefer: set[str] | None = None) -> dict | None:
    """The official website (P856) of the Wikidata entity matching the brand. Several entities can share a name
    (Orange the company, the colour, the fruit): one whose website matches a domain from the local brand base
    wins, which is exactly the agreement between two sources that Vigie looks for."""
    r = await ctx.http.get(WIKIDATA, params={"action": "wbsearchentities", "search": brand, "language": "en",
                                             "type": "item", "limit": 10, "format": "json"},
                           headers=API_HEADERS)
    r.raise_for_status()
    ids = [item["id"] for item in r.json().get("search", [])]
    if not ids:
        return None
    r = await ctx.http.get(WIKIDATA, params={"action": "wbgetentities", "ids": "|".join(ids),
                                             "props": "claims|labels|descriptions", "languages": "en",
                                             "format": "json"}, headers=API_HEADERS)
    r.raise_for_status()
    entities = r.json().get("entities", {})
    found = []
    for qid in ids:
        entity = entities.get(qid, {})
        claims = entity.get("claims", {})
        inception = None
        for c in claims.get("P571", []):
            t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time")
            if t:
                inception = t.lstrip("+")[:4]
        for claim in claims.get("P856", []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if value:
                host = (urlsplit(value).hostname or "").lower().removeprefix("www.")
                found.append({"entity": qid, "label": entity.get("labels", {}).get("en", {}).get("value"),
                              "description": entity.get("descriptions", {}).get("en", {}).get("value"),
                              "website": value, "domain": registered_domain(host), "founded": inception})
    if not found:
        return None
    for item in found:
        if prefer and item["domain"] in prefer:
            return item
    return found[0]


async def run(ctx, args: dict) -> dict:
    brand = (args.get("brand") or "").strip()
    if not brand:
        return {"error": "a brand name is required"}
    local = _match_brand(brand)
    try:
        prefer = {registered_domain(d) for d in local["domains"]} if local else None
        wiki = await wikidata_official(ctx, local["name"] if local else brand, prefer)
    except Exception as exc:
        wiki = None
        wiki_error = type(exc).__name__
    else:
        wiki_error = None
    local_domains = [registered_domain(d) for d in local["domains"]] if local else []
    candidates: dict[str, list[str]] = {}
    for d in local_domains:
        candidates.setdefault(d, []).append("local brand base")
    if wiki:
        candidates.setdefault(wiki["domain"], []).append("Wikidata")
    confirmed = [d for d, sources in candidates.items() if len(sources) >= 2]
    return {
        "brand": local["name"] if local else brand,
        "local_brand_base": {"domains": local_domains, "founded": local.get("founded")} if local else None,
        "wikidata": wiki or ({"error": wiki_error} if wiki_error else None),
        "candidates": [{"domain": d, "sources": s} for d, s in candidates.items()],
        "confirmed_official_domains": confirmed,
        "confirmed": bool(confirmed),
        "note": "" if confirmed else "Fewer than two sources agree. Confirm with another source before relying on it.",
    }

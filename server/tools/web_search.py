"""Web search through the Brave Search API, for models without built-in search."""
from __future__ import annotations


async def run(ctx, args: dict) -> dict:
    query = (args.get("query") or "").strip()[:200]
    if not query:
        return {"error": "a query is required"}
    r = await ctx.http.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": 6},
                           headers={"X-Subscription-Token": ctx.settings.brave_key, "Accept": "application/json"})
    r.raise_for_status()
    results = r.json().get("web", {}).get("results", [])
    return {"query": query, "results": [{"title": x.get("title"), "url": x.get("url"),
                                         "snippet": (x.get("description") or "")[:240]} for x in results]}

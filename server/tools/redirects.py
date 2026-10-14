"""Follow the redirect chain without running JavaScript."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from . import ToolContext, resolve_public

MAX_HOPS = 10
MAX_BODY = 400_000
META_REFRESH = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+content=["'][^"']*url=([^"'>]+)""", re.I)
JS_LOCATION = re.compile(r"""(?:window\.|document\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""", re.I)


async def run(ctx: ToolContext, args: dict) -> dict:
    url = args.get("url") or ctx.link.url
    method = "HEAD" if ctx.link.sensitive else "GET"
    hops: list[dict] = []
    status = None
    content_type = ""
    for _ in range(MAX_HOPS):
        host = urlsplit(url).hostname or ""
        await resolve_public(host)
        response = await ctx.http.request(method, url)
        status = response.status_code
        content_type = response.headers.get("content-type", "")
        hops.append({"url": url, "status": status})
        location = response.headers.get("location")
        if status in (301, 302, 303, 307, 308) and location:
            url = urljoin(url, location)
            continue
        if method == "GET" and "html" in content_type:
            body = response.text[:MAX_BODY]
            ctx.page_body, ctx.page_url = body, url
            target = META_REFRESH.search(body)
            # A script redirect only counts on a near-empty page; full pages often mention location in widgets.
            if not target and len(re.sub(r"<script.*?</script>", "", body, flags=re.S | re.I)) < 1500:
                target = JS_LOCATION.search(body)
            if target and len(hops) < MAX_HOPS:
                next_url = urljoin(url, target.group(1).strip())
                if next_url != url and next_url.startswith("http"):
                    hops[-1]["client_redirect"] = True
                    url = next_url
                    continue
        break
    final = urlsplit(url)
    return {
        "hops": hops,
        "redirect_count": len(hops) - 1,
        "final_url": url,
        "final_host": final.hostname,
        "final_status": status,
        "content_type": content_type.split(";")[0],
        "left_original_domain": (final.hostname or "") != ctx.link.host,
        "note": "HEAD requests only: the link carries a token and was not opened." if ctx.link.sensitive else "",
    }

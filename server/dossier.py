"""The server prepares the case file before any AI call.

All the measuring tools run here, in parallel and for free; the AI only receives a compact summary
(about 1,000 tokens) and asks for the identity checks it still needs. This keeps an investigation to one
to three model turns instead of eight to twelve, which divides its cost by five to eight.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from .normalize import registered_domain
from .tools import ToolContext, ToolSpec, run_tool
from .tools import compare, domain, memory, official_site, redirects, reputation, signals, urlscan

Step = Callable[..., Awaitable[int]]
PAGE_DEADLINE = 18.0   # seconds from the start to wait for the urlscan.io capture


def _spec(name: str, fn) -> ToolSpec:
    return ToolSpec(name, "", {}, fn)


def blocklist_hits(ctx: ToolContext) -> list[str]:
    """Reasons a blocklist gives to block the link. Any hit blocks it, whatever an AI might say (section 4.3)."""
    rep = ctx.last("reputation") or {}
    hits = []
    if (rep.get("safe_browsing") or {}).get("hit"):
        hits.append("Listed by Google Safe Browsing")
    if (rep.get("urlhaus") or {}).get("hit"):
        hits.append("Listed by URLhaus")
    if (rep.get("openphish") or {}).get("hit"):
        hits.append("Listed by OpenPhish")
    malicious = (rep.get("virustotal") or {}).get("malicious") or 0
    if malicious >= 3:
        hits.append(f"Flagged by {malicious} VirusTotal engines")
    return hits


def _thin(page: dict) -> bool:
    """A read that tells almost nothing: error, or little text and no form."""
    if page.get("error") or page.get("source") == "none":
        return not page.get("source") == "none"
    text = (page.get("untrusted_page_data") or {}).get("visible_text", "")
    return len(text) < 200 and not page.get("form_count")


def own_brand(ctx: ToolContext) -> str | None:
    """The brand whose official domain this link is on, according to the local brand base."""
    from .tools.urlscan import BRANDS
    for brand in BRANDS:
        if any(ctx.link.registered_domain == registered_domain(d) for d in brand["domains"]):
            return brand["name"]
    return None


def claimed_brand(ctx: ToolContext) -> str | None:
    """Which company the link claims to be, from the strongest signal to the weakest. A brand merely mentioned
    in the page text counts only when the page also asks for credentials (a news page may name ten banks)."""
    own = own_brand(ctx)
    if own:
        return own
    sig = ctx.last("signals") or {}
    if sig.get("brand_name_outside_official_domain"):
        return sig["brand_name_outside_official_domain"][0]["brand"]
    page = ctx.last("urlscan") or {}
    from .tools.urlscan import brands_mentioned
    in_title = brands_mentioned(page.get("title") or "")
    if in_title:
        return in_title[0]
    asks = any(page.get(k) for k in ("asks_for_login", "asks_for_card", "asks_for_pin_or_otp", "asks_for_mobile_money"))
    if asks and page.get("brands_mentioned"):
        return page["brands_mentioned"][0]
    return None


async def prepare(ctx: ToolContext, step: Step, labels: tuple[Callable, Callable]) -> None:
    """Run every measuring tool and record the results in `ctx`. Steps are streamed to the client."""
    running_label, done_label = labels
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def tool(name: str, fn, args: dict) -> dict:
        sid = await step(name, running_label(name, args), "running")
        result = await run_tool(ctx, _spec(name, fn), args)
        await step(name, done_label(name, args, result), "done", sid)
        return result

    # The urlscan.io capture takes 10 to 20 seconds: start it first, read it last.
    scan_id = await urlscan.submit(ctx, ctx.link.url)
    await asyncio.gather(
        tool("signals", signals.run, {"url": ctx.link.url}),
        tool("redirects", redirects.run, {"url": ctx.link.url}),
        tool("domain", domain.run, {"domain": ctx.link.host}),
        tool("reputation", reputation.run, {"url": ctx.link.url}),
        tool("memory", memory.run, {"domain": ctx.link.registered_domain}),
    )
    if blocklist_hits(ctx):
        return  # already decided: no need to read the page or to ask the AI

    red = ctx.last("redirects") or {}
    final_host = (red.get("final_host") or "").lower()
    if final_host and registered_domain(final_host) != ctx.link.registered_domain:
        await tool("domain", domain.run, {"domain": final_host})   # the link lands on another domain

    sid = await step("urlscan", running_label("urlscan", {}), "running")
    # The HTML read without JavaScript is usually enough. Wait for the urlscan.io capture (which runs the
    # page's JavaScript) only when that read shows an almost empty page, typical of pages built by scripts.
    try:
        page = await asyncio.wait_for(urlscan.direct(ctx, ctx.link.url), ctx.settings.tool_timeout)
    except Exception as exc:
        page = {"error": f"page not readable ({type(exc).__name__})"}
    if scan_id and _thin(page):
        captured = await urlscan.collect(ctx, scan_id, started + PAGE_DEADLINE)
        if captured:
            page = captured
    ctx.record("urlscan", {"args": {"url": ctx.link.url}, **page})
    await step("urlscan", done_label("urlscan", {}, page), "done", sid)

    brand = claimed_brand(ctx)
    if brand:
        found = await tool("official_site", official_site.run, {"brand": brand})
        confirmed = found.get("confirmed_official_domains") or []
        host = final_host or ctx.link.host
        if confirmed and registered_domain(host) not in confirmed:
            await tool("compare", compare.run, {"domain_a": registered_domain(host), "domain_b": confirmed[0]})


def _flags(d: dict, keys: tuple[str, ...]) -> list[str]:
    return [k for k in keys if d.get(k)]


def compact(ctx: ToolContext) -> dict:
    """The case file for the AI: only what helps a decision, in a few hundred tokens."""
    link = ctx.link
    out: dict = {"link": {"url": link.url, "host": link.host}}
    if link.display_host != link.host:
        out["link"]["unicode_host"] = link.display_host
    if link.sensitive:
        out["link"]["carries_private_token"] = True

    sig = ctx.last("signals") or {}
    out["address"] = {
        "warnings": _flags(sig, ("punycode", "mixed_scripts", "raw_ip_host", "high_risk_tld", "url_shortener",
                                 "shared_hosting", "brand_in_subdomain", "at_sign_in_url", "plain_http")),
        "brand_name_outside_official_domain": [b["brand"] for b in sig.get("brand_name_outside_official_domain", [])],
        "lure_words": sig.get("lure_words", []),
    }

    red = ctx.last("redirects") or {}
    out["redirects"] = {"count": red.get("redirect_count"), "final_url": red.get("final_url")} if not red.get(
        "error") else {"error": red.get("error")}

    if sig.get("shared_hosting"):
        out["address"]["shared_hosting_platform"] = (
            "Anyone can publish a page on this platform: the platform domain's age and certificate say nothing "
            "about who made this page. Judge the page itself.")

    domains = []
    for item in ctx.results.get("domain", []):
        if item.get("error"):
            continue
        if sig.get("shared_hosting") and item.get("registered_domain") == link.registered_domain:
            continue  # the platform's age would mislead
        age, source = domain.age_days(item)
        reg = item.get("registration") or {}
        entry = {"domain": item.get("domain"), "age_days": age, "age_source": source or None,
                 "registrar": reg.get("registrar"), "tls_issuer": (item.get("tls") or {}).get("issuer"),
                 "tls_valid": (item.get("tls") or {}).get("valid")}
        if reg.get("activation"):
            entry["registry_activation_days_ago"] = reg.get("activation_days_ago")
            entry["activation_note"] = "may be the last renewal, not the creation"
        crt = item.get("first_certificate") or {}
        if crt.get("age_days") is not None:
            entry["first_certificate_days_ago"] = crt["age_days"]
        host = item.get("hosting") or {}
        if host.get("tags") or host.get("known_vulnerabilities"):
            entry["hosting"] = {"tags": host.get("tags"), "known_vulnerabilities": host.get("known_vulnerabilities")}
        domains.append({k: v for k, v in entry.items() if v not in (None, [], {})})
    out["domains"] = domains

    page = ctx.last("urlscan") or {}
    if page.get("source") == "none":
        out["page"] = {"not_opened": page.get("note")}
    elif page and not page.get("error"):
        out["page"] = {
            "source": page.get("source"),
            "title": page.get("title"),
            "brands_mentioned": page.get("brands_mentioned"),
            "sign_in_with_buttons": page.get("sign_in_with") or None,
            "asks_for": _flags(page, ("asks_for_login", "asks_for_card", "asks_for_pin_or_otp",
                                      "asks_for_mobile_money")),
            "form_sends_to": [t for t in page.get("form_targets", []) if t and t != link.host],
            "lure_phrases": page.get("lure_phrases"),
            "untrusted_page_text": (page.get("untrusted_page_data") or {}).get("visible_text", "")[:1200],
        }
    else:
        out["page"] = {"error": page.get("error", "not read")}

    rep = ctx.last("reputation") or {}
    out["blocklists"] = {
        name: ("listed" if (rep.get(key) or {}).get("hit") else "not listed") if (rep.get(key) or {}).get("checked")
        else "not checked"
        for key, name in (("safe_browsing", "google_safe_browsing"), ("urlhaus", "urlhaus"), ("openphish", "openphish"))
    }
    vt = rep.get("virustotal") or {}
    if vt.get("checked"):
        out["blocklists"]["virustotal_engines_flagging"] = vt.get("malicious", 0) if vt.get("known") else "unknown url"
    abuse = rep.get("abuseipdb") or {}
    if abuse.get("checked"):
        out["blocklists"]["hosting_ip_abuse_score"] = abuse.get("abuse_score")

    mem = ctx.last("memory") or {}
    if mem.get("previous_verdicts"):
        out["previous_verdicts_on_domain"] = mem["previous_verdicts"][:3]

    official = ctx.last("official_site")
    if official and not official.get("error"):
        base = (official.get("local_brand_base") or {}).get("domains") or []
        out["identity"] = {"claimed_brand": official.get("brand"),
                           "official_domains_confirmed_by_two_sources": official.get("confirmed_official_domains"),
                           "candidates": official.get("candidates"),
                           # Vigie's own brand base is verified by hand: a link on a domain listed there IS
                           # that brand's site, whatever Wikidata says.
                           "link_domain_listed_in_vigie_brand_base": link.registered_domain in base}
        cmp_ = ctx.last("compare")
        if cmp_ and not cmp_.get("error"):
            out["identity"]["comparison"] = {k: cmp_.get(k) for k in (
                "same_registered_domain", "age_days", "same_registrar", "shared_hosting_address", "same_favicon")}
    return out


def as_text(dossier: dict) -> str:
    return json.dumps(dossier, ensure_ascii=False, separators=(",", ":"), default=str)

"""Hard-coded rules that run after the agent (section 4.3). They can only block, never allow,
so the agent remains the only one able to say "safe" (S06)."""
from __future__ import annotations

import asyncio

from .normalize import registered_domain
from .tools import ToolContext, domain as domain_tool, reputation, run_tool, ToolSpec

VERDICTS = ("safe", "blocked")
THREATS = ("none", "phishing", "impersonation", "malware", "scam", "other")


def validate(raw: dict | None) -> tuple[dict | None, str]:
    """Return a clean verdict, or None and the reason it was rejected."""
    if not isinstance(raw, dict):
        return None, "The agent did not return a verdict."
    verdict = raw.get("verdict")
    explanation = (raw.get("explanation") or "").strip()
    evidence = raw.get("decisive_evidence")
    if verdict not in VERDICTS:
        return None, "The agent's answer was not valid."
    if not explanation or len(explanation) > 600:
        return None, "The agent's answer was not valid."
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        return None, "The agent's answer was not valid."
    threat = raw.get("threat_type") if raw.get("threat_type") in THREATS else "other"
    return {
        "verdict": verdict,
        "threat_type": "none" if verdict == "safe" else threat,
        "impersonated_brand": (raw.get("impersonated_brand") or "").strip()[:80],
        "official_domain": (raw.get("official_domain") or "").strip().lower()[:120],
        "decisive_evidence": [e.strip()[:160] for e in evidence[:5] if e.strip()],
        "explanation": explanation,
    }, ""


async def _ensure(ctx: ToolContext, name: str, fn, args: dict) -> dict:
    found = ctx.last(name)
    if found is not None and not found.get("error"):
        return found
    spec = ToolSpec(name, "", {}, fn)
    return await run_tool(ctx, spec, args)


async def apply(ctx: ToolContext, verdict: dict) -> tuple[dict, list[str]]:
    """Return the final verdict and the guardrails that fired."""
    fired: list[str] = []
    rep, dom = await asyncio.gather(
        _ensure(ctx, "reputation", reputation.run, {"url": ctx.link.url}),
        _ensure(ctx, "domain", domain_tool.run, {"domain": ctx.link.host}),
    )
    if (rep.get("safe_browsing") or {}).get("hit"):
        fired.append("Listed by Google Safe Browsing")
    if (rep.get("urlhaus") or {}).get("hit"):
        fired.append("Listed by URLhaus")
    if (rep.get("openphish") or {}).get("hit"):
        fired.append("Listed by OpenPhish")
    if ((rep.get("virustotal") or {}).get("malicious") or 0) >= 3:
        fired.append(f"Flagged by {rep['virustotal']['malicious']} VirusTotal engines")

    # A confirmed official domain that differs, a scanned domain under 30 days old and a login form.
    official = ctx.last("official_site") or {}
    confirmed = official.get("confirmed_official_domains") or []
    page = ctx.last("urlscan") or {}
    final_host = ((ctx.last("redirects") or {}).get("final_host") or ctx.link.host).lower()
    # Only a real creation date counts here; an activation date or a first certificate never blocks on its own.
    age, _ = domain_tool.age_days(dom)
    asks = (page.get("asks_for_login") or page.get("asks_for_card") or page.get("asks_for_pin_or_otp")
            or page.get("asks_for_mobile_money"))
    if confirmed and registered_domain(final_host) not in confirmed and age is not None and age < 30 and asks:
        fired.append(f"New domain asking for credentials while the official site is {confirmed[0]}")

    if fired and verdict["verdict"] == "safe":
        verdict = {**verdict, "verdict": "blocked", "threat_type": "phishing",
                   "explanation": "A hard safety rule blocked this link: " + fired[0].lower() + ". "
                                  "Vigie never opens a link that a blocklist reports."}
    if fired:
        verdict = {**verdict, "decisive_evidence": list(dict.fromkeys(verdict["decisive_evidence"] + fired))[:6]}
    return verdict, fired

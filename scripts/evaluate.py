"""Compare AI models on the same case files.

    python scripts/evaluate.py build [N]          build the case files (N real sites, N phishing links from OpenPhish; 15)
    python scripts/evaluate.py run openai:gpt-4.1-nano gemini:gemini-3.5-flash-lite ...

The case files are built once and reused, so every model sees exactly the same evidence and the free
checks are not run again. For phishing links the blocklist results are hidden from the model: those links
are already listed, and the question is whether the AI alone would catch a site no blocklist knows yet.
No phishing URL is written in this repository: they are fetched from the public feed when building.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server import dossier  # noqa: E402
from server.agent import SYSTEM_PROMPT, VERDICT_TOOL, done_label, running_label  # noqa: E402
from server.config import settings  # noqa: E402
from server.db import Store  # noqa: E402
from server.guardrails import validate  # noqa: E402
from server.normalize import normalise  # noqa: E402
from server.providers import ProviderChoice, ProviderError, make_provider  # noqa: E402
from server.tools import ToolContext, new_http_client, registry, run_tool  # noqa: E402
from server.tools.reputation import openphish_feed  # noqa: E402

EVAL = REPO / "data" / "eval"
# Real sites people in Togo and West Africa use, then large services that phishing pages imitate most.
LEGITIMATE = [
    "https://ecobank.com", "https://www.orabank.net", "https://www.ubagroup.com", "https://togocom.tg",
    "https://otr.tg", "https://www.republicoftogo.com", "https://www.wave.com", "https://www.mtn.com",
    "https://www.orange.com", "https://www.bceao.int", "https://www.wikipedia.org", "https://www.google.com",
    "https://www.youtube.com", "https://www.paypal.com", "https://www.boad.org",
    "https://www.bankofafrica.net", "https://www.afdb.org", "https://www.airtel.africa", "https://www.moov-africa.tg",
    "https://www.orange.ci", "https://www.jeuneafrique.com", "https://www.rfi.fr", "https://www.africanews.com",
    "https://www.worldbank.org", "https://www.imf.org", "https://www.who.int", "https://www.un.org",
    "https://www.westernunion.com", "https://www.worldremit.com", "https://www.visa.com", "https://www.mastercard.com",
    "https://www.microsoft.com", "https://www.apple.com", "https://www.amazon.com", "https://www.facebook.com",
    "https://www.instagram.com", "https://www.whatsapp.com", "https://www.linkedin.com", "https://github.com",
    "https://www.netflix.com", "https://www.bbc.com", "https://www.lemonde.fr", "https://www.booking.com",
    "https://www.airbnb.com", "https://www.ebay.com", "https://outlook.live.com", "https://www.office.com",
    "https://www.dropbox.com", "https://zoom.us", "https://www.spotify.com", "https://www.adobe.com",
    "https://www.binance.com", "https://www.coinbase.com", "https://stripe.com", "https://www.cloudflare.com",
    "https://www.mozilla.org", "https://www.python.org", "https://www.jumia.com.ng", "https://www.dhl.com",
    "https://www.icloud.com",
]
HIDDEN_BLOCKLISTS = {k: {"checked": True, "hit": False} for k in ("safe_browsing", "urlhaus", "openphish")}


async def _build_one(url: str, label: str, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        s = settings()
        link = normalise(url)
        ctx = ToolContext(link, s, Store(":memory:"), new_http_client(s))

        async def step(*args, **kwargs):
            return 0
        try:
            await asyncio.wait_for(dossier.prepare(ctx, step, (running_label, done_label)), 40)
        except Exception as exc:
            print(f"  {label:9} {url[:60]}  prepare stopped: {type(exc).__name__}")
        finally:
            await ctx.http.aclose()
        listed = dossier.blocklist_hits(ctx)
        print(f"  {label:9} {link.host[:50]:50} listed={bool(listed)}")
        return {"url": link.url, "label": label, "listed": listed, "results": ctx.results}


async def build(count: int = 15) -> None:
    legitimate = LEGITIMATE[:count]
    s = settings()
    http = new_http_client(s)
    urls, _ = await openphish_feed(http)
    await http.aclose()
    seen, phishing = set(), []
    for url in sorted(urls, reverse=True):
        host = normalise(url).registered_domain
        if host not in seen:
            seen.add(host)
            phishing.append(url)
        if len(phishing) == count:
            break
    sem = asyncio.Semaphore(5)
    cases = await asyncio.gather(*(_build_one(u, "legit", sem) for u in legitimate),
                                 *(_build_one(u, "phishing", sem) for u in phishing))
    EVAL.mkdir(parents=True, exist_ok=True)
    (EVAL / "cases.json").write_text(json.dumps([c for c in cases if c], default=str), encoding="utf-8")
    print(f"{len(cases)} case files written to data/eval/cases.json")


async def _ask(provider_name: str, model: str, case: dict) -> dict:
    s = settings()
    link = normalise(case["url"])
    ctx = ToolContext(link, s, Store(":memory:"), new_http_client(s))
    ctx.results = json.loads(json.dumps(case["results"]))
    if case["label"] == "phishing":
        rep = ctx.last("reputation") or {}
        rep.update(HIDDEN_BLOCKLISTS)
        rep["virustotal"] = {"checked": False}
    provider = make_provider(s, ProviderChoice(provider_name, model))
    extra = [t for t in registry(s, include_web_search=False) if t.name in ("official_site", "compare", "domain")]
    by_name = {t.name: t for t in extra}
    conversation = provider.start(SYSTEM_PROMPT, "Decide whether this link may open. Case file built by Vigie's "
                                  f"tools:\nDOSSIER_JSON: {dossier.as_text(dossier.compact(ctx))}", [*extra, VERDICT_TOOL])
    bill = {"cost": 0.0, "in": 0, "out": 0, "turns": 0}
    started = time.monotonic()
    verdict, error = None, ""
    reminded = False
    try:
        for _ in range(s.max_agent_turns):
            turn = await asyncio.wait_for(conversation.next(), 60)
            bill["turns"] += 1
            bill["cost"] += turn.cost_usd
            bill["in"] += turn.input_tokens
            bill["out"] += turn.output_tokens
            done = [c for c in turn.calls if c.name == "submit_verdict"]
            if done:
                verdict = validate(done[-1].args)[0]
                break
            others = [c for c in turn.calls if c.name in by_name]
            if not others:
                if reminded:
                    error = "no verdict"
                    break
                reminded = True
                conversation.remind("Call submit_verdict now with your verdict.")
                continue
            results = []
            for call in others:
                r = await run_tool(ctx, by_name[call.name], call.args)
                results.append((call.id, json.dumps(r, default=str)[:4000], bool(r.get("error"))))
            conversation.add_results(results)
    except (ProviderError, asyncio.TimeoutError) as exc:
        error = str(exc) or type(exc).__name__
    finally:
        await ctx.http.aclose()
    expected = "blocked" if case["label"] == "phishing" else "safe"
    got = verdict["verdict"] if verdict else "unknown"
    return {"url": case["url"], "label": case["label"], "expected": expected, "got": got, "correct": got == expected,
            "explanation": verdict["explanation"] if verdict else "", "error": error,
            "seconds": round(time.monotonic() - started, 1), **bill}


async def run(specs: list[str]) -> None:
    cases = json.loads((EVAL / "cases.json").read_text(encoding="utf-8"))
    lines = [f"# Vigie model evaluation, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
             f"{sum(c['label'] == 'legit' for c in cases)} legitimate sites, "
             f"{sum(c['label'] == 'phishing' for c in cases)} phishing links (blocklists hidden from the model).", "",
             "| Model | Phishing blocked | Legit opened | Errors | Avg cost | Avg tokens in/out | Avg time |",
             "|---|---|---|---|---|---|---|"]
    details = []
    for spec in specs:
        provider_name, model = spec.split(":", 1)
        rows = []
        for case in cases:
            row = await _ask(provider_name, model, case)
            rows.append(row)
            mark = "ok " if row["correct"] else "BAD"
            print(f"  {spec:32} {mark} {row['label']:8} {row['got']:8} ${row['cost']:.5f} {row['seconds']:5}s "
                  f"{normalise(row['url']).host[:40]} {row['error'][:50]}")
            if provider_name == "gemini":
                await asyncio.sleep(13)   # free tier: a few requests per minute
        phish = [r for r in rows if r["label"] == "phishing"]
        legit = [r for r in rows if r["label"] == "legit"]
        errors = sum(1 for r in rows if r["error"])
        answered = [r for r in rows if not r["error"]] or rows
        lines.append(f"| {spec} | {sum(r['correct'] for r in phish)}/{len(phish)} | "
                     f"{sum(r['correct'] for r in legit)}/{len(legit)} | {errors} | "
                     f"${statistics.mean(r['cost'] for r in answered):.5f} | "
                     f"{statistics.mean(r['in'] for r in answered):.0f}/{statistics.mean(r['out'] for r in answered):.0f} | "
                     f"{statistics.mean(r['seconds'] for r in answered):.1f} s |")
        details.append({"model": spec, "rows": rows})
    report = "\n".join(lines)
    stamp = f"{datetime.now(timezone.utc):%Y%m%d-%H%M}"
    (EVAL / f"report-{stamp}.md").write_text(report + "\n", encoding="utf-8")
    (EVAL / f"details-{stamp}.json").write_text(json.dumps(details, indent=1), encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        asyncio.run(build(int(sys.argv[2]) if len(sys.argv) > 2 else 15))
    elif sys.argv[1:2] == ["run"] and len(sys.argv) > 2:
        asyncio.run(run(sys.argv[2:]))
    else:
        print(__doc__)

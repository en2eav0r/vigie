"""Catalogue of the AI models available with the configured keys.

    python -m server.models list                    models per configured provider
    python -m server.models probe gemini MODEL      check tool calling with one small real request
    python -m server.models probe-all gemini        probe every candidate model of a provider

Results of probes are kept in data/model_probes.json. A model that cannot call tools is never used (section 5.2).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

from .config import REPO, Settings, settings
from .providers import ProviderChoice, ProviderError, make_provider
from .tools import ToolSpec

PROBES = REPO / "data" / "model_probes.json"
# Model families that are not text agents (speech, images, music, robots, research products...).
NOT_AGENTS = re.compile(r"(tts|image|imagen|lyria|robotics|computer-use|deep-research|antigravity|transcribe|"
                        r"nano-banana|embedding|aqa|veo|audio|realtime|whisper|dall-e|moderation|omni|live)", re.I)


def _keys(cfg: Settings) -> dict[str, str]:
    import os
    from .providers import COMPAT
    keys = {"anthropic": cfg.anthropic_key, "gemini": cfg.gemini_key}
    for name, (env, _) in COMPAT.items():
        if env and name != "openai_compat":
            keys[name] = os.environ.get(env, "").strip()
    return keys


def list_models(provider: str, cfg: Settings | None = None) -> list[str]:
    cfg = cfg or settings()
    key = _keys(cfg).get(provider, "")
    if not key:
        return []
    if provider == "gemini":
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 500},
                      headers={"x-goog-api-key": key}, timeout=20)
        r.raise_for_status()
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    elif provider == "anthropic":
        r = httpx.get("https://api.anthropic.com/v1/models", params={"limit": 100}, timeout=20,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        r.raise_for_status()
        names = [m["id"] for m in r.json().get("data", [])]
    else:
        from .providers import COMPAT
        base = COMPAT[provider][1]
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        r.raise_for_status()
        names = [m["id"] for m in r.json().get("data", [])]
    return sorted(n for n in names if not NOT_AGENTS.search(n))


def load_probes() -> dict:
    try:
        return json.loads(PROBES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


ECHO = ToolSpec("record_answer", "Record the answer to the question.",
                {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"],
                 "additionalProperties": False}, fn=None)


async def probe(provider: str, model: str) -> dict:
    """One small request: the model must answer by calling a tool."""
    cfg = settings()
    started = time.monotonic()
    try:
        agent = make_provider(cfg, ProviderChoice(name=provider, model=model))
        conversation = agent.start("You answer only by calling the record_answer tool.",
                                   "What is the capital of Togo? Call record_answer with the city.", [ECHO])
        turn = await asyncio.wait_for(conversation.next(), 60)
        calls = [c for c in turn.calls if c.name == "record_answer"]
        ok = bool(calls) and "lom" in str(calls[0].args.get("answer", "")).lower()
        result = {"tool_calling": bool(calls), "correct": ok, "error": ""}
    except (ProviderError, asyncio.TimeoutError) as exc:
        result = {"tool_calling": False, "correct": False, "error": str(exc) or type(exc).__name__}
    result.update(seconds=round(time.monotonic() - started, 1), checked=time.strftime("%Y-%m-%d"))
    probes = load_probes()
    probes[f"{provider}/{model}"] = result
    PROBES.parent.mkdir(parents=True, exist_ok=True)
    PROBES.write_text(json.dumps(probes, indent=1, sort_keys=True), encoding="utf-8")
    return result


def main(argv: list[str]) -> int:
    cfg = settings()
    if not argv or argv[0] == "list":
        probes = load_probes()
        for provider in _keys(cfg):
            if not _keys(cfg).get(provider):
                print(f"{provider}: no key configured")
                continue
            models = list_models(provider, cfg)
            print(f"{provider}: {len(models)} candidate models")
            for m in models:
                p = probes.get(f"{provider}/{m}")
                state = "not probed" if p is None else ("tool calling OK" if p["tool_calling"] else f"rejected: {p['error']}")
                print(f"  {m:42} {state}{'' if p is None else f' ({p['seconds']} s)'}")
        return 0
    if argv[0] == "probe" and len(argv) == 3:
        print(json.dumps(asyncio.run(probe(argv[1], argv[2])), indent=1))
        return 0
    if argv[0] == "probe-all" and len(argv) == 2:
        for m in list_models(argv[1], cfg):
            result = asyncio.run(probe(argv[1], m))
            print(f"{m:42} {'OK ' if result['tool_calling'] else 'NO '} {result['seconds']:>5} s  {result['error'][:70]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

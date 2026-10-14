"""Deterministic stand-in for the AI model, used ONLY by the test suite.

It reads the case file built by the server and applies simple rules, so the streaming API, the guardrails
and the clients can be tested end to end without an AI key. make_provider refuses to build it unless
VIGIE_ALLOW_TEST_PROVIDER=1. It is not a detection engine and never ships.
"""
from __future__ import annotations

import json

from ..tools import ToolSpec
from . import ToolCall, Turn


class ScriptedConversation:
    def __init__(self, user: str):
        self.case = json.loads(user.split("DOSSIER_JSON:", 1)[1].strip())

    async def next(self) -> Turn:
        return Turn(calls=[ToolCall("call_verdict", "submit_verdict", self._verdict())])

    def _verdict(self) -> dict:
        case = self.case
        host = case["link"]["host"]
        identity = case.get("identity") or {}
        brand = identity.get("claimed_brand") or ""
        official = identity.get("official_domains_confirmed_by_two_sources") or []
        on_official = any(host == d or host.endswith("." + d) for d in official)
        lookalike = bool(case.get("address", {}).get("brand_name_outside_official_domain"))
        page = case.get("page") or {}
        asks = bool(page.get("asks_for"))
        ages = [d.get("age_days") for d in case.get("domains", []) if d.get("age_days") is not None]
        evidence = [f"Domain registered {ages[0]} days ago"] if ages else []
        if brand:
            evidence.append(f"Page claims to be {brand}")
        if official:
            evidence.append(f"Official site: {official[0]}")
        if lookalike or (brand and official and not on_official and asks):
            return {"verdict": "blocked", "threat_type": "impersonation", "impersonated_brand": brand,
                    "official_domain": official[0] if official else "",
                    "decisive_evidence": evidence or ["Brand name used outside its official domain"],
                    "explanation": f"This site pretends to be {brand}, but {brand}'s real site is "
                                   f"{official[0] if official else 'elsewhere'}. Do not enter any details here."}
        return {"verdict": "safe", "threat_type": "none", "impersonated_brand": "",
                "official_domain": official[0] if on_official else "",
                "decisive_evidence": evidence or ["No warning sign found"],
                "explanation": (f"This is {brand}'s official site." if brand and on_official
                                else "No sign of phishing was found on this link.")}

    def remind(self, text: str) -> None:
        pass

    def add_results(self, results: list[tuple[str, str, bool]]) -> None:
        pass


class ScriptedProvider:
    name = "scripted"
    model = "scripted-test-agent"
    builtin_search = False
    vision = False

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> ScriptedConversation:
        return ScriptedConversation(user)

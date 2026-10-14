"""Replay mode for the jury demo (section 12.3): if the AI provider or the network fails on the day, a real
investigation recorded beforehand is played back, clearly labelled as a replay and never passed off as live.

    python -m server.replay record ecobank-fake https://ecobank-tg-verif.com/login
    python -m server.replay list

Then open /replay/ecobank-fake on the server.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone

from .config import REPO, settings
from .db import Store
from .normalize import normalise
from .providers import ProviderChoice

REPLAYS = REPO / "data" / "replays"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def load(name: str) -> dict | None:
    if not NAME.match(name):
        return None
    path = REPLAYS / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def record(name: str, url: str) -> dict:
    from .agent import investigate
    if not NAME.match(name):
        raise ValueError("Use lowercase letters, digits and dashes for the name.")
    link = normalise(url)
    events: list[dict] = []
    started = time.monotonic()

    async def emit(event: str, data: dict) -> None:
        events.append({"t": round(time.monotonic() - started, 2), "event": event, "data": data})

    result = await investigate(link, settings(), Store(":memory:"), ProviderChoice(""), emit)
    result = {k: v for k, v in result.items() if k != "steps"}
    events.append({"t": round(time.monotonic() - started, 2), "event": "verdict", "data": result})
    replay = {"name": name, "url": link.url, "host": link.display_host,
              "recorded_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "events": events}
    REPLAYS.mkdir(parents=True, exist_ok=True)
    (REPLAYS / f"{name}.json").write_text(json.dumps(replay, ensure_ascii=False, indent=1), encoding="utf-8")
    return replay


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "record":
        replay = asyncio.run(record(argv[1], argv[2]))
        verdict = replay["events"][-1]["data"]
        print(f"Recorded {argv[1]}: {verdict['verdict']} in {replay['events'][-1]['t']} s. Play it at /replay/{argv[1]}")
        return 0
    if argv[:1] == ["list"]:
        for path in sorted(REPLAYS.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            print(f"{data['name']:24} {data['events'][-1]['data']['verdict']:8} {data['url']}  ({data['recorded_at']})")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

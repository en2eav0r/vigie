"""Run Vigie locally.

    python scripts/dev.py               uses the provider configured in .env (needs an AI key)
    python scripts/dev.py --test-agent  uses the scripted test agent (no AI key; for UI and pipeline tests only)
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO))

if "--test-agent" in sys.argv:
    os.environ["VIGIE_PROVIDER"] = "scripted"
    os.environ["VIGIE_ALLOW_TEST_PROVIDER"] = "1"
    os.environ.setdefault("VIGIE_DB", str(REPO / "data" / "dev-test.db"))
port = int(os.environ.get("PORT", "8740"))

import uvicorn  # noqa: E402

uvicorn.run("server.api:app", host="127.0.0.1", port=port)

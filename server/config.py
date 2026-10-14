"""Server settings, read from environment variables (and an optional .env file).

Secrets never live in the repository: copy .env.example to .env on the server.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]          # quoted: keep everything inside the quotes
        else:
            value = "" if value.startswith("#") else re.split(r"\s+#", value, maxsplit=1)[0].strip()
        os.environ.setdefault(key.strip(), value)


_load_dotenv(REPO / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # AI provider (section 5). "anthropic", "openai", "gemini", "deepseek", "openai_compat".
    provider: str = field(default_factory=lambda: _env("VIGIE_PROVIDER", "anthropic"))
    model: str = field(default_factory=lambda: _env("VIGIE_MODEL"))
    effort: str = field(default_factory=lambda: _env("VIGIE_EFFORT", "medium"))
    base_url: str = field(default_factory=lambda: _env("VIGIE_BASE_URL"))
    # Optional backup provider, used only when the first one does not answer (never a vote).
    backup_provider: str = field(default_factory=lambda: _env("VIGIE_BACKUP_PROVIDER"))
    backup_model: str = field(default_factory=lambda: _env("VIGIE_BACKUP_MODEL"))

    anthropic_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    gemini_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    deepseek_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    compat_key: str = field(default_factory=lambda: _env("VIGIE_COMPAT_API_KEY"))

    # Threat intelligence sources (section 7). Each is optional; missing keys skip the source.
    virustotal_key: str = field(default_factory=lambda: _env("VIRUSTOTAL_API_KEY"))
    safebrowsing_key: str = field(default_factory=lambda: _env("GOOGLE_SAFE_BROWSING_KEY"))
    urlhaus_key: str = field(default_factory=lambda: _env("URLHAUS_AUTH_KEY"))
    urlscan_key: str = field(default_factory=lambda: _env("URLSCAN_API_KEY"))
    abuseipdb_key: str = field(default_factory=lambda: _env("ABUSEIPDB_API_KEY"))
    brave_key: str = field(default_factory=lambda: _env("BRAVE_SEARCH_API_KEY"))

    # Limits (S04, S09, S10, N02).
    max_tool_calls: int = field(default_factory=lambda: _int("VIGIE_MAX_TOOL_CALLS", 6))
    max_agent_turns: int = field(default_factory=lambda: _int("VIGIE_MAX_AGENT_TURNS", 4))
    # Hard ceiling per investigation: above it the link stays closed with "Verification impossible".
    max_cost_per_investigation: float = field(default_factory=lambda: _float("VIGIE_MAX_COST_USD", 0.01))
    tool_timeout: float = field(default_factory=lambda: _float("VIGIE_TOOL_TIMEOUT", 8.0))
    investigation_timeout: float = field(default_factory=lambda: _float("VIGIE_INVESTIGATION_TIMEOUT", 45.0))
    daily_quota_per_token: int = field(default_factory=lambda: _int("VIGIE_DAILY_QUOTA", 20))
    daily_spend_cap_usd: float = field(default_factory=lambda: _float("VIGIE_DAILY_SPEND_CAP_USD", 5.0))
    verdict_ttl_hours: float = field(default_factory=lambda: _float("VIGIE_VERDICT_TTL_HOURS", 24.0))

    db_path: str = field(default_factory=lambda: _env("VIGIE_DB", str(REPO / "data" / "vigie.db")))
    # Only for the test suite: enables the scripted provider. Never set on a real server.
    allow_test_provider: bool = field(default_factory=lambda: _env("VIGIE_ALLOW_TEST_PROVIDER") == "1")
    # Origins allowed to call the API from a browser (the desktop app calls it from Python).
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(o for o in _env("VIGIE_CORS_ORIGINS").split(",") if o)
    )


def settings() -> Settings:
    return Settings()

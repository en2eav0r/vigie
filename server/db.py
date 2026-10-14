"""SQLite storage: verdict memory (S03), client tokens and quotas (S09, S10), review queue (C05).

Stored data follows N06: domain, normalised URL without parameters, verdict, date.
Never the user's identity, IP or the app the link came from.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    url_key     TEXT PRIMARY KEY,
    public_url  TEXT NOT NULL,
    domain      TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS verdicts_domain ON verdicts(domain);
CREATE TABLE IF NOT EXISTS tokens (
    token       TEXT PRIMARY KEY,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    token       TEXT NOT NULL,
    day         TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (token, day)
);
CREATE TABLE IF NOT EXISTS spend (
    day         TEXT PRIMARY KEY,
    usd         REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    public_url  TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    public_url  TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    steps       TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def _q(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # Verdict memory -------------------------------------------------------
    def get_verdict(self, url_key: str, ttl_hours: float) -> dict | None:
        rows = self._q("SELECT payload, created_at FROM verdicts WHERE url_key=?", (url_key,))
        if not rows:
            return None
        payload, created = rows[0]
        if time.time() - created > ttl_hours * 3600:
            self._q("DELETE FROM verdicts WHERE url_key=?", (url_key,))
            return None
        data = json.loads(payload)
        data["cached_at"] = created
        return data

    def put_verdict(self, url_key: str, public_url: str, domain: str, verdict: str, payload: dict) -> None:
        self._q(
            "INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?)",
            (url_key, public_url, domain, verdict, json.dumps(payload), time.time()),
        )

    def domain_history(self, domain: str, limit: int = 5) -> list[dict]:
        rows = self._q(
            "SELECT public_url, verdict, created_at FROM verdicts WHERE domain=? ORDER BY created_at DESC LIMIT ?",
            (domain, limit),
        )
        return [
            {"url": u, "verdict": v, "date": datetime.fromtimestamp(c, timezone.utc).isoformat(timespec="minutes")}
            for u, v, c in rows
        ]

    # Tokens and quotas ----------------------------------------------------
    def new_token(self) -> str:
        token = "vg_" + secrets.token_urlsafe(24)
        self._q("INSERT INTO tokens VALUES (?,?)", (token, time.time()))
        return token

    def token_exists(self, token: str) -> bool:
        return bool(token) and bool(self._q("SELECT 1 FROM tokens WHERE token=?", (token,)))

    def usage_today(self, token: str) -> int:
        rows = self._q("SELECT count FROM usage WHERE token=? AND day=?", (token, today()))
        return rows[0][0] if rows else 0

    def add_usage(self, token: str) -> None:
        self._q(
            "INSERT INTO usage(token, day, count) VALUES (?,?,1) "
            "ON CONFLICT(token, day) DO UPDATE SET count=count+1",
            (token, today()),
        )

    def spend_today(self) -> float:
        rows = self._q("SELECT usd FROM spend WHERE day=?", (today(),))
        return rows[0][0] if rows else 0.0

    def add_spend(self, usd: float) -> None:
        self._q(
            "INSERT INTO spend(day, usd) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET usd=usd+?",
            (today(), usd, usd),
        )

    # Review queue and logs --------------------------------------------------
    def add_report(self, public_url: str, verdict: str, note: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO reports(public_url, verdict, note, created_at) VALUES (?,?,?,?)",
                (public_url, verdict, note[:500], time.time()),
            )
            return int(cur.lastrowid)

    def log_investigation(self, public_url: str, verdict: str, steps: list[dict]) -> None:
        self._q(
            "INSERT INTO investigation_log(public_url, verdict, steps, created_at) VALUES (?,?,?,?)",
            (public_url, verdict, json.dumps(steps), time.time()),
        )
        # N07: investigation logs are deleted after 30 days.
        self._q("DELETE FROM investigation_log WHERE created_at < ?", (time.time() - 30 * 86400,))

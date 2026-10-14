"""Refuse a commit that contains an API key (installed as the git pre-commit hook).

Checks the staged files for every value set in .env and for the usual key formats.
    python scripts/check_secrets.py            check the staged files (what the hook runs)
    python scripts/check_secrets.py --all      check every tracked and untracked file
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATTERNS = {
    "OpenAI key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "Google AI Studio key": re.compile(r"AQ\.[A-Za-z0-9_-]{30,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
SKIP = {".env.example"}


def env_values() -> list[str]:
    values = []
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, raw = line.split("=", 1)
                if not re.search(r"KEY|TOKEN|SECRET|PASSWORD", name):
                    continue  # model names and limits are not secrets
                value = raw.split(" #")[0].strip().strip('"').strip("'")
                if len(value) >= 16:
                    values.append(value)
    return values


def files(all_files: bool) -> list[Path]:
    if all_files:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO,
                             capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], cwd=REPO,
                             capture_output=True, text=True).stdout
    return [REPO / f for f in out.splitlines() if f]


def main() -> int:
    secrets = env_values()
    problems = []
    for path in files("--all" in sys.argv):
        if path.name in SKIP or path.name == ".env" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary file
        rel = path.relative_to(REPO)
        if any(value in text for value in secrets):
            problems.append(f"{rel}: contains a value from .env")
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{rel}: looks like it contains a {name}")
    if problems:
        print("Commit refused, secrets found:\n  " + "\n  ".join(problems))
        print("Move the secret to .env (never committed) and try again.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

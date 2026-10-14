"""Vigie Desktop tests (Windows only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows client")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))


def test_link_is_never_opened_without_a_safe_verdict(monkeypatch):
    from vigie_desktop import app, browsers
    opened = []
    monkeypatch.setattr(browsers, "open_in", lambda b, url: opened.append(url))
    api = app.Api()
    result = api.open_link("https://ecobank-tg-verif.com/login", None, False)
    assert result["ok"] is False and not opened


def test_safe_link_opens_once_in_the_chosen_browser(monkeypatch, tmp_path):
    from vigie_desktop import app, browsers, settings
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fake = browsers.Browser(id="Test", name="Test browser", exe=sys.executable)
    monkeypatch.setattr(browsers, "installed", lambda: [fake])
    opened = []
    monkeypatch.setattr(browsers, "open_in", lambda b, url: opened.append((b.name, url)))
    api = app.Api()
    api._cleared.add("https://ecobank.com/")
    assert api.open_link("https://ecobank.com/", "Test", False)["ok"]
    assert opened == [("Test browser", "https://ecobank.com/")]
    assert api.open_link("https://ecobank.com/", "Test", False)["ok"] is False  # cleared once, opened once


def test_server_address_must_be_https_except_local():
    from vigie_desktop.settings import valid_server
    assert valid_server("https://vigie.example.org/") == "https://vigie.example.org"
    assert valid_server("http://127.0.0.1:8740") == "http://127.0.0.1:8740"
    assert valid_server("http://vigie.example.org") is None


def test_local_copy_of_past_verdicts(monkeypatch, tmp_path):
    from vigie_desktop import settings
    monkeypatch.setattr(settings, "VERDICTS_FILE", tmp_path / "verdicts.json")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings.remember_verdict("https://ecobank.com/?utm_source=x", {"verdict": "safe", "url": "https://ecobank.com/"})
    assert settings.past_verdict("https://ecobank.com/")["verdict"] == "safe"
    settings.remember_verdict("https://x.org", {"verdict": "unknown"})
    assert settings.past_verdict("https://x.org") is None      # unknown is never remembered


def test_installed_browsers_are_found():
    from vigie_desktop import browsers
    found = browsers.installed()
    assert all(b.exe.lower().endswith(".exe") for b in found)
    assert not any(b.id.lower() == "vigie" for b in found)

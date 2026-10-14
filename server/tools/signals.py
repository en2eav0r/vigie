"""Computed signals on the URL itself; no network access."""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

from ..normalize import registered_domain
from .urlscan import BRANDS

HIGH_RISK_TLDS = {"zip", "mov", "top", "xyz", "icu", "click", "link", "cfd", "sbs", "rest", "buzz", "monster",
                  "gq", "tk", "ml", "cf", "ga", "work", "support", "cyou", "quest", "bond", "lol", "mom"}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "rb.gy", "ow.ly", "shorturl.at", "tiny.cc",
              "s.id", "t.ly", "goo.gl", "bitly.com", "rebrand.ly", "shorturl.asia"}
LURE_WORDS = re.compile(r"(login|log-in|signin|verify|verif|secure|account|update|confirm|bonus|gift|claim|"
                        r"reward|win|promo|unlock|suspend|wallet|kyc|"
                        # French: the language of most scams aimed at Togo
                        r"connexion|compte|securite|validation|valider|cadeau|gagnant|gain|recompense|"
                        r"remboursement|debloquer|bloque|activation|momo|flooz|tmoney|t-money)", re.I)
LOOKALIKES = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
# Platforms where anyone can publish a page under the platform's own (old, trusted) domain.
SHARED_HOSTING = ("sites.google.com", "github.io", "web.app", "firebaseapp.com", "pages.dev", "netlify.app",
                  "vercel.app", "weebly.com", "wixsite.com", "blogspot.com", "000webhostapp.com", "ngrok-free.app",
                  "craftum.io", "webflow.io", "glitch.me", "replit.app", "repl.co", "framer.app", "framer.website",
                  "wordpress.com", "godaddysites.com", "square.site", "mystrikingly.com", "strikingly.com", "carrd.co",
                  "notion.site", "jimdosite.com", "webnode.page", "yolasite.com", "site123.me", "onrender.com",
                  "herokuapp.com", "azurewebsites.net", "workers.dev", "surge.sh", "forms.gle", "typedream.app",
                  "ipfs.io", "dweb.link", "r2.dev", "s3.amazonaws.com", "storage.googleapis.com", "translate.goog")


def _scripts(label: str) -> set[str]:
    scripts = set()
    for ch in label:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            scripts.add(name.split(" ")[0])
    return scripts


def official_domains_for(text: str) -> list[tuple[str, list[str]]]:
    hits = []
    squashed = text.lower().translate(LOOKALIKES).replace("rn", "m").replace("vv", "w")
    for brand in BRANDS:
        for name in [brand["name"], *brand.get("aliases", [])]:
            token = re.sub(r"[^a-z0-9]", "", name.lower())
            if len(token) >= 3 and token in re.sub(r"[^a-z0-9]", "", squashed):
                hits.append((brand["name"], brand["domains"]))
                break
    return hits


async def run(ctx, args: dict) -> dict:
    url = args.get("url") or ctx.link.url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    base = registered_domain(host)
    tld = host.rsplit(".", 1)[-1]
    try:
        unicode_host = host.encode("ascii").decode("idna")
    except UnicodeError:
        unicode_host = host
    is_ip = True
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        is_ip = False
    brand_hits = []
    for brand, domains in official_domains_for(host):
        if not any(base == d or host.endswith("." + d) for d in domains):
            brand_hits.append({"brand": brand, "official_domains": domains})
    subdomain = host[: -len(base)].rstrip(".") if host != base else ""
    return {
        "host": host,
        "unicode_host": unicode_host,
        "punycode": "xn--" in host,
        "mixed_scripts": len(_scripts(unicode_host.replace(".", ""))) > 1,
        "raw_ip_host": is_ip,
        "high_risk_tld": tld in HIGH_RISK_TLDS,
        "tld": tld,
        "url_shortener": base in SHORTENERS or host in SHORTENERS,
        "shared_hosting": any(host.endswith(s) for s in SHARED_HOSTING),
        "brand_name_outside_official_domain": brand_hits,
        "brand_in_subdomain": bool(subdomain and official_domains_for(subdomain)),
        "lure_words": sorted(set(m.lower() for m in LURE_WORDS.findall(host + parts.path)))[:6],
        "hyphens_in_domain": base.count("-"),
        "at_sign_in_url": "@" in parts.netloc,
        "plain_http": parts.scheme == "http",
        "url_length": len(url),
    }

"""URL normalisation (S02) and sensitive-link detection (N09)."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid", "igshid",
    "yclid", "_hsenc", "_hsmi", "ref_src", "si", "s_cid", "mkt_tok",
}
TRACKING_PREFIXES = ("utm_",)

# Parameters that usually carry a secret: these links are never sent to VirusTotal or urlscan.io.
SENSITIVE_PARAMS = re.compile(
    r"^(token|access_token|id_token|auth|code|key|sig|signature|otp|reset|magic|session|sid|"
    r"password|pwd|ticket|hash|nonce|state|confirm|verify|verification)$",
    re.I,
)
SENSITIVE_PATH = re.compile(r"(reset|magic|verify|confirm|activate|invite|unsubscribe|login/link)", re.I)


class InvalidLink(ValueError):
    """The text is not a link Vigie can investigate."""


@dataclass(frozen=True)
class Link:
    url: str            # full URL to visit, scheme and host normalised
    key: str            # memory key: no tracking parameters, no fragment
    public: str         # what is stored and published: scheme, host and path only (N06)
    host: str           # punycode (ASCII) host
    display_host: str   # Unicode host, for the interface
    registered_domain: str
    sensitive: bool


_MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "co.za", "co.ke", "co.tz", "co.ug",
    "com.ng", "org.ng", "gov.ng", "com.gh", "gov.gh", "co.ci", "com.br", "co.jp", "co.in",
    "com.tg", "gouv.tg", "gov.tg", "co.tg", "gouv.bj", "gouv.ci", "gouv.sn", "gouv.fr",
}


def registered_domain(host: str) -> str:
    """Best-effort registrable domain (eTLD+1) without a public-suffix download."""
    if _is_ip(host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    # Country registries usually sell names under com.xx, co.xx, org.xx... (roblox.com.ml is the domain,
    # com.ml is not).
    if len(parts[-1]) == 2 and parts[-2] in _GENERIC_SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


_GENERIC_SECOND_LEVEL = {"com", "co", "net", "org", "gov", "gouv", "edu", "ac", "or", "ne", "go", "mil", "sch",
                         "info", "biz", "nom", "ltd", "plc"}


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def normalise(raw: str) -> Link:
    text = (raw or "").strip()
    if not text:
        raise InvalidLink("Paste a link to check.")
    if len(text) > 4096:
        raise InvalidLink("This link is too long to check.")
    if re.search(r"\s", text):
        raise InvalidLink("A link cannot contain spaces.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        if text.lower().startswith(("javascript:", "data:", "file:", "vbscript:")):
            raise InvalidLink("Vigie only checks web links (http or https).")
        text = "https://" + text
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidLink("Vigie only checks web links (http or https).")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise InvalidLink("This does not look like a web address.")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower() if not _is_ip(host) else host
    except UnicodeError:
        ascii_host = host.lower()
    if not _is_ip(ascii_host) and ("." not in ascii_host or not re.match(r"^[a-z0-9.-]+$", ascii_host)):
        raise InvalidLink("This does not look like a web address.")
    try:
        display_host = ascii_host.encode("ascii").decode("idna") if "xn--" in ascii_host else ascii_host
    except UnicodeError:
        display_host = ascii_host

    port = parts.port
    netloc = ascii_host if not port or (scheme, port) in (("http", 80), ("https", 443)) else f"{ascii_host}:{port}"
    path = quote(unquote(parts.path or "/"), safe="/%:@!$&'()*+,;=-._~")
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in query_items
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)]
    full = urlunsplit((scheme, netloc, path, parts.query, ""))
    key = urlunsplit((scheme, netloc, path, urlencode(sorted(kept)), ""))
    public = urlunsplit((scheme, netloc, path, "", ""))
    sensitive = any(SENSITIVE_PARAMS.match(k) for k, _ in query_items) or bool(
        SENSITIVE_PATH.search(path) and query_items
    )
    return Link(full, key, public, ascii_host, display_host, registered_domain(ascii_host), sensitive)

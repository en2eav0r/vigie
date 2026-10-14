"""Build static/img/icons.svg from the SVG assets exported from Figma (paths unchanged, colour -> currentColor)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "server" / "web" / "static"
NAMES = ["arrow", "link", "scan", "eye", "stop", "bank", "alert", "search", "check", "clock", "file", "browser",
         "back", "menu", "win-min", "win-max", "win-close", "desktop", "phone"]

# The Figma "Icon / link" vector (8:76) leaves its 24 px frame (x down to -1.24), so its left loop is cut off.
# It is redrawn here in the same outline style: 24 px frame, 1.7 stroke, round caps and joins.
FIXED = {
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
}

out = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
for name in NAMES:
    s = (STATIC / "icons" / f"{name}.svg").read_text()
    vb = re.search(r'viewBox="([^"]+)"', s).group(1)
    body = re.search(r"<svg[^>]*>(.*)</svg>", s, re.S).group(1)
    body = re.sub(r"<defs>.*?</defs>", "", body, flags=re.S)
    body = re.sub(r'\s(id|clip-path)="[^"]*"', "", body)
    body = re.sub(r'stroke="(#[0-9A-Fa-f]{6}|white)"', 'stroke="currentColor"', body)
    body = re.sub(r'fill="(#[0-9A-Fa-f]{6}|white)"', 'fill="currentColor"', body)
    body = re.sub(r"\s+", " ", body).strip()
    body = FIXED.get(name, body)
    out.append(f'<symbol id="i-{name}" viewBox="{vb}" fill="none">{body}</symbol>')
# Logo 03 (Figma component "Logo / Symbol 01", vector 2:34); also used for the decorative V.
logo = (STATIC / "icons" / "logo-symbol.svg").read_text()
path = re.search(r'<path[^>]*d="([^"]+)"', logo).group(1)
out.append(f'<symbol id="i-logo" viewBox="0 0 32 32"><path d="{path}" fill="currentColor"/></symbol>')
out.append("</svg>")
(STATIC / "img" / "icons.svg").write_text("\n".join(out))
(STATIC / "img" / "favicon.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="{path}" fill="#123B70"/></svg>')
print("sprite:", len(NAMES) + 1, "symbols")

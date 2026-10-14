"""Draw the Windows icons from the logo 03 vector (Figma component 2:32, path in icons/logo-symbol.svg).

    python scripts/make_icon.py          writes desktop/assets/vigie-white.ico and vigie-blue.ico
"""
from pathlib import Path
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "desktop" / "assets"
# The logo path uses only straight segments: two polygons, in the 32 x 32 Figma frame.
LEFT = [(1.185, 8), (29.185, 1), (26.185, 7), (10.185, 11), (15.185, 17), (15.185, 31), (12.185, 31)]
RIGHT = [(19.185, 10), (32.185, 6), (21.185, 31), (17.185, 31), (17.185, 17)]
BLUE = (0x12, 0x3B, 0x70, 255)
WHITE = (255, 255, 255, 255)
BORDER = (0xC4, 0xCE, 0xDB, 255)   # the design's border token, keeps the white tile visible on white
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def render(size: int, background, logo) -> Image.Image:
    scale = 8  # supersample, then downsample for clean edges
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = big * 0.22
    if background == WHITE:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius, fill=WHITE, outline=BORDER, width=max(scale, big // 64))
    else:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius, fill=background)
    # The logo spans 31 x 30 units; centre it in the tile with a margin that grows on small sizes.
    margin = big * (0.22 if size >= 32 else 0.16)
    unit = (big - 2 * margin) / 31.0
    ox, oy = margin - 1.185 * unit, margin - 1 * unit + (big - 2 * margin - 30 * unit) / 2
    for poly in (LEFT, RIGHT):
        draw.polygon([(ox + x * unit, oy + y * unit) for x, y in poly], fill=logo)
    return img.resize((size, size), Image.LANCZOS)


for name, background, logo in (("white", WHITE, BLUE), ("blue", BLUE, WHITE)):
    images = [render(s, background, logo) for s in SIZES]
    images[-1].save(ASSETS / f"vigie-{name}.ico", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    images[-1].save(ASSETS / f"vigie-{name}-256.png")

# Preview: both icons at 256, 48 and 24 px, on a light and a dark taskbar.
preview = Image.new("RGB", (760, 420), (243, 246, 251))
dark = Image.new("RGB", (760, 120), (32, 32, 32))
preview.paste(dark, (0, 300))
for i, name in enumerate(("white", "blue")):
    big = Image.open(ASSETS / f"vigie-{name}-256.png")
    preview.paste(big, (40 + i * 400, 20), big)
    for j, s in enumerate((48, 24)):
        small = render(s, WHITE if name == "white" else BLUE, BLUE if name == "white" else WHITE)
        preview.paste(small, (40 + i * 400 + j * 70, 336), small)
preview.save(ASSETS / "icon-preview.png")
print("icons written to", ASSETS)

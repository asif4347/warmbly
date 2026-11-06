#!/usr/bin/env python3
"""Draw the placeholder Datamart Warmup icons into datamart/assets/.

A white "D" on a teal tile. Swap these files for a designed logo whenever one
exists; rebrand.py copies whatever is in datamart/assets/.
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
TEAL = (15, 118, 110, 255)


def tile(size: int) -> Image.Image:
    s = 4 * size  # draw large, then downsample for smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s // 5, fill=TEAL)
    # The D: a bar on the left plus a half disc, with a matching hole.
    x0, y0, x1, y1 = int(s * 0.27), int(s * 0.2), int(s * 0.78), int(s * 0.8)
    h = y1 - y0
    d.rectangle([x0, y0, x1 - h // 2, y1], fill="white")
    d.pieslice([x1 - h, y0, x1, y1], -90, 90, fill="white")
    t = int(s * 0.12)
    hx0, hy0, hy1 = x0 + t, y0 + t, y1 - t
    hh = hy1 - hy0
    hx1 = x1 - t
    d.rectangle([hx0, hy0, hx1 - hh // 2, hy1], fill=TEAL)
    d.pieslice([hx1 - hh, hy0, hx1, hy1], -90, 90, fill=TEAL)
    return im.resize((size, size), Image.LANCZOS)


def save(app: str, name: str, size: int):
    p = OUT / app / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tile(size).save(p)


for n in (16, 32, 48, 96):
    save("web", f"favicon-{n}x{n}.png", n)
save("web", "apple-touch-icon.png", 180)
save("web", "web-app-manifest-192x192.png", 192)
save("web", "web-app-manifest-512x512.png", 512)
tile(64).save(OUT / "web" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

for n in (16, 32):
    save("admin", f"favicon-{n}x{n}.png", n)
save("admin", "apple-touch-icon.png", 180)
save("admin", "icon-192.png", 192)
save("admin", "icon-512.png", 512)
tile(64).save(OUT / "admin" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
(OUT / "admin" / "admin-icon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" rx="20" fill="#0f766e"/>'
    '<path fill="#fff" fill-rule="evenodd" d="M27 20H48C66 20 78 33 78 50C78 67 66 80 48 80H27Z'
    'M39 32V68H48C59 68 66 60 66 50C66 40 59 32 48 32Z"/></svg>\n'
)
print("icons written to", OUT)

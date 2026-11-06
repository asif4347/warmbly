#!/usr/bin/env python3
"""Draw the Datamart Warmup icons into datamart/assets/ from the Datamart logo.

Favicons are the bare mark on a transparent background. App and home-screen
icons put it on white with room around it, as the Datamart brand guide asks.
rebrand.py copies whatever is in datamart/assets/.
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "assets"
MARK = Image.open(HERE / "brand-src" / "datamart-logo-512.png").convert("RGBA")
MARK = MARK.crop(MARK.getbbox())


def fit(size: int, pad: float, bg=None) -> Image.Image:
    im = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    inner = int(size * (1 - 2 * pad))
    m = MARK.copy()
    m.thumbnail((inner, inner), Image.LANCZOS)
    im.alpha_composite(m, ((size - m.width) // 2, (size - m.height) // 2))
    return im


def favicon(app: str, n: int):
    fit(n, 0.04).save(OUT / app / f"favicon-{n}x{n}.png")


def tile(app: str, name: str, n: int):
    fit(n, 0.18, (255, 255, 255, 255)).convert("RGB").save(OUT / app / name)


for app in ("web", "admin"):
    (OUT / app).mkdir(parents=True, exist_ok=True)
    fit(64, 0.04).save(OUT / app / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    tile(app, "apple-touch-icon.png", 180)

for n in (16, 32, 48, 96):
    favicon("web", n)
tile("web", "web-app-manifest-192x192.png", 192)
tile("web", "web-app-manifest-512x512.png", 512)

for n in (16, 32):
    favicon("admin", n)
tile("admin", "icon-192.png", 192)
tile("admin", "icon-512.png", 512)
(OUT / "admin" / "admin-icon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 82 82">'
    '<path fill="#d61700" d="M41.008,0.938c9.558,0,18.338,3.321,25.255,8.87L29.338,2.652C33.032,1.539,36.949,0.938,41.008,0.938z"/>'
    '<path fill="#d61700" d="M78.159,25.45c0.784,1.833,1.438,3.736,1.947,5.696L36.787,80.062l-21-66.474L78.159,25.45z"/>'
    '<path fill="#b01400" d="M80.388,50.366C77.372,63.57,67.886,74.306,55.443,79.069L80.388,50.366z"/>'
    '<path fill="#d61700" d="M21.163,76.523C8.896,69.589,0.612,56.431,0.612,41.333c0-6.387,1.484-12.427,4.124-17.796L21.163,76.523z"/>'
    "</svg>\n"
)
print("icons written to", OUT)

#!/usr/bin/env python3
"""Put the Datamart Warmup logo and colours on the product tour's screenshots.

The tour shows real screenshots of the dashboard with the Warmbly logo and name
in the top-left corner. This paints that corner over with the page colour and
draws our mark and name in its place, turns the sky-blue accents Datamart charcoal,
and swaps the Slack app avatar for our icon. Results go to datamart/overrides/, which rebrand.py copies over the
checkout, and their upstream hashes go to datamart/overrides.json so a Warmbly
update that changes a screenshot is caught instead of silently overwritten.

Run it on a Mac (it uses Helvetica Neue) whenever rebrand.py --check reports a
changed screenshot, then commit the results.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOTS = "web/src/components/app/tour/shots"
OUT = ROOT / "datamart" / "overrides"
INK = (17, 24, 39)
NAME = json.loads((ROOT / "datamart" / "brand.json").read_text())["name"]
FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 19, index=1)

# The corner every full-page screenshot shares: logo mark at ~(28, 18), name to
# its right, the workspace switcher from x=288.
BOX = (12, 6, 270, 56)


MARK = Image.open(ROOT / "datamart" / "brand-src" / "datamart-logo-512.png").convert("RGBA")
MARK = MARK.crop(MARK.getbbox())


def draw_mark(patch: Image.Image, x: int, y: int, h: int, dim: bool):
    """The Datamart mark, h pixels tall, washed out on a dimmed page."""
    m = MARK.copy()
    m.thumbnail((h, h), Image.LANCZOS)
    if dim:
        m.putalpha(m.getchannel("A").point(lambda a: int(a * 0.55)))
    patch.paste(m, (x, y + (h - m.height) // 2), m)


def recolour(im: Image.Image) -> Image.Image:
    """Turn Warmbly's sky-blue accents Datamart charcoal, as the app's palette
    does: pale washes stay pale, strong blues become dark grey."""
    hsv = np.array(im.convert("HSV"), dtype=np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sky = (h >= 130) & (h <= 155) & (s >= 60)  # 185 to 218 degrees, not greys
    v[sky] = v[sky] * (1 - 0.7 * s[sky] / 255)
    s[sky] = 0
    return Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")


def stamp(src: Path, dest: Path):
    im = recolour(Image.open(src).convert("RGB"))
    s = 3  # draw at 3x and downsample for smooth edges
    region = im.crop(BOX)
    bg = im.getpixel((BOX[2] - 4, 30))
    patch = Image.new("RGB", ((BOX[2] - BOX[0]) * s, (BOX[3] - BOX[1]) * s), bg)
    d = ImageDraw.Draw(patch)
    # The overlay screenshot (a dialog over a dimmed page) uses the dimmed ink.
    dim = sum(bg) < 3 * 215
    ink = tuple(int(c * 0.55 + b * 0.45) for c, b in zip(INK, bg)) if dim else INK
    draw_mark(patch, (26 - BOX[0]) * s, (15 - BOX[1]) * s, 26 * s, dim)
    big = ImageFont.truetype(FONT.path, FONT.size * s, index=1)
    d.text(((64 - BOX[0]) * s, (31 - BOX[1]) * s), NAME, font=big, fill=ink, anchor="lm")
    patch = patch.resize(region.size, Image.LANCZOS)
    if dim:
        patch = patch.filter(ImageFilter.GaussianBlur(1.6))
    im.paste(patch, BOX[:2])
    # The sample workspace's plan badge ("GROW") in the top bar. Nothing here
    # has plans, so it goes. Every full-page shot has it in the same place.
    ImageDraw.Draw(im).rectangle([1048, 12, 1138, 50], fill=im.getpixel((1044, 31)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=90)


def avatar(dest: Path):
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    m = MARK.copy()
    m.thumbnail((160, 160), Image.LANCZOS)
    im.paste(m, ((256 - m.width) // 2, (256 - m.height) // 2), m)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=90)


def recolour_only(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    recolour(Image.open(src).convert("RGB")).save(dest, "WEBP", quality=90)


def main():
    hashes = {}
    for src in sorted((ROOT / SHOTS).glob("*.webp")):
        rel = f"{SHOTS}/{src.name}"
        hashes[rel] = hashlib.sha256(src.read_bytes()).hexdigest()
        if src.name == "warmbly-avatar.webp":
            avatar(OUT / rel)
        elif Image.open(src).size == (1600, 1000):
            stamp(src, OUT / rel)
        else:
            recolour_only(src, OUT / rel)  # a cropped detail with no logo in it
    (ROOT / "datamart" / "overrides.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"stamped {len(hashes)} files into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Put the Datamart Warmup logo on the product tour's screenshots.

The tour shows real screenshots of the dashboard with the Warmbly logo and name
in the top-left corner. This paints that corner over with the page colour and
draws our mark and name in its place, and swaps the Slack app avatar for our
icon. Results go to datamart/overrides/, which rebrand.py copies over the
checkout, and their upstream hashes go to datamart/overrides.json so a Warmbly
update that changes a screenshot is caught instead of silently overwritten.

Run it on a Mac (it uses Helvetica Neue) whenever rebrand.py --check reports a
changed screenshot, then commit the results.
"""

import hashlib
import json
from pathlib import Path

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


def draw_mark(d: ImageDraw.ImageDraw, x: int, y: int, h: int, fg, bg):
    """The D: a bar plus a half disc, with a matching hole."""
    w = h
    d.rectangle([x, y, x + w - h // 2, y + h], fill=fg)
    d.pieslice([x + w - h, y, x + w, y + h], -90, 90, fill=fg)
    t = max(3, h // 5)
    hh = h - 2 * t
    d.rectangle([x + t, y + t, x + w - t - hh // 2, y + h - t], fill=bg)
    d.pieslice([x + w - t - hh, y + t, x + w - t, y + h - t], -90, 90, fill=bg)


def stamp(src: Path, dest: Path):
    im = Image.open(src).convert("RGB")
    s = 3  # draw at 3x and downsample for smooth edges
    region = im.crop(BOX)
    bg = im.getpixel((BOX[2] - 4, 30))
    patch = Image.new("RGB", ((BOX[2] - BOX[0]) * s, (BOX[3] - BOX[1]) * s), bg)
    d = ImageDraw.Draw(patch)
    # The overlay screenshot (a dialog over a dimmed page) uses the dimmed ink.
    dim = sum(bg) < 3 * 215
    ink = tuple(int(c * 0.55 + b * 0.45) for c, b in zip(INK, bg)) if dim else INK
    draw_mark(d, (28 - BOX[0]) * s, (16 - BOX[1]) * s, 24 * s, ink, bg)
    big = ImageFont.truetype(FONT.path, FONT.size * s, index=1)
    d.text(((64 - BOX[0]) * s, (31 - BOX[1]) * s), NAME, font=big, fill=ink, anchor="lm")
    patch = patch.resize(region.size, Image.LANCZOS)
    if dim:
        patch = patch.filter(ImageFilter.GaussianBlur(1.6))
    im.paste(patch, BOX[:2])
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=90)


def avatar(dest: Path):
    s = 1024
    im = Image.new("RGB", (s, s), (15, 118, 110))
    d = ImageDraw.Draw(im)
    draw_mark(d, int(s * 0.27), int(s * 0.21), int(s * 0.58), (255, 255, 255), (15, 118, 110))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.resize((256, 256), Image.LANCZOS).save(dest, "WEBP", quality=90)


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
            del hashes[rel]  # no logo in it (a cropped detail), left as it is
    (ROOT / "datamart" / "overrides.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"stamped {len(hashes)} files into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

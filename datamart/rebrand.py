#!/usr/bin/env python3
"""Rebrand the web and admin apps as Datamart Warmup, at build time.

The datamart branch never edits upstream files. It only adds files under
datamart/ and .github/workflows/datamart-*. This script applies the brand to a
checkout right before the images are built, so merging Warmbly's updates never
conflicts. If an update moves something a patch relies on, the script stops
with a clear error instead of shipping a half-branded build.

    python3 datamart/rebrand.py          apply to this checkout
    python3 datamart/rebrand.py --check  report what would change, write nothing

What it does:
  1. Replaces the word "Warmbly" in user-visible text with the brand name.
     "Warmbly Cloud" is left alone: it names their hosted service, whose
     screens stay hidden on a server that is not linked to it.
  2. Applies the small code patches in PATCHES (logo, cloud banner, tour plans)
     and copies datamart/overrides/ over the checkout (tour screenshots).
  3. Copies datamart/assets/<app>/ over <app>/public/ (favicons, icons).
  4. Rewrites the two PWA manifests.

Lowercase "warmbly" (import paths, storage keys, routes) is never touched.
"""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND = json.loads((ROOT / "datamart" / "brand.json").read_text())
NAME = BRAND["name"]

APPS = ["web", "admin"]
TEXT_SUFFIXES = {".ts", ".tsx", ".html"}
WORD = re.compile(r"\bWarmbly\b(?! Cloud)")

# Lines where "Warmbly" is a real value the backend sends or expects, not a
# brand mention: the webhook signature header, and the Gmail folder warmup mail
# goes into, which the backend still names "Warmbly".
KEEP_LINE = re.compile(r'-Warmbly-|placeholder="Warmbly"|for "Warmbly"|default, "Warmbly"')

# The Datamart mark, its four shapes as one path, scaled into the 746x764 box
# upstream's Logo components draw in. Datamart red in both themes: an inline
# style, so the dark theme's grey logo gradient does not repaint it.
DM_D = (
    "M41.008,0.938c9.558,0,18.338,3.321,25.255,8.87L29.338,2.652C33.032,1.539,36.949,0.938,41.008,0.938z"
    "M78.159,25.45c0.784,1.833,1.438,3.736,1.947,5.696L36.787,80.062l-21-66.474L78.159,25.45z"
    "M80.388,50.366C77.372,63.57,67.886,74.306,55.443,79.069L80.388,50.366z"
    "M21.163,76.523C8.896,69.589,0.612,56.431,0.612,41.333c0-6.387,1.484-12.427,4.124-17.796L21.163,76.523z"
)
DM_TRANSFORM = "translate(28 37) scale(8.4)"
LOGO_PATH = f'<path transform="{DM_TRANSFORM}" d="{DM_D}" style={{{{ fill: "#d61700" }}}} />'

# (file, exact upstream text, replacement). Each anchor must appear exactly once.
PATCHES = [
    (
        "web/src/components/svg.tsx",
        '<path d="M222.805 644.772L186.274 108.881L704.5 451.158L484.5 451.158L245.5 196.158L444 463.5L222.805 644.772Z" fill="currentColor" />',
        LOGO_PATH,
    ),
    (
        "admin/src/components/Logo.tsx",
        '                d="M222.805 644.772L186.274 108.881L704.5 451.158L484.5 451.158L245.5 196.158L444 463.5L222.805 644.772Z"',
        f'                transform="{DM_TRANSFORM}"\n                d="{DM_D}"\n                style={{{{ fill: "#d61700" }}}}',
    ),
    (
        # On an unlinked server the banner tells members local warmup "is not
        # effective" and sends them to Warmbly Cloud. In this network warmup is
        # local by design, so the banner never shows.
        "web/src/components/app/emails/CloudPoolBanner.tsx",
        "    if (!pool.manageable || pool.loading) return null;",
        "    if (true || !pool.manageable || pool.loading) return null; // datamart: no Warmbly Cloud upsell",
    ),
    (
        # The tour ends on Warmbly's hosted plans, which are not ours to sell.
        "web/src/components/app/tour/tourSteps.ts",
        "export const TOUR_SLIDES: FlatSlide[] = TOUR_CHAPTERS.flatMap(",
        'export const TOUR_SLIDES: FlatSlide[] = TOUR_CHAPTERS.filter((c) => c.id !== "plans").flatMap(',
    ),
    (
        # Skipping the tour jumped to those plans first; now it just closes.
        "web/src/components/app/tour/ProductTour.tsx",
        '        if (!jumped && slide.chapter.id !== "plans") {',
        '        if (false && !jumped && slide.chapter.id !== "plans") { // datamart: no plans chapter',
    ),
    (
        # The sign-in showcase draws its chart and ring in a hard-coded sky
        # blue; on its charcoal panel they take the red accent.
        "web/src/app/auth/_components/AuthShowcase.tsx",
        'd="M0 25 L24 22 L48 23 L72 15 L96 9 L120 3" stroke="#0ea5e9"',
        'd="M0 25 L24 22 L48 23 L72 15 L96 9 L120 3" stroke="#d61700"',
    ),
    (
        "web/src/app/auth/_components/AuthShowcase.tsx",
        'r={r} stroke="#0ea5e9"',
        'r={r} stroke="#d61700"',
    ),
]

# The Datamart theme, appended to each app's global stylesheet so it comes
# after everything it overrides.
THEME_CSS = ROOT / "datamart" / "theme" / "datamart.css"
THEME_MARK = "Datamart theme (appended by datamart/rebrand.py)"
STYLESHEETS = ["web/src/global.css", "admin/src/global.css"]

# The dark theme keeps its own copy of the sky palette (translucent washes,
# lightness flipped for dark surfaces). Keep each step's lightness and alpha and
# drop the colour, so it reads as charcoal and white like the light theme. In
# the solid-fill block (buttons and badges with white text) the darker steps go
# darker still, so white text on them keeps its contrast.
DARK_THEME = "web/src/styles/theme-dark.css"
SKY_OKLCH = re.compile(r"(--color-sky-(\d+):\s*oklch\()([\d.]+)%\s+([\d.]+)\s+([\d.]+)")
SOLID_BLOCK = ".dark :is(.theme-solid"
LIGHT_BLOCK = ".dark .theme-light {"
# Light islands inside dark mode (white cards, menus) use the light theme's
# values, taken from the @theme block in datamart/theme/datamart.css.
LIGHT_SCALE = dict(re.findall(r"--color-sky-(\d+):\s*(#[0-9a-f]{6})", THEME_CSS.read_text()))


def neutralise(text: str) -> tuple[str, int]:
    out, n, solid, light = [], 0, False, False
    for line in text.splitlines(keepends=True):
        if line.startswith(SOLID_BLOCK):
            solid = True
        elif line.startswith(LIGHT_BLOCK):
            light = True
        elif line.startswith("}"):
            solid = light = False
        if light:
            new = re.sub(r"(--color-sky-(\d+):\s*)oklch\([^)]*\)", lambda m: m.group(1) + LIGHT_SCALE[m.group(2)], line)
            n += new != line
            out.append(new)
            continue

        def grey(m: re.Match) -> str:
            nonlocal n
            n += 1
            light = float(m.group(3))
            if float(m.group(4)) == 0:
                return m.group(0)  # already neutral
            if solid and int(m.group(2)) >= 500:
                light -= 22
            return f"{m.group(1)}{light:g}% 0 0"

        out.append(SKY_OKLCH.sub(grey, line))
    return "".join(out), n


def kept(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(rel.startswith(k) for k in BRAND.get("keep_paths", []))


def text_files():
    for app in APPS:
        for sub in ("src", "index.html", "public/404.html"):
            p = ROOT / app / sub
            if p.is_file():
                yield p
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.suffix in TEXT_SUFFIXES and "node_modules" not in f.parts:
                        yield f


def main(check: bool) -> int:
    errors = []
    words = files = 0

    for f in text_files():
        if kept(f):
            continue
        text = f.read_text(encoding="utf-8")
        n = 0
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if not KEEP_LINE.search(line):
                lines[i], k = WORD.subn(NAME, line)
                n += k
        new = "".join(lines)
        if n:
            words += n
            files += 1
            if not check:
                f.write_text(new, encoding="utf-8")

    for rel, old, new in PATCHES:
        f = ROOT / rel
        if not f.exists():
            errors.append(f"{rel}: file is gone")
            continue
        text = f.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0 and new in text:
            continue  # already applied
        if count != 1:
            errors.append(f"{rel}: expected the patch anchor once, found it {count} times")
            continue
        if not check:
            f.write_text(text.replace(old, new), encoding="utf-8")

    css = THEME_CSS.read_text()
    for rel in STYLESHEETS:
        f = ROOT / rel
        if not f.exists():
            errors.append(f"{rel}: file is gone")
            continue
        text = f.read_text()
        if THEME_MARK not in text and not check:
            f.write_text(text.rstrip("\n") + "\n" + css)

    dark = ROOT / DARK_THEME
    if not dark.exists():
        errors.append(f"{DARK_THEME}: file is gone")
    else:
        text = dark.read_text()
        new, n = neutralise(text)
        if n == 0:
            errors.append(f"{DARK_THEME}: no sky palette found to recolour")
        if not check:
            dark.write_text(new)

    # Whole files we replace (the tour screenshots). Each is only valid for the
    # upstream version it was made from; a changed original means re-running
    # datamart/tools/stamp_tour_shots.py, not shipping a stale copy.
    overrides = json.loads((ROOT / "datamart" / "overrides.json").read_text())
    for rel, digest in overrides.items():
        target = ROOT / rel
        mine = ROOT / "datamart" / "overrides" / rel
        if not target.exists():
            errors.append(f"{rel}: file is gone; drop it from datamart/overrides.json")
            continue
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current == hashlib.sha256(mine.read_bytes()).hexdigest():
            continue  # already applied
        if current != digest:
            errors.append(f"{rel}: Warmbly changed it; re-run datamart/tools/stamp_tour_shots.py")
            continue
        if not check:
            shutil.copyfile(mine, target)

    assets = ROOT / "datamart" / "assets"
    copied = 0
    for app in APPS:
        src = assets / app
        if not src.is_dir():
            continue
        for a in src.rglob("*"):
            if a.is_file():
                copied += 1
                if not check:
                    dest = ROOT / app / "public" / a.relative_to(src)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(a, dest)

    for app in APPS:
        m = ROOT / app / "public" / "site.webmanifest"
        if not m.exists():
            errors.append(f"{m.relative_to(ROOT)}: file is gone")
            continue
        data = json.loads(m.read_text())
        data["name"] = NAME if app == "web" else f"{NAME} Admin"
        data["short_name"] = BRAND["short_name"] if app == "web" else "DM Admin"
        if app == "web":
            data["description"] = BRAND["description"]
            data["theme_color"] = BRAND["theme_color"]
            data["background_color"] = BRAND["background_color"]
        if not check:
            m.write_text(json.dumps(data, indent=2) + "\n")

    mode = "would change" if check else "changed"
    print(f"{mode}: {words} mentions in {files} files, {len(PATCHES)} patches, {len(overrides)} replaced files, {copied} assets, 2 manifests")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))

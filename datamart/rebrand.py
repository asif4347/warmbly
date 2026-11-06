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
  2. Applies the small code patches in PATCHES (logo, cloud banner).
  3. Copies datamart/assets/<app>/ over <app>/public/ (favicons, icons).
  4. Rewrites the two PWA manifests.

Lowercase "warmbly" (import paths, storage keys, routes) is never touched.
"""

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

# The mark drawn by the Logo component, same viewBox as upstream's.
LOGO_PATH = (
    '<path fillRule="evenodd" d="M170 112H392C537 112 652 229 652 382C652 535 537 652 392 652H170Z'
    'M290 232V532H392C470 532 532 466 532 382C532 298 470 232 392 232Z" fill="currentColor" />'
)

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
        '                fillRule="evenodd"\n                d="M170 112H392C537 112 652 229 652 382C652 535 537 652 392 652H170Z'
        'M290 232V532H392C470 532 532 466 532 382C532 298 470 232 392 232Z"',
    ),
    (
        # On an unlinked server the banner tells members local warmup "is not
        # effective" and sends them to Warmbly Cloud. In this network warmup is
        # local by design, so the banner never shows.
        "web/src/components/app/emails/CloudPoolBanner.tsx",
        "    if (!pool.manageable || pool.loading) return null;",
        "    if (true || !pool.manageable || pool.loading) return null; // datamart: no Warmbly Cloud upsell",
    ),
]


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
    print(f"{mode}: {words} mentions in {files} files, {len(PATCHES)} patches, {copied} assets, 2 manifests")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))

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
  5. Renames the product in the backend's Go strings and comments, and the
     few lowercase file names people download.

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
# The in-app AI assistant, Remie upstream, is Molty here.
ASSISTANT = re.compile(r"\bRemie\b")
ASSISTANT_NAME = "Molty"

# Lines where "Warmbly" is a real value the backend sends or expects, not a
# brand mention: the webhook signature header.
KEEP_LINE = re.compile(r'-Warmbly-')

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
        # Upstream's pool-size notice assumes a workspace warms only against its
        # own mailboxes and points at Warmbly Cloud. Here every member's
        # mailboxes form one pool across workspaces, so the notice is wrong.
        "web/src/components/app/emails/WarmupCoverageNotice.tsx",
        "    if (!canWarmup || cloudConnected || warmupCount < 1 || warmupCount >= HEALTHY_MIN) return null;",
        "    if (true || !canWarmup || cloudConnected || warmupCount < 1 || warmupCount >= HEALTHY_MIN) return null; // datamart: shared pool",
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
        # Billing is off, so upstream meters no AI at all. Charge the Datamart
        # allowance (datamart/go/datamart_allowance.go) instead.
        "internal/app/credits/service.go",
        "\t\t// No metering: report a large remaining balance without debiting.\n\t\treturn selfHostBalance, nil",
        "\t\t// No metering: report a large remaining balance without debiting.\n"
        "\t\tif err := s.datamartAllowance(ctx, orgID, amount); err != nil { // datamart\n"
        "\t\t\treturn 0, err\n"
        "\t\t}\n"
        "\t\treturn selfHostBalance, nil",
    ),
    (
        # When a workspace runs out of its free AI allowance, Molty's error
        # links to the page for asking Datamart for more (datamart/billing).
        "web/src/components/app/agent/AgentPanel.tsx",
        "                        <span>{b.message}</span>",
        "                        <span>\n"
        "                            {b.message}\n"
        '                            {b.code === "usage_cap_exceeded" && (\n'
        "                                <a\n"
        "                                    href={`/molty/unlock?org=${useAppStore.getState().currentOrganization?.id ?? \"\"}`}\n"
        '                                    className="ml-1 font-semibold underline underline-offset-2 hover:text-red-900"\n'
        "                                >\n"
        "                                    Ask for more credits\n"
        "                                </a>\n"
        "                            )}\n"
        "                        </span>",
    ),
    (
        # The demo workspace is suspended from sending and warmup with the
        # reason "Demo workspace"; its banner says so plainly instead of
        # sounding like an account review.
        "web/src/components/layout/SendingRestrictedBar.tsx",
        "    const suspended = data.suspended;",
        "    const suspended = data.suspended;\n"
        '    const demo = suspended && !!data.reason?.startsWith("Demo"); // datamart',
    ),
    (
        "web/src/components/layout/SendingRestrictedBar.tsx",
        '                suspended\n                    ? "bg-rose-50 border-rose-200 text-rose-900"',
        '                demo\n                    ? "bg-slate-50 border-slate-200 text-slate-800"\n                    : suspended\n                    ? "bg-rose-50 border-rose-200 text-rose-900"',
    ),
    (
        "web/src/components/layout/SendingRestrictedBar.tsx",
        '                    {suspended\n                        ? "Sending is paused for this workspace while it is reviewed."',
        '                    {demo\n                        ? "This is a demo workspace with sample data. Sending and warmup are switched off, so you can explore safely."\n                        : suspended\n                        ? "Sending is paused for this workspace while it is reviewed."',
    ),
    (
        "web/src/components/layout/SendingRestrictedBar.tsx",
        '<Icon className={`w-4 h-4 mt-px shrink-0 ${suspended ? "text-rose-600" : "text-amber-600"}`} />',
        '<Icon className={`w-4 h-4 mt-px shrink-0 ${demo ? "text-slate-500" : suspended ? "text-rose-600" : "text-amber-600"}`} />',
    ),
    (
        "web/src/components/layout/SendingRestrictedBar.tsx",
        "                {data.reason ? <>Reason: {data.reason}. </> : null}\n                Contact support if you think this is wrong.",
        "                {demo ? null : (\n"
        "                    <>\n"
        "                        {data.reason ? <>Reason: {data.reason}. </> : null}\n"
        "                        Contact support if you think this is wrong.\n"
        "                    </>\n"
        "                )}",
    ),
    (
        # The name authenticator apps list 2FA codes under.
        "internal/app/twofa/service.go",
        '\tissuer        = "Warmbly"',
        '\tissuer        = "Datamart Warmup"',
    ),
    (
        "internal/app/aiagent/service.go",
        'Message: "AI usage limit reached, please try again later."',
        'Message: "You have used today\'s free Molty allowance. It resets at midnight UTC. Ask Datamart if your team needs more."',
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

# Files that only exist on the datamart branch, copied into the checkout.
NEW_FILES = {
    "datamart/go/datamart_allowance.go": "internal/app/credits/datamart_allowance.go",
}

# Lowercase names people see: downloaded file names.
LOWER_SWAPS = [
    ("warmbly-recovery-codes-", "datamart-warmup-recovery-codes-"),
    ("`warmbly-${campaign.id}.png`", "`datamart-warmup-${campaign.id}.png`"),
    ("`warmbly-analytics-${range}.png`", "`datamart-warmup-analytics-${range}.png`"),
    ('"warmbly-contacts-sample.csv"', '"datamart-warmup-contacts-sample.csv"'),
]

# Backend: the product name in Go string literals and comments (error
# messages, emails, the passkey and authenticator names, the folder warmup
# mail goes into, Slack and CRM labels). Code is never touched: rule.Warmbly
# is a field. Hyphenated names (X-Warmbly-Signature, Warmbly-Webhooks/1.0)
# are protocol and stay.
GO_DIRS = ["internal", "cmd"]
GO_WORD = re.compile(r"(?<![-\w.])Warmbly(?![-\w])(?! Cloud)")
# "See https://docs.warmbly.com/..." pointers at the end of error messages.
GO_DOCS = re.compile(r" ?See https://docs\.warmbly\.com/[^\s\"`]*")


def go_text(src: str) -> tuple[str, int]:
    """Apply the name swaps inside Go strings and comments only."""
    out, n, i, L = [], 0, 0, len(src)

    def swap(s: str) -> str:
        nonlocal n
        s, a = GO_WORD.subn(NAME, s)
        s, b = ASSISTANT.subn(ASSISTANT_NAME, s)
        s, d = GO_DOCS.subn("", s) if s[:1] in "\"`" else (s, 0)
        n += a + b + d
        return s

    while i < L:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = L if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = L if j < 0 else j + 2
        elif c == "`":
            j = src.find("`", i + 1)
            j = L if j < 0 else j + 1
        elif c in "\"'":
            j = i + 1
            while j < L and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, L)
        else:
            j = i + 1
            while j < L and src[j] not in "/`\"'":
                j += 1
            out.append(src[i:j])
            i = j
            continue
        out.append(swap(src[i:j]))
        i = j
    return "".join(out), n

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
                lines[i], k2 = ASSISTANT.subn(ASSISTANT_NAME, lines[i])
                n += k + k2
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

    for src, dest in NEW_FILES.items():
        if not check:
            shutil.copyfile(ROOT / src, ROOT / dest)

    for f in text_files():
        if kept(f):
            continue
        text = f.read_text(encoding="utf-8")
        new = text
        for old, rep in LOWER_SWAPS:
            new = new.replace(old, rep)
        if new != text:
            words += 1
            if not check:
                f.write_text(new, encoding="utf-8")

    # Tests included, so tests of user-facing text expect the new name.
    for d in GO_DIRS:
        for f in sorted((ROOT / d).rglob("*.go")):
            text = f.read_text(encoding="utf-8")
            new, n = go_text(text)
            if n:
                words += n
                files += 1
                if not check:
                    f.write_text(new, encoding="utf-8")

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

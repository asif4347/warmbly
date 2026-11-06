#!/usr/bin/env python3
"""Turn one exported sample workspace into a large demo workspace.

Input: a warmblyctl org export (zip, one NDJSON file per table) of the seeded
sample workspace. Output: COPIES archives, each a fresh copy of the people,
companies, campaigns, inbox, deals and their history, to import one after the
other into the demo workspace with `warmblyctl org import`.

Per copy:
  - every UUID in a multiplied table gets a new value, the same new value in
    every table, so foreign keys still line up; ids of shared rows (mailboxes,
    pipelines, settings, the organization and its owner) are left alone;
  - each sample contact becomes a different invented person at an invented
    company on a .test domain, replaced consistently in every text field, so
    inbox senders still match their contact;
  - thread and message ids get a per-copy suffix, and every timestamp moves
    back COPY_SHIFT_DAYS * copy, spreading history over the past months;
  - campaigns get their own names and end up paused or completed, never
    active: the demo mailboxes have no credentials and cannot send.

Shared rows travel only in copy 0. Sample members and webhooks are dropped, so
the import creates no invitations and calls no outside URL.

    python3 demo_multiply.py demo.zip out_dir 8
    python3 demo_multiply.py demo.zip out_dir 8 campaign,sequences 1

The optional fourth argument limits the copies to tables starting with those
prefixes (everything else, contacts included, is then shared and only
referenced); the fifth is the first copy to write.
"""

import copy as cp
import datetime as dt
import json
import random
import re
import sys
import uuid
import zipfile
from pathlib import Path

COPY_SHIFT_DAYS = 9

# Tables whose rows are duplicated per copy. Everything else travels once.
MULTIPLY_PREFIXES = ("contact", "campaign", "sequences", "segment", "unibox", "deals", "crm_tasks",
                     "notifications", "reply_intents", "email_opens", "email_link_clicks",
                     "deliverability_events", "email_message_map", "ai_thread_drafts", "compose_drafts",
                     "meeting_bookings", "suppressed_recipients", "inbox_tag_results")
NOT_MULTIPLIED = {"contact_import_mappings", "unibox_mailboxes"}
DROP = {"organization_members", "organization_member_roles", "organization_invitations",
        "organization_invitation_roles", "team_members", "webhook_endpoints", "api_keys",
        "oauth_access_grants", "organization_member_mailbox_access", "organization_member_campaign_access"}
STRING_IDS = {"thread_id", "message_id", "parent_id", "gmail_id"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(T[\d:.]+.*)?$")

FIRST = ["Amara", "Ben", "Chiara", "Dmitri", "Elena", "Farah", "Gabriel", "Hana", "Isaac", "Jun", "Kofi",
         "Lena", "Mateo", "Nia", "Omar", "Priya", "Quentin", "Rosa", "Sven", "Tara", "Uma", "Victor",
         "Wen", "Ximena", "Yusuf", "Zoe", "Arjun", "Bianca", "Caleb", "Daria", "Emeka", "Freya",
         "Hugo", "Ines", "Jonah", "Keira", "Liam", "Maya", "Noah", "Olga", "Pablo", "Rhea", "Sami",
         "Theo", "Vera", "Will", "Yara", "Ayesha", "Bilal", "Hira", "Usman", "Zainab", "Rehan"]
LAST = ["Abara", "Bauer", "Castillo", "Dubois", "Eriksen", "Fischer", "Garcia", "Haddad", "Ito", "Jensen",
        "Khan", "Lindqvist", "Moreau", "Novak", "Okafor", "Patel", "Quinn", "Rossi", "Silva", "Tanaka",
        "Uddin", "Varga", "Walsh", "Xu", "Yilmaz", "Zimmer", "Ahmed", "Becker", "Chen", "Delgado",
        "Evans", "Farouk", "Grant", "Holm", "Iqbal", "Kowalski", "Larsen", "Mensah", "Nakamura", "Ortiz"]
CO_A = ["Brightpath", "Cedar", "Copperleaf", "Driftwood", "Evergreen", "Fieldnote", "Granite", "Harbor",
        "Ironbark", "Juniper", "Keystone", "Lanternfly", "Meridian", "Northgate", "Oakline", "Pinecrest",
        "Quarry", "Redwood", "Saltmarsh", "Tidewater", "Upland", "Vantage", "Westbrook", "Yellowfin"]
CO_B = ["Analytics", "Labs", "Digital", "Partners", "Growth", "Studio", "Systems", "Media", "Works",
        "Consulting", "Health", "Logistics", "Realty", "Software", "Ventures", "Agency"]
CAMPAIGNS = ["Q4 agency outreach", "SaaS founders, EU", "RevOps leaders follow-up", "Healthcare clinics pilot",
             "Real estate teams, Texas", "Ecommerce brands, cold intro", "Event follow-up: SaaStr",
             "Partnership asks, agencies", "Win-back: lost deals", "Webinar invite, November",
             "Logistics managers, US", "Fintech CTOs", "Recruiting firms, UK", "Local services, NYC",
             "Product launch announcement", "Case study share, warm leads", "Referral asks, customers",
             "Hiring managers, remote teams"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def shift(value: str, days: int) -> str:
    m = TS_RE.match(value)
    if not m or days == 0:
        return value
    try:
        d = dt.date.fromisoformat(m.group(1)) - dt.timedelta(days=days)
    except ValueError:
        return value
    return d.isoformat() + (m.group(2) or "")


def main(src: str, out_dir: str, copies: int, only: tuple = (), start: int = 0):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(src)
    manifest = json.loads(z.read("manifest.json"))
    tables = {}
    for t in manifest["tables"]:
        name = f"data/{t['name']}.ndjson"
        raw = z.read(name).decode() if name in z.namelist() else ""
        tables[t["name"]] = [json.loads(l) for l in raw.splitlines() if l.strip()]

    def multiplied(name: str) -> bool:
        return name not in NOT_MULTIPLIED and name.startswith(only or MULTIPLY_PREFIXES)

    # Ids that stay put: the own id of every row in a shared table, plus the org
    # and its owner. Only "id": a shared link table's campaign_id must not pin
    # the campaign it points at.
    keep = {manifest["organization_id"], manifest["organization"]["owner_user_id"]}
    for name, rows in tables.items():
        if not multiplied(name):
            for r in rows:
                if isinstance(r.get("id"), str) and UUID_RE.match(r["id"]):
                    keep.add(r["id"])
    name_pool = iter(CAMPAIGNS * 4)

    contacts = tables.get("contacts", [])
    rnd = random.Random(20261106)
    used_people = set()

    for c in range(start, copies):
        idmap = {}

        def mapid(v: str) -> str:
            if c == 0 or v in keep:
                return v
            return idmap.setdefault(v, str(uuid.uuid4()))

        # New identities for this copy (copy 0 is renamed too: the sample
        # names repeat across Warmbly demos).
        subs = []
        companies = {}
        for ct in contacts:
            while True:
                first, last = rnd.choice(FIRST), rnd.choice(LAST)
                if (first, last) not in used_people:
                    used_people.add((first, last))
                    break
            oldco = ct.get("company") or ""
            if oldco not in companies:
                companies[oldco] = f"{rnd.choice(CO_A)} {rnd.choice(CO_B)}"
            newco = companies[oldco]
            olddom = (ct.get("email") or "@x").split("@")[1]
            newdom = slug(newco) + ".test"
            oldlocal = (ct.get("email") or "").split("@")[0]
            newlocal = f"{first}.{last}".lower()
            subs += [(f"{oldlocal}@{olddom}", f"{newlocal}@{newdom}"),
                     (f"{ct.get('first_name','')} {ct.get('last_name','')}".strip(), f"{first} {last}")]
            if ct.get("first_name"):
                subs.append((ct["first_name"], first))
            if ct.get("last_name"):
                subs.append((ct["last_name"], last))
            if oldco:
                subs.append((oldco, newco))
            subs.append((olddom, newdom))
        subs.append(("warmbly.test", "northstar-demo.test"))
        subs.append(("Warmbly", "Northstar"))
        subs = sorted({a: b for a, b in subs if a}.items(), key=lambda p: -len(p[0]))

        def text(s: str) -> str:
            for a, b in subs:
                if a in s:
                    s = re.sub(r"(?<![\w.])" + re.escape(a) + r"(?![\w])", b, s)
            return s

        days = COPY_SHIFT_DAYS * c

        def walk(v, key=""):
            if isinstance(v, dict):
                return {k: walk(x, k) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x, key) for x in v]
            if isinstance(v, str):
                if UUID_RE.match(v):
                    return mapid(v)
                if key in STRING_IDS and v and c > 0:
                    return v[:-1] + f"-c{c}>" if v.endswith(">") else f"{v}-c{c}"
                if TS_RE.match(v):
                    return shift(v, days)
                return text(v)
            return v

        archive_tables = {}
        for name, rows in tables.items():
            if name in DROP or (c > 0 and not multiplied(name)):
                archive_tables[name] = []
                continue
            new = [walk(cp.deepcopy(r)) for r in rows]
            if name == "campaigns":
                for i, r in enumerate(new):
                    if c > 0:
                        r["name"] = next(name_pool)
                    if r.get("status") not in ("draft",):
                        r["status"] = "completed" if c % 2 else "paused"
            archive_tables[name] = new

        m = cp.deepcopy(manifest)
        m["members"] = []
        for t in m["tables"]:
            t["rows"] = len(archive_tables.get(t["name"], []))
        path = out / f"demo_{c}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as w:
            w.writestr("manifest.json", json.dumps(m, indent=2))
            for name in z.namelist():
                if name.startswith("data/"):
                    t = name[len("data/"):-len(".ndjson")]
                    w.writestr(name, "".join(json.dumps(r) + "\n" for r in archive_tables.get(t, [])))
                elif name != "manifest.json":
                    w.writestr(name, z.read(name))
        print(path, sum(len(v) for v in archive_tables.values()), "rows")


if __name__ == "__main__":
    only = tuple(p for p in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if p)
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), only, int(sys.argv[5]) if len(sys.argv) > 5 else 0)

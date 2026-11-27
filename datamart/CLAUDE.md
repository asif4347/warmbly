# Datamart Warmup: working notes for agents

Datamart Warmup (https://warmup.dtm.global) is Datamart Inc.'s free fork of
Warmbly (Apache 2.0): warmup network, campaigns, one inbox, deliverability,
analytics, CRM and Molty, the AI assistant. Owner: Asif.

Upstream's `CLAUDE.md` at the repo root covers the Warmbly code itself (Go
backend, workers, web, CI rules). This file covers only what is ours. How the
fork is built, synced and hosted is in [README.md](README.md); read it before
touching branches, images or the server.

## Hard rules

1. **Never edit an upstream file in a commit.** Ours lives in `datamart/`,
   `NOTICE` and `.github/workflows/datamart-*`. Anything that has to change
   upstream code goes in as a patch in `rebrand.py` or a file in `overrides/`.
2. **`rebrand.py` rewrites hundreds of upstream files in place.** That is for
   local builds and image builds only. Before any commit, check `git status`
   and stage only paths under `datamart/` (and our workflows). Never `git add -A`.
3. **No dashes in anything a person reads** (landing page, captions, emails,
   share copy). Commas or a rewrite. No "Pakistan team"; say "global
   engineering team". No client names.
4. **Never claim what the live product does not do.** On the current build,
   HubSpot, Pipedrive, Salesforce and Slack show "Coming soon". Pricing facts
   come from `landing/pricing.html` only (free, 15 AI credits per workspace a
   day, more on request).
5. **No `Co-Authored-By` trailer or "Generated with" footer** on commits.
6. **Asif ships small changes straight to production after verification.**
   Verify first, then deploy, then tell him what went live.

## Where things are

| Path | What |
|---|---|
| `rebrand.py`, `brand.json` | The brand, applied at build time (`--check` is a dry run) |
| `overrides/`, `assets/`, `theme/` | Files copied over the checkout by `rebrand.py` |
| `go/datamart_allowance.go` | The daily AI credit allowance, copied into `internal/app/credits/` at build |
| `billing/` | Molty billing service (`/molty/*` on the app domain) |
| `deploy/` | Caddyfile, compose overlay, env overlay, LiteLLM config, DNS records |
| `landing/` | Static landing, pricing, terms and privacy pages, served by Caddy |
| `landing/video/` | Hero film (45 s) and the product tour (3 min 30 s) with captions and chapters |
| `landing/img/tour/` | Product screenshots used on the landing page |
| `tools/` | Icon maker, tour screenshot stamping, demo data multiplier |

Demo films and their sources live in `../brag-output-*` folders at the repo
root (ignored by git). The newest is `brag-output-2026-11-27-demo/`: storyboard
in `build/build.py`, narration in `build/lines.tsv`, 2x screenshots in
`capture/final/`.

## Deploying the landing page

Caddy on the server serves `/opt/datamart-warmup/datamart/landing` directly,
so a landing change goes live with a pull, no restart:

1. Commit only `datamart/landing/...` on `datamart` and `git push origin datamart`.
2. On the server, over SSM, as `AWS_PROFILE=tipbx-staging` (the `datamart`
   profile key on the Mac is invalid; see the workspace's `os/index/OPS.md`):
   `cd /opt/datamart-warmup && git pull --ff-only origin datamart`
3. Check `https://warmup.dtm.global/` and the changed assets return 200.

App code (web, admin, backend) ships as images instead; see README "Updates".

## Running it locally

Needs Docker, pnpm and Go 1.25+. Go is installed at `~/.local/go-dist/go/bin`
(not on PATH by default). Clear proxy variables for the Go processes.

```bash
export PATH="$HOME/.local/go-dist/go/bin:$PATH"
python3 datamart/rebrand.py      # optional: see the Datamart brand locally
make sandbox                     # infra, migrations, seed, then all app services
```

Dashboard http://localhost:5173, API :8080, Mailpit http://localhost:18025.
Login and org are printed by `make sandbox` (upstream's seed values).

Known local issue: the seed fails with "warmup pool authority unavailable"
because seeded mailboxes default to `test_mode='off'`. Locally only, set the
column default to `'legacy'` and update existing rows, then reseed. Upstream bug,
not reported yet.

Afterwards: stop the app processes, `docker compose stop` the infra, and restore
upstream files changed by `rebrand.py` (`git status` first; restore only
tracked files outside `datamart/`, and remove the copied
`internal/app/credits/datamart_allowance.go`).

## Screenshots and films

Playwright captures run from `qa/` against the local sandbox
(`chromium.launch({ channel: "chrome" })`; the bundled browser is not
installed). The capture helpers live in `tools/capture/`; copy them into
`qa/scripts/` to run them (see its README) and delete the copies after. Hide the "SELF-HOSTED" and "dev" header badges in any image meant
for the public, and label every product screen "sample workspace".

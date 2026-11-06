# Datamart Warmup

A free mailbox warmup network for the Datamart community, built on
[Warmbly](https://github.com/warmbly/warmbly) (Apache 2.0). Each member company
gets its own workspace, and Warmbly's pairing sends warmup mail between
different workspaces, so a company's mailboxes warm other companies' mailboxes,
never each other.

## Branches

- `main` is an exact copy of Warmbly's main. Never commit to it.
- `datamart` is the default branch. It holds Warmbly's newest stable release
  plus only *new* files: this folder, `NOTICE` and the `datamart-*` workflows.
  No upstream file is edited, so merging Warmbly's updates never conflicts.

## How the brand gets in

`datamart/rebrand.py` runs right before the web and admin images are built. It
swaps the visible name, the logo, the icons in `datamart/assets/` and the app
manifests, and hides the Warmbly Cloud banner. If a Warmbly update moves code a
patch relies on, `--check` fails and the daily sync opens an issue instead of
shipping a half-branded build.

The backend, workers, tracking and realtime run Warmbly's own published images.
Platform email is branded through `EMAIL_BRAND_*` settings. One known leftover:
authenticator apps list 2FA codes under "Warmbly", because that name is fixed
in the backend.

Icons are placeholders drawn by `datamart/tools/make_icons.py`. Drop real
files into `datamart/assets/` to replace them.

## Updates

`datamart-sync` runs every day at 08:30 Lahore time:

1. switches off Warmbly's own workflows (deploys, releases, builds),
2. copies Warmbly's main onto `main`,
3. merges Warmbly's newest stable release into `datamart`,
4. checks the rebrand still applies,
5. starts `datamart-images`, which publishes
   `ghcr.io/asif4347/datamart-warmup/{web,admin}:<release>`.

The server is updated by hand, once a week, after a look at the release notes:
set `WARMBLY_TAG` and run compose again.

### One-time setup on GitHub

1. Settings > General: set the default branch to `datamart`.
2. Actions tab: enable workflows on the fork.
3. Create a fine-grained token for this repository only, with Contents,
   Workflows, Actions and Issues set to read and write. Save it as the
   `SYNC_TOKEN` Actions secret.
4. Settings > General > Features: turn on Issues, so failed syncs can be reported.
5. Run `Datamart sync` once by hand.
6. After the first image build: make the two `datamart-warmup` packages public,
   or give the server a read-only package token.

## Server

- Its own EC2 instance (4 GB RAM) in the Datamart account, with an IAM role
  allowed to send through SES. Set the instance metadata hop limit to 2 so
  containers can use the role.
- Security group: only 80 and 443 open. The compose file also publishes
  Postgres, Redis and NATS ports, which must stay closed to the internet.
- Hostnames, all DNS-only or proxied in Cloudflare under `dtm.global`:
  `warmup` (app), `warmup-admin`, `warmup-api`, `warmup-ws`, `warmup-t`
  (tracking), `warmup-forms`.
- SES: verify `mail.dtm.global` (DKIM, SPF and DMARC records in Cloudflare)
  and request production access.
- Settings: `.env.example`, then `datamart/deploy/env.datamart` on top, then
  generated secrets.
- Start: `docker compose -f docker-compose.yml -f datamart/deploy/compose.datamart.yml up -d`
- Nightly Postgres dump to S3.

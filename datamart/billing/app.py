"""Molty billing: Stripe checkout and webhook for Datamart Warmup.

Served under /molty/ on the app's own domain (Caddy forwards it):

  GET  /molty/credits?org=<organization id>
       The credit packs page: one-time packs of AI credits for that workspace.
       No sign-in needed: paying for a workspace only ever adds credits to it.
       Without Stripe settings it shows how to ask Datamart for more instead.

  GET  /molty/credits/checkout?org=<id>&price=<Stripe price id>
       Starts a one-time Stripe Checkout for one of the configured packs.

  GET  /molty/credits/done?org=<id>&session=<checkout session id>
       Where Stripe sends people back. Waits until the webhook has queued the
       credits, then returns to the app. It never credits anything itself.

  GET  /molty/unlock?org=<organization id>
       The older monthly "Molty unlocked" subscription, kept for workspaces
       that have one.

  POST /molty/stripe-webhook
       Stripe's signed notices. A paid pack checkout queues its credits in
       the Redis hash datamart:ai:grants:<org> (session id -> credits); the
       backend moves them into its Postgres credit ledger on the next balance
       read or charge, keyed on the session id so nothing is credited twice
       (datamart/go/datamart_allowance.go). Subscription events keep the
       unlocked set datamart:ai:unlocked.

Stripe is the record. Redis only snapshots to disk every few minutes, so on
start and every hour the service re-reads Stripe: the unlocked set from live
subscriptions, and every paid pack checkout the backend has not confirmed in
datamart:ai:granted is queued again.

Settings (environment):
  STRIPE_MOLTY_SECRET_KEY      Datamart's Stripe secret key (test or live)
  STRIPE_MOLTY_WEBHOOK_SECRET  signing secret of the webhook endpoint
  STRIPE_MOLTY_PACK_PRICES     comma-separated one-time price ids, one per pack.
                               Each price carries its credits in its metadata
                               ("credits": "750"), or as price_id=750 here
  STRIPE_MOLTY_PRICE_ID        the monthly "Molty unlocked" price (optional)
  APP_URL                      where to send people back to
  REDIS_URL                    the stack's Redis
"""

import html
import json
import logging
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import redis
import stripe

UNLOCKED = "datamart:ai:unlocked"  # set of organization ids
SUBS = "datamart:ai:subs"  # hash: subscription id -> organization id
GRANTS = "datamart:ai:grants:"  # hash per organization: checkout session id -> credits
GRANTED = "datamart:ai:granted"  # session ids the backend has put in its ledger
LIVE_STATUSES = {"active", "trialing", "past_due"}
PACK_KIND = "credit_pack"
SESSION_ID = re.compile(r"^cs_(test|live)_[A-Za-z0-9]+$")

APP_URL = os.environ.get("APP_URL", "").rstrip("/")
PRICE_ID = os.environ.get("STRIPE_MOLTY_PRICE_ID", "")
PACK_PRICES = [p.strip() for p in os.environ.get("STRIPE_MOLTY_PACK_PRICES", "").split(",") if p.strip()]
WEBHOOK_SECRET = os.environ.get("STRIPE_MOLTY_WEBHOOK_SECRET", "")
stripe.api_key = os.environ.get("STRIPE_MOLTY_SECRET_KEY", "")
db = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"), decode_responses=True)
log = logging.getLogger("molty-billing")

_packs_cache: tuple[float, list[dict]] = (0.0, [])


def packs() -> list[dict]:
    """The configured packs with Stripe's live prices, smallest first. Cached for five minutes."""
    global _packs_cache
    if time.time() - _packs_cache[0] < 300 and _packs_cache[1]:
        return _packs_cache[1]
    out = []
    for entry in PACK_PRICES:
        price_id, _, credits = entry.partition("=")
        price = stripe.Price.retrieve(price_id)
        credits = int(credits or (price.get("metadata") or {}).get("credits") or 0)
        if not price.get("active") or price.get("type") != "one_time" or credits <= 0 or not price.get("unit_amount"):
            log.error("pack price %s is inactive, recurring, or has no credits", price_id)
            continue
        out.append({"price": price_id, "credits": credits, "amount": price["unit_amount"], "currency": price["currency"]})
    out.sort(key=lambda p: p["credits"])
    _packs_cache = (time.time(), out)
    return out


def money(amount: int, currency: str) -> str:
    symbol = {"usd": "$", "eur": "€", "gbp": "£"}.get(currency.lower())
    value = f"{amount / 100:,.2f}".removesuffix(".00")
    return f"{symbol}{value}" if symbol else f"{value} {currency.upper()}"


def queue_grant(org: str, session_id: str, credits: int):
    if not org or credits <= 0 or db.sismember(GRANTED, session_id):
        return
    db.hset(GRANTS + org, session_id, credits)
    log.info("queued %d credits for workspace %s (checkout %s)", credits, org, session_id)


def is_paid_pack(session: dict) -> bool:
    meta = session.get("metadata") or {}
    return session.get("mode") == "payment" and session.get("payment_status") == "paid" and meta.get("kind") == PACK_KIND


def grant_from_session(session: dict):
    meta = session.get("metadata") or {}
    queue_grant(meta.get("org_id") or "", session["id"], int(meta.get("credits") or 0))


def org_from_subscription(sub: dict) -> str:
    return (sub.get("metadata") or {}).get("org_id") or db.hget(SUBS, sub["id"]) or ""


def set_unlocked(org: str, sub_id: str, live: bool):
    if not org:
        log.warning("subscription %s has no workspace", sub_id)
        return
    db.hset(SUBS, sub_id, org)
    (db.sadd if live else db.srem)(UNLOCKED, org)
    log.info("workspace %s %s (subscription %s)", org, "unlocked" if live else "locked", sub_id)


def handle_event(event: dict):
    kind, obj = event["type"], event["data"]["object"]
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded") and is_paid_pack(obj):
        grant_from_session(obj)
    elif kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        set_unlocked(obj.get("client_reference_id") or "", obj.get("subscription") or "", True)
    elif kind in ("customer.subscription.created", "customer.subscription.updated"):
        set_unlocked(org_from_subscription(obj), obj["id"], obj.get("status") in LIVE_STATUSES)
    elif kind == "customer.subscription.deleted":
        set_unlocked(org_from_subscription(obj), obj["id"], False)


def resync_subscriptions():
    """Make the unlocked set match Stripe's live subscriptions to the price."""
    live = {}
    for sub in stripe.Subscription.list(price=PRICE_ID, status="all", limit=100).auto_paging_iter():
        org = (sub.get("metadata") or {}).get("org_id")
        if org and sub["status"] in LIVE_STATUSES:
            live[sub["id"]] = org
    pipe = db.pipeline()
    pipe.delete(UNLOCKED)
    if live:
        pipe.sadd(UNLOCKED, *set(live.values()))
        pipe.hset(SUBS, mapping=live)
    pipe.execute()
    log.info("resync: %d unlocked workspaces", len(set(live.values())))


def resync_packs():
    """Queue again every paid pack the backend has not confirmed."""
    queued = 0
    for session in stripe.checkout.Session.list(status="complete", limit=100).auto_paging_iter():
        if is_paid_pack(session) and not db.sismember(GRANTED, session["id"]):
            grant_from_session(session)
            queued += 1
    log.info("resync: %d paid packs waiting for the ledger", queued)


def resync_forever():
    while True:
        for job, on in ((resync_subscriptions, PRICE_ID), (resync_packs, PACK_PRICES)):
            if not on:
                continue
            try:
                job()
            except (stripe.StripeError, redis.RedisError) as err:
                log.error("%s failed: %s", job.__name__, err)
        time.sleep(3600)


STYLE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<style>body{font:16px/1.6 system-ui,sans-serif;max-width:560px;margin:10vh auto;padding:0 16px;color:#141414;background:#fff}"
    "h1{font-size:22px;margin:0 0 8px}a.back{color:#333}.packs{display:grid;gap:10px;margin:24px 0}"
    ".pack{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #e6e6e6;border-radius:10px;padding:14px 16px}"
    ".pack b{font-size:18px}.pack small{display:block;color:#666}.buy{background:#d61700;color:#fff;text-decoration:none;font-weight:600;"
    "padding:9px 16px;border-radius:8px;white-space:nowrap}.fine{color:#666;font-size:14px}"
    "@media (prefers-color-scheme:dark){body{background:#111;color:#eee}a.back{color:#ccc}.pack{border-color:#333}.pack small,.fine{color:#aaa}}</style>"
)


class Handler(BaseHTTPRequestHandler):
    def send_html(self, status: int, doc: str, headers: dict | None = None):
        data = doc.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def back_link(self) -> str:
        return f"<p><a class=back href='{html.escape(APP_URL or '')}/app'>Back to Datamart Warmup</a></p>"

    def page(self, status: int, title: str, body: str):
        self.send_html(status, f"{STYLE}<title>{html.escape(title)}</title><h1>{html.escape(title)}</h1><p>{html.escape(body)}</p>{self.back_link()}")

    def redirect(self, url: str):
        self.send_response(303)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def request_page(self, org: str):
        """Without Stripe settings, extra credits are free on request: tell people how to ask."""
        self.send_html(
            200,
            f"{STYLE}<title>More Molty credits</title><h1>Need more Molty credits?</h1>"
            "<p>Every workspace gets free AI credits each day, and they reset at midnight UTC. "
            "If your team needs more, ask the Datamart team and we will add credits to your workspace. It is free.</p>"
            "<p>Quote your workspace ID so we know where to add them:</p>"
            "<p style='font:15px ui-monospace,Menlo,monospace;background:#f5f5f5;color:#141414;border:1px solid #e6e6e6;"
            f"border-radius:8px;padding:10px 12px;word-break:break-all;user-select:all'>{html.escape(org)}</p>"
            "<p><a class=buy href='https://dtm.global' target='_blank' rel='noopener'>Ask the Datamart team</a></p>"
            f"{self.back_link()}",
        )

    def packs_page(self, org: str):
        try:
            offered = packs()
        except stripe.StripeError as err:
            log.error("reading pack prices failed: %s", err)
            return self.page(502, "Credit packs are unavailable", "Stripe could not be reached. Please try again in a minute.")
        if not offered:
            return self.request_page(org)
        rows = []
        for p in offered:
            href = f"/molty/credits/checkout?org={quote(org)}&price={quote(p['price'])}"
            rows.append(
                f"<div class=pack><div><b>{p['credits']:,} credits</b>"
                f"<small>{money(p['amount'], p['currency'])}, one time</small></div>"
                f"<a class=buy href='{html.escape(href)}'>Buy for {money(p['amount'], p['currency'])}</a></div>"
            )
        self.send_html(
            200,
            f"{STYLE}<title>Buy Molty credits</title><h1>Buy Molty credits</h1>"
            "<p>Every workspace keeps its free AI credits each day. A credit pack adds more on top: "
            "they are used once the free ones run out, and they never expire.</p>"
            f"<div class=packs>{''.join(rows)}</div>"
            "<p class=fine>One payment, no subscription. Credits go to this workspace only, "
            "and payment is handled by Stripe.</p>"
            f"{self.back_link()}",
        )

    def checkout(self, org: str, price_id: str):
        try:
            pack = next((p for p in packs() if p["price"] == price_id), None)
        except stripe.StripeError as err:
            log.error("reading pack prices failed: %s", err)
            pack = None
        if not pack:
            return self.page(400, "Pack not found", "That credit pack is not on offer. Open Buy more credits from your workspace and pick one again.")
        meta = {"org_id": org, "credits": str(pack["credits"]), "kind": PACK_KIND}
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                client_reference_id=org,
                metadata=meta,
                payment_intent_data={"metadata": meta, "description": f"{pack['credits']:,} Molty credits"},
                success_url=f"{APP_URL}/molty/credits/done?org={org}&session={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{APP_URL}/molty/credits?org={org}",
            )
        except stripe.StripeError as err:
            log.error("checkout for %s failed: %s", org, err)
            return self.page(502, "Checkout did not open", "Stripe could not start the checkout. Please try again in a minute.")
        self.redirect(session.url)

    def done(self, org: str, session_id: str):
        if not SESSION_ID.match(session_id):
            return self.page(400, "Payment not found", "Open Buy more credits from your workspace to check your credits.")
        try:
            arrived = db.sismember(GRANTED, session_id) or db.hexists(GRANTS + org, session_id)
        except redis.RedisError:
            arrived = False
        if arrived:
            return self.redirect(f"{APP_URL}/app?credits=added")
        self.send_html(
            200,
            f"{STYLE}<meta http-equiv=refresh content=2><title>Adding your credits</title>"
            "<h1>Thanks, adding your credits</h1>"
            "<p>We are confirming the payment with Stripe. This page moves on by itself in a few seconds.</p>"
            f"{self.back_link()}",
        )

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/molty/health":
            self.send_response(204)
            self.end_headers()
            return
        if url.path not in ("/molty/credits", "/molty/credits/checkout", "/molty/credits/done", "/molty/unlock"):
            return self.page(404, "Not found", "There is nothing here.")
        org = (query.get("org") or [""])[0].strip().lower()
        try:
            uuid.UUID(org)
        except ValueError:
            return self.page(400, "Workspace missing", "Open Buy more credits from your workspace and try again.")
        if not stripe.api_key:
            return self.request_page(org)
        if url.path == "/molty/credits":
            return self.packs_page(org)
        if url.path == "/molty/credits/checkout":
            return self.checkout(org, (query.get("price") or [""])[0])
        if url.path == "/molty/credits/done":
            return self.done(org, (query.get("session") or [""])[0])
        return self.unlock(org)

    def unlock(self, org: str):
        if not PRICE_ID:
            return self.redirect(f"/molty/credits?org={org}")
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                client_reference_id=org,
                metadata={"org_id": org},
                subscription_data={"metadata": {"org_id": org}},
                allow_promotion_codes=True,
                success_url=f"{APP_URL}/app?molty=unlocked",
                cancel_url=f"{APP_URL}/app",
            )
        except stripe.StripeError as err:
            log.error("checkout for %s failed: %s", org, err)
            return self.page(502, "Checkout did not open", "Stripe could not start the checkout. Please try again in a minute.")
        self.redirect(session.url)

    def do_POST(self):
        if urlparse(self.path).path != "/molty/stripe-webhook":
            return self.page(404, "Not found", "There is nothing here.")
        payload = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            event = stripe.Webhook.construct_event(payload, self.headers.get("Stripe-Signature", ""), WEBHOOK_SECRET)
        except (ValueError, stripe.SignatureVerificationError):
            self.send_response(400)
            self.end_headers()
            return
        try:
            handle_event(json.loads(payload))
        except redis.RedisError as err:
            log.error("redis error on %s: %s", event["id"], err)
            self.send_response(500)  # Stripe retries
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if stripe.api_key and (PRICE_ID or PACK_PRICES):
        threading.Thread(target=resync_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()

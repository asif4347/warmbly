"""Molty unlock: Stripe checkout and webhook for Datamart Warmup.

Two routes, served under /molty/ on the app's own domain (Caddy forwards them):

  GET  /molty/unlock?org=<organization id>
       Starts a Stripe Checkout subscription for that workspace and redirects
       to it. No sign-in needed: paying for a workspace only ever unlocks it.

  POST /molty/stripe-webhook
       Stripe's notices. A paid checkout adds the workspace to the Redis set
       the AI allowance reads (datamart:ai:unlocked); a subscription that
       lapses or is cancelled takes it out again.

Stripe is the record. Redis only snapshots to disk every few minutes, so on
start and every hour the service rebuilds the set from Stripe's live
subscriptions to this price.

Settings (environment):
  STRIPE_MOLTY_SECRET_KEY      Datamart's Stripe secret key (test or live)
  STRIPE_MOLTY_WEBHOOK_SECRET  signing secret of the webhook endpoint
  STRIPE_MOLTY_PRICE_ID        the monthly "Molty unlocked" price
  APP_URL                      where to send people back to
  REDIS_URL                    the stack's Redis
"""

import html
import json
import logging
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import redis
import stripe

UNLOCKED = "datamart:ai:unlocked"  # set of organization ids
SUBS = "datamart:ai:subs"  # hash: subscription id -> organization id
LIVE_STATUSES = {"active", "trialing", "past_due"}

APP_URL = os.environ.get("APP_URL", "").rstrip("/")
PRICE_ID = os.environ.get("STRIPE_MOLTY_PRICE_ID", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_MOLTY_WEBHOOK_SECRET", "")
stripe.api_key = os.environ.get("STRIPE_MOLTY_SECRET_KEY", "")
db = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"), decode_responses=True)
log = logging.getLogger("molty-billing")


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
    if kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        set_unlocked(obj.get("client_reference_id") or "", obj.get("subscription") or "", True)
    elif kind in ("customer.subscription.created", "customer.subscription.updated"):
        set_unlocked(org_from_subscription(obj), obj["id"], obj.get("status") in LIVE_STATUSES)
    elif kind == "customer.subscription.deleted":
        set_unlocked(org_from_subscription(obj), obj["id"], False)


def resync():
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


def resync_forever():
    while True:
        try:
            resync()
        except (stripe.StripeError, redis.RedisError) as err:
            log.error("resync failed: %s", err)
        time.sleep(3600)


class Handler(BaseHTTPRequestHandler):
    def page(self, status: int, title: str, body: str):
        doc = (
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title>"
            "<body style='font:16px/1.6 system-ui,sans-serif;max-width:520px;margin:15vh auto;padding:0 16px;color:#141414'>"
            f"<h1 style='font-size:22px'>{html.escape(title)}</h1><p>{html.escape(body)}</p>"
            f"<p><a href='{html.escape(APP_URL or '/')}/app' style='color:#333'>Back to Datamart Warmup</a></p>"
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(doc)))
        self.end_headers()
        self.wfile.write(doc)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/molty/health":
            self.send_response(204)
            self.end_headers()
            return
        if url.path != "/molty/unlock":
            return self.page(404, "Not found", "There is nothing here.")
        org = (parse_qs(url.query).get("org") or [""])[0].strip().lower()
        try:
            uuid.UUID(org)
        except ValueError:
            return self.page(400, "Workspace missing", "Open Molty from your workspace and try the Unlock button again.")
        if not (stripe.api_key and PRICE_ID):
            return self.page(503, "Unlocking is not open yet", "Paid Molty is coming soon. Your free daily allowance resets at midnight UTC.")
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
        self.send_response(303)
        self.send_header("Location", session.url)
        self.end_headers()

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
    if stripe.api_key and PRICE_ID:
        threading.Thread(target=resync_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()

"""
Example Flask webhook file for real Stripe fulfillment.

This version is set up for a recurring Pro subscription instead of a one-time unlock.
Host it on a backend, point Stripe webhooks to it, and keep the Streamlit app as the UI.
"""

from __future__ import annotations

import os

import stripe
from flask import Flask, jsonify, request

from db import (
    get_user_by_user_id,
    get_user_by_stripe_customer_id,
    get_user_by_subscription_id,
    init_db,
    set_latest_checkout_session,
    set_subscription_state,
    upsert_user,
    verify_webhook_idempotency,
)

app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

ACTIVE_STATUSES = {"trialing", "active", "past_due"}

init_db()


def _checkout_user_id(session: dict) -> str | None:
    client_reference_id = session.get("client_reference_id") or ""
    prefix = "furuflow_user:"
    if client_reference_id.startswith(prefix):
        return client_reference_id[len(prefix):]
    metadata = session.get("metadata") or {}
    return metadata.get("user_id")


def _upsert_from_subscription(*, user_id: str | None = None, customer_id: str | None, subscription_id: str | None, status: str | None):
    user = None

    if user_id:
        user = get_user_by_user_id(user_id)

    if not user and customer_id:
        existing = get_user_by_stripe_customer_id(customer_id)
        user = existing if existing else None

    if not user and subscription_id:
        existing = get_user_by_subscription_id(subscription_id)
        user = existing if existing else None

    if not user:
        return

    upsert_user(
        user["email"],
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status=status,
        purchase_source="stripe",
    )
    set_subscription_state(
        user["email"],
        pro_active=(status in ACTIVE_STATUSES),
        subscription_status=status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        purchase_source="stripe",
    )


@app.post("/stripe/webhook")
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    event_type = event["type"]
    event_id = event.get("id")
    if event_id and not verify_webhook_idempotency(event_id, event_type):
        return jsonify({"received": True, "duplicate": True})

    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        mode = obj.get("mode")
        user_id = _checkout_user_id(obj)
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        checkout_session_id = obj.get("id")
        if user_id and checkout_session_id:
            set_latest_checkout_session(user_id, checkout_session_id)

        if mode == "subscription":
            _upsert_from_subscription(
                user_id=user_id,
                customer_id=customer_id,
                subscription_id=subscription_id,
                status="active",
            )
        else:
            # Keep one-time payments compatible if you ever sell lifetime unlocks later.
            user = get_user_by_user_id(user_id) if user_id else None
            if user:
                upsert_user(user["email"], stripe_customer_id=customer_id, purchase_source="stripe")
                set_subscription_state(
                    user["email"],
                    pro_active=True,
                    subscription_status="one_time_paid",
                    stripe_customer_id=customer_id,
                    purchase_source="stripe",
                )

    elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        customer_id = obj.get("customer")
        subscription_id = obj.get("id")
        status = obj.get("status")

        _upsert_from_subscription(
            customer_id=customer_id,
            subscription_id=subscription_id,
            status=status,
        )

    elif event_type == "invoice.payment_failed":
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        _upsert_from_subscription(
            customer_id=customer_id,
            subscription_id=subscription_id,
            status="past_due",
        )

    return jsonify({"received": True})
